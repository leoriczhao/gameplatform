"""Minimal DQN training for Tetris over official OpenEnv WebSocket sessions.

The training loop and model run locally; each server slot owns one WS session.
Slots advance sequentially: n round trips per vector step, not one batch HTTP
request. Versions are pinned; rewards are sent only at reset and stay fixed
for that episode. Failed steps are not retried. All training/evaluation sockets
close on exit. Leave one server slot free for evaluation (currently --envs <= 63).
Export compatible ONNX models and upload them with PlatformClient to play.

    pip install -r sdk/requirements.txt torch && pip install -e sdk
    python training/tetris_dqn.py --base-url https://games.cree1p.com \
        --episodes 200 --envs 32 --save my_tetris_dqn.pt

Notes on the Tetris action semantics (see /api.html#tetris):
  - actions 0..2 (left/right/rotate) are FREE moves: no tick, reward 0 —
    they produce many near-duplicate transitions in the replay buffer
  - action 3 (hard drop) locks the piece, clears lines (k^2 * line reward)
    and spawns the next piece; the episode ends with a lockout
"""
import argparse
import random
import time
from collections import deque

import numpy as np
import torch
import torch.nn as nn

from gameplatform import RemoteVecEnv

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
N_ACTIONS = 4  # 0=left 1=right 2=rotate 3=hard_drop


class MLP(nn.Module):
    def __init__(self, dim, n_actions=N_ACTIONS):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(dim, 128), nn.ReLU(),
            nn.Linear(128, 64), nn.ReLU(),
            nn.Linear(64, n_actions),
        )

    def forward(self, x):
        return self.net(x)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="https://games.cree1p.com")
    ap.add_argument("--envs", type=int, default=32, help="sequential WS slots; leave one of the server slots free for eval")
    ap.add_argument("--episodes", type=int, default=200, help="total episodes to run")
    ap.add_argument("--obs", default="grid", choices=["grid"])
    ap.add_argument("--reward-line", type=float, default=1.0)
    ap.add_argument("--reward-step", type=float, default=-0.01)
    ap.add_argument("--reward-death", type=float, default=-1.0)
    ap.add_argument("--gamma", type=float, default=0.97)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--batch-size", type=int, default=128)
    ap.add_argument("--buffer-size", type=int, default=30000)
    ap.add_argument("--target-sync", type=int, default=500)
    ap.add_argument("--eps-start", type=float, default=1.0)
    ap.add_argument("--eps-end", type=float, default=0.05)
    ap.add_argument("--eps-decay", type=float, default=0.9995)
    ap.add_argument("--eval-interval", type=int, default=25)
    ap.add_argument("--throttle", type=float, default=0.02,
                    help="optional pause between vector steps (each slot uses its own WS)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--save", default="my_tetris_dqn.pt")
    args = ap.parse_args()

    torch.manual_seed(args.seed)
    random.seed(args.seed)
    np.random.seed(args.seed)

    with RemoteVecEnv(game="tetris", n=args.envs, base_url=args.base_url,
                        seed=args.seed, obs_mode=args.obs,
                        rewards={"line": args.reward_line,
                                 "step": args.reward_step,
                                 "death": args.reward_death}) as envs:
        if args.envs >= envs.max_concurrent_envs:
            raise ValueError("leave one OpenEnv slot free for evaluation: "
                             f"--envs must be below {envs.max_concurrent_envs}")
        train(envs, args)


def train(envs, args):
    print(f"[env] {args.envs} remote envs, obs={args.obs} ({envs.obs_dim} dims), "
          f"device={DEVICE}, url={args.base_url}")

    net = MLP(envs.obs_dim).to(DEVICE)
    target = MLP(envs.obs_dim).to(DEVICE)
    target.load_state_dict(net.state_dict())
    opt = torch.optim.Adam(net.parameters(), lr=args.lr)
    buf = deque(maxlen=args.buffer_size)

    obs = envs._last_obs  # constructor already reset with args.seed
    obs = obs.reshape(args.envs, -1)  # MLP input: flatten grid obs to envs.obs_dim
    eps = args.eps_start
    n_episodes = 0
    step = 0
    best_eval = 0.0
    loss = None

    def act(o, greedy=False):
        o = torch.from_numpy(np.ascontiguousarray(o)).to(DEVICE)
        with torch.no_grad():
            q = net(o)
        if greedy:
            return q.argmax(1).cpu().numpy()
        a = q.argmax(1).cpu().numpy()
        rnd = np.random.rand(len(a))
        a[rnd < eps] = np.random.randint(0, N_ACTIONS, size=(rnd < eps).sum())
        return a

    while n_episodes < args.episodes:
        time.sleep(args.throttle)
        actions = act(obs)
        obs2, rewards, dones, infos = envs.step(actions)
        obs2 = obs2.reshape(args.envs, -1)

        for i in range(args.envs):
            next_obs = (envs.terminal_obs(infos[i]).reshape(-1) if dones[i] else obs2[i])
            buf.append((obs[i], actions[i], rewards[i], next_obs, dones[i]))
        obs = obs2
        step += args.envs
        eps = max(args.eps_end, eps * args.eps_decay)

        n_episodes += int(dones.sum())

        if step % args.target_sync == 0:
            target.load_state_dict(net.state_dict())

        if len(buf) >= args.batch_size:
            batch = random.sample(buf, args.batch_size)
            s, a, r, s2, d = (torch.from_numpy(np.stack(x)).to(DEVICE)
                              for x in zip(*batch))
            with torch.no_grad():
                q_next = target(s2).max(1).values
                y = r + args.gamma * q_next * (1 - d.float())
            loss = nn.functional.smooth_l1_loss(
                net(s).gather(1, a.unsqueeze(1)).squeeze(1), y)
            opt.zero_grad()
            loss.backward()
            opt.step()

        if n_episodes and n_episodes % args.eval_interval == 0:
            eval_score, eval_lines = evaluate(net, args, episodes=3)
            best_eval = max(best_eval, eval_score)
            loss_s = f"{loss.item():.3f}" if loss is not None else "n/a"
            print(f"episodes={n_episodes} eps={eps:.3f} loss={loss_s} "
                  f"eval_score={eval_score:.0f} eval_lines={eval_lines:.0f} "
                  f"best={best_eval:.0f} steps={step}", flush=True)

    torch.save(net.state_dict(), args.save)
    print(f"saved -> {args.save}")


def evaluate(net, args, episodes=3):
    """Greedy eval on fresh seeds; returns (mean score, mean lines)."""
    scores, lines = [], []
    for _ in range(episodes):
        with RemoteVecEnv(game="tetris", n=1, base_url=args.base_url,
                         seed=random.randrange(1 << 30), obs_mode=args.obs, autoreset=False) as e:
            obs = e._last_obs.reshape(1, -1)
            for _ in range(500):  # free moves don't tick; hard drops advance
                time.sleep(0.02)
                o = torch.from_numpy(np.ascontiguousarray(obs)).to(DEVICE)
                with torch.no_grad():
                    a = int(net(o).argmax(1).item())
                obs, _r, d, info = e.step([a])
                obs = obs.reshape(1, -1)
                if d[0]:
                    scores.append(info[0]["score"])
                    lines.append(info[0]["lines"])
                    break
            else:
                scores.append(info[0]["score"])
                lines.append(info[0]["lines"])
    return float(np.mean(scores)), float(np.mean(lines))


if __name__ == "__main__":
    main()
