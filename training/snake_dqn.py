"""Minimal DQN training for Snake over official OpenEnv WebSocket sessions.

Each slot advances synchronously; n slots cost n round trips, not one batched
request. The game version is pinned and rewards are fixed at each reset.
Training/evaluation close their sockets on exit; a failed step is not retried.
Leave one server slot free for evaluation (currently at most 63 training slots).

    pip install -r sdk/requirements.txt torch && pip install -e sdk
    python training/snake_dqn.py --base-url https://games.cree1p.com \
        --episodes 300 --obs features --save my_snake_dqn.pt
"""
import argparse
import random
from collections import deque

import numpy as np
import torch
import torch.nn as nn

from gameplatform import RemoteVecEnv

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
ACTIONS = 3  # 0=turn left, 1=straight, 2=turn right (relative to heading)


class MLP(nn.Module):
    def __init__(self, dim, n_actions=ACTIONS):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(dim, 128), nn.ReLU(),
            nn.Linear(128, 64), nn.ReLU(),
            nn.Linear(64, n_actions),
        )

    def forward(self, x):
        return self.net(x)


def dist_to_food(state):
    head, food = state["body"][0], state["food"]
    return 0.0 if food is None else abs(head[0] - food[0]) + abs(head[1] - food[1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="https://games.cree1p.com")
    ap.add_argument("--envs", type=int, default=16, help="sequential WS slots; leave one of the server slots free for eval")
    ap.add_argument("--episodes", type=int, default=300, help="total episodes to run")
    ap.add_argument("--obs", default="features", choices=["features", "rotwin", "reach", "grid"])
    ap.add_argument("--reward-food", type=float, default=10.0)
    ap.add_argument("--reward-step", type=float, default=-0.1)
    ap.add_argument("--reward-death", type=float, default=-10.0)
    ap.add_argument("--gamma", type=float, default=0.9)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--batch-size", type=int, default=128)
    ap.add_argument("--buffer-size", type=int, default=20000)
    ap.add_argument("--target-sync", type=int, default=500)
    ap.add_argument("--eps-start", type=float, default=1.0)
    ap.add_argument("--eps-end", type=float, default=0.05)
    ap.add_argument("--eps-decay", type=float, default=0.9992)
    ap.add_argument("--shape-weight", type=float, default=1.0,
                    help="potential-based bonus w*(d(s) - gamma*d(s')) toward food")
    ap.add_argument("--eval-interval", type=int, default=50)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--save", default="my_snake_dqn.pt")
    args = ap.parse_args()

    torch.manual_seed(args.seed)
    random.seed(args.seed)
    np.random.seed(args.seed)

    with RemoteVecEnv(game="snake", n=args.envs, base_url=args.base_url,
                        seed=args.seed, obs_mode=args.obs,
                        rewards={"food": args.reward_food,
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
        a[rnd < eps] = np.random.randint(0, ACTIONS, size=(rnd < eps).sum())
        return a

    while n_episodes < args.episodes:
        actions = act(obs)
        states_before = envs.states  # state dicts for the shape bonus
        obs2, rewards, dones, infos = envs.step(actions)
        obs2 = obs2.reshape(args.envs, -1)

        # potential-based shaping toward the food (same formula as the repo's
        # --shape-weight: r += w * (d(s) - gamma * d(s')); on death the body is
        # unchanged so d(s') == d(s), exactly like stepping the C++ env)
        if args.shape_weight:
            for i in range(args.envs):
                d_before = dist_to_food(states_before[i])
                d_after = dist_to_food(infos[i]["state"])
                rewards[i] += args.shape_weight * (d_before - args.gamma * d_after)

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
            loss = nn.functional.smooth_l1_loss(net(s).gather(1, a.unsqueeze(1)).squeeze(1), y)
            opt.zero_grad()
            loss.backward()
            opt.step()

        if n_episodes and n_episodes % args.eval_interval == 0:
            eval_score = evaluate(net, args, episodes=3, greedy=True)
            best_eval = max(best_eval, eval_score)
            loss_s = f"{loss.item():.3f}" if loss is not None else "n/a"
            print(f"episodes={n_episodes} eps={eps:.3f} loss={loss_s} "
                  f"eval_score={eval_score:.0f} best={best_eval:.0f} steps={step}",
                  flush=True)

    torch.save(net.state_dict(), args.save)
    print(f"saved -> {args.save}")


def evaluate(net, args, episodes=3, greedy=True):
    """Greedy eval on fresh seeds; returns mean score."""
    scores = []
    for _ in range(episodes):
        with RemoteVecEnv(game="snake", n=1, base_url=args.base_url,
                         seed=random.randrange(1 << 30), obs_mode=args.obs, autoreset=False) as e:
            obs = e._last_obs.reshape(1, -1)
            score = 0
            for _ in range(2000):
                o = torch.from_numpy(np.ascontiguousarray(obs)).to(DEVICE)
                with torch.no_grad():
                    a = int(net(o).argmax(1).item())
                obs, _r, d, info = e.step([a])
                obs = obs.reshape(1, -1)
                score = info[0]["score"]
                if d[0]:
                    break
            scores.append(score)
    return float(np.mean(scores))


if __name__ == "__main__":
    main()
