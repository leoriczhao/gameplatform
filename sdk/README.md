# GamePlatform Python SDK

**SDK 1.0 是破坏性大版本**：对局协议从 v1 会话接口迁移到 v2 matches（设计 17 §5）。
SDK 1.0 要求平台版本为 **M4（对局舞台 v2 全量上线）或更新**；旧平台没有
`/api/v2/matches`，SDK 不再回退到已删除的 v1 会话接口。

在仓库根目录安装：

```sh
pip install -e sdk
# 运行仓库训练脚本还需要 torch；ONNX 导出另需 onnx/onnxruntime。
```

## 平台 API 客户端：账号、模型与 v2 对局

```python
from gameplatform import PlatformClient

c = PlatformClient(base_url="https://games.cree1p.com")
c.login("alice", "secret")                  # 或 c.register(...) / c.guest()

model = c.upload_model("my_dqn.onnx", game="snake", name="我的DQN")
c.eval_model(model["id"])

# 模型对战：两个 model 座位，kind/mode 由服务端推导；返回对局 uid
uid = c.create_match(game="microrts", model_a=model["id"], model_b="ai:light_rush")
view = c.wait_match(uid)                    # 轮询 v2 快照直到终局
print(view["status"], view["result"])

# 回放：/frames 分页组装
replay = c.match_replay(uid)
print(replay["total"], replay["frames"][0]["tick"])
```

### PlatformClient 0.x → 1.0 变更

| 0.x | 1.0 |
|---|---|
| `create_match(game, model_a, model_b)` 返回 int match_id | 返回对局 **uid**（str）；POST `/api/v2/matches`，p0/p1 均为 model 座位 |
| `get_match(match_id)` 返回 v1 match | `get_match(uid)` 返回 v2 **MatchView** 快照 |
| `wait_match(match_id)` 轮询 v1 status | `wait_match(uid)` 轮询 v2 快照 status（finished/cancelled/aborted 为终局） |
| `match_replay(match_id)` 返回 v1 replay | `match_replay(uid)` 返回 `{id, frames, total}`，用 `/frames` 分页 |
| `create_room(...)` 返回 SessionClient | `create_room(...)` 返回 **MatchView**（`view["id"]` 为对局 id，`view["invite"]` 为邀请码） |
| `list_rooms` | `lobby(game, mode=None)` |
| `join_room(game, room_id, invite)` | `join_room(uid, invite=None, seat="p1")` |
| `join_quick_match` | `quick_match(game, mode="casual")` → 对局 uid |
| `queue_status` / `cancel_queue`（v1 路径） | 同语义，走 `/api/v2/{game}/matchmaking/*` |
| `active_games()` | `my_live_matches()` → `[MatchView]`（`GET /api/v2/me/matches`） |
| `chat_send` / `chat_since`（v1 会话聊天） | `send_chat(uid, text)`；读取走 `MatchView["chat"]` / SSE `chat` 事件 |

`my_matches()` **保留 v1 历史列表**（`GET /api/v1/matches`，平台保留该只读接口）：
它只返回已结束对局的历史记录，不含进行中/可重连的对局。进行中的对局用
`my_live_matches()`（v2 `GET /api/v2/me/matches`）。

### SessionClient：v2 对局客户端（语义大改）

0.x 的 `SessionClient` 包装 v1 play 会话；1.0 中它是
`GET /api/v2/matches/{uid}` 的有状态客户端：`self.match` 始终是最近一次
MatchView，`act()` 提交 `{tick, action}` 并阻塞到再次轮到自己或终局。

```python
# 单机练习：单座游戏直接开始；双座游戏默认对手由服务端决定
s = c.session("snake")
s.start_pve(seed=42)
while not s.done:
    view = s.act(pick_action(s.match))      # 返回最新 MatchView
print(s.status, s.winner, s.cause, s.tick, s.waiting_for)

# 双座游戏指定 AI 对手 / 让模型代打自己
s = c.session("microrts")
s.start_pve(opponent="worker_rush",
            controller={"type": "model", "model_id": 12})

# PvP：创建（私密房拿到邀请码）→ 对方凭 uid + 邀请码入座
host = c.session("microrts").create_pvp(mode="casual", visibility="private")
print(host.id, host.invite)
guest = c.session("microrts").join_pvp(host.id, invite=host.invite)

# 快速匹配（v2 队列；返回 match uid），然后附着到该对局
uid = c.quick_match("microrts", mode="ranked")
s = c.session("microrts", uid)

# 认输 / 再来一局 / 回放
s.resign(); s.rematch(); replay = s.replay()
```

SessionClient API：`start_pve(opponent, controller, seed)`、
`create_pvp(seed, mode, visibility)`、`join_pvp(match_id, invite, seat)`、
`act(actions)`、`poll()`、`resign()`、`rematch()`、`replay()`、
`set_controller(controller, seat=None)`；属性 `match`、`id`、`invite`、
`status`、`done`、`winner`、`cause`、`tick`、`you_seat`、
`your_turn`、`to_act`、`waiting_for`、`chat`。

### v1 → v2 字段映射

| v1 会话字段 | v2 MatchView |
|---|---|
| session.id | `view["id"]` |
| side / session.side | `view["you"]["seat"]` |
| state | `view["frame"]` |
| tick | `view["tick"]` |
| status（finished 等） | `view["status"]`：waiting / active / finished / aborted / cancelled |
| winner / cause | `view["result"]["winner"]` / `view["result"]["cause"]` |
| session.invite | `view["invite"]` |
| expected_tick（可选乐观锁） | `tick` 必填，作为幂等键（同一 seat+tick 重复提交覆盖而不推进） |
| actions 响应里的 state | 202 `{accepted, seq}` 确认；结果只从快照/流里读 |
| 会话 replay | `/api/v2/matches/{uid}/frames`（`next` 分页） |
| waiting_for | `SessionClient.waiting_for`（to_act 中尚未提交的座位） |
| 聊天 GET 轮询 | `MatchView["chat"]` / SSE `chat` 事件；发送仍为 `POST /chat` |

`act()` 的轮询语义：提交前基于上次快照的 `tick`；收到 202 后轮询快照，
直到再次轮到我（`you.seat` 在 `to_act` 中且该 tick 尚未提交）或终局。
`stale_tick`（409）会自动刷新快照并重试（最多 3 次）；`not_to_act` 会先等到
轮到自己。

### 错误

`PlatformError` 带 `code`、`status`、`detail` 属性，`code` 对应 v2 机器
可读错误码：`stale_tick`、`not_to_act`、`match_over`、`not_your_seat`、
`bad_controller` 等。

## 本地训练（默认）：游戏包在你的进程里运行

平台分发每个官方游戏包，以及作者在 game.yaml 声明了 `local_training: true` 的 UGC 包。
`LocalVecEnv` 只在首次使用时下载一次精确版本，校验 sha256 后缓存到
`$GAMEPLATFORM_CACHE`（默认 `~/.cache/gameplatform`），然后在本进程中 import 运行。
每一步只是一次函数调用，没有网络往返，也不占服务器的 64 个并发名额。

```python
from gameplatform import LocalVecEnv, evaluate, export_onnx, parity_check

with LocalVecEnv(game="snake", n=64, obs_mode="rotwin", seed=42,
                 base_url="https://games.cree1p.com") as envs:
    obs = envs.reset(seed=42)
    obs, rewards, dones, infos = envs.step(actions)   # 与 RemoteVecEnv 接口一致

export_onnx(net, envs.runtime, "my.onnx")   # 契约取自游戏包 game.yaml，UGC 同样适用
evaluate("my.onnx", envs.runtime, episodes=20, seed=0)  # 与服务端评估同一协议，固定种子
parity_check("snake", base_url="https://games.cree1p.com")  # 本地与线上逐步比对完整 state
```

- **与线上一致**：运行的是服务器上同一份包代码（D3）；调用语义（rewards 参数回退、
  JSON 边界、reset/step 规则、种子递增 100003、SAME_STEP autoreset、info 字段）与
  OpenEnv 会话相同。`parity_check` 用同一组动作分别跑本地和远程，返回第一个不一致的步数。
- **离线**：传入明确的 `version` 且已缓存时，不访问网络。
- **UGC 是第三方代码**：会以 Python 代码的形式在你的机器上运行，需要显式传入
  `trust_remote_code=True`；官方包不需要。平台对公开版本做过静态扫描和人工审核，
  但本地运行不在沙箱里。
- **开发自己的游戏包**：`load_game("./my-game")` 或 `LocalVecEnv("./my-game")`
  直接加载目录（需要 PyYAML），不需要服务器。
- 两个都使用绝对导入、且模块同名的游戏包，不能在同一个进程里同时加载
  （平台 worker 同样把包目录放进 `sys.path`）。官方游戏包使用相对导入，不受影响。

## 远程环境：官方 OpenEnv WebSocket

适用于无法在本地运行游戏包的 agent（例如只能发 HTTP/WS 的 LLM agent）。

SDK 固定依赖 `openenv==0.4.1`，每个槽使用一个官方
`GenericEnvClient(...).sync()`，连接 `/api/openenv/{game}/ws`。
不再调用旧环境 HTTP 接口，也不接受无状态 `{state, action}` 信封。
账号、模型上传和对局等 `PlatformClient` 功能使用平台 HTTP API；对局协议为
v2（见上）。

```python
import numpy as np
from gameplatform import RemoteVecEnv

with RemoteVecEnv(game="snake", n=4, base_url="http://127.0.0.1:8080",
                  obs_mode="features", seed=42,
                  rewards={"food": 10, "step": -0.1, "death": -10}) as envs:
    obs = envs.reset(seed=42)  # 构造时已 reset；显式 seed 可复现初始观测
    obs, rewards, dones, infos = envs.step(np.ones(4, dtype=np.int64))
    for i in np.flatnonzero(dones):
        terminal = envs.terminal_obs(infos[i])
```

- 首个连接在 reset 前调用官方 `state()` 读取 `environment` 描述。
  描述含 `actions/obs_modes/schemas/meta/version/max_concurrent_envs`，SDK 可从
  `envs.info` 查看。所有槽、所有后续 reset 固定使用初始化时的游戏版本。
- `new_options` 或 `reset(options=...)` 对应 OpenEnv reset 的 `options`；
  `rewards` 仅在 reset 发送，由服务端固定到本局结束，不随 step 发送。
- 服务端模式（如 `grid`）传原样 `obs_mode`，并使用 `include_state=True`。
  服务端声明与本地函数重名时，仍优先服务端模式（保持原意图）：当前 Snake
  `rotwin` 为服务端固定 R=10、1334 维，SDK 的 R 不会覆盖它。未由服务端声明的
  本地 `features/rotwin/reach` 通过 `state` 模式读取完整局面再计算。
  `obs_mode="state"` 返回完整 state 字典列表。`envs.states` 始终可用于训练 shaping。
- 官方 reset/step 返回 `StepResult`，其 `.observation` 为观测 dict；
  官方 `.state()` 返回状态 dict。SDK 消费这些官方结果，不自建网络协议。
- 标量种子给槽 i 分配 `seed+i`，`reset(seed=[...])` 可单独指定各槽种子。
  每槽每次成功 reset 后，下一局种子递增 100003；仅终局槽自动 reset。
- 默认 SAME_STEP autoreset：返回的 obs 属于新局，终局局面留在
  `infos[i]["state"]`，终局观测用 `terminal_obs(infos[i])` 获取。
  `autoreset=False` 时保留终局，必须手动 reset 后才能再 step。
- `PlatformEnv` 保留 Gymnasium 单环境手动 reset；
  `PlatformVecEnv` 为 SAME_STEP，提供 `final_obs/final_info` 和对应掩码。
  两者默认 `backend="local"`，传 `backend="remote"` 改用 OpenEnv WS。
  Gymnasium 包装器只接收数值观测。

## 容量、吞吐与退出

`1 <= n <= environment.max_concurrent_envs`（当前每游戏 64，所有连接共享）。
容量不足也可能发生在初始化中途；SDK 会关闭已经创建的所有连接。
当前实现**同步逐槽**推进，向量 step 有 n 次 WS 往返，并非一次批量 HTTP 请求；
远程高延迟链路的吞吐会比原批量接口低，增大 n 不再能摊薄网络往返。

必须使用 `with` 或在 `finally` 调用 `close()`，以释放 WS 环境和官方同步客户端线程。
网络/协议异常会关闭整个向量。**绝不重发已经发出的 step**：部分槽可能已经推进，
不能把失败操作盲目重试；需由调用者明确创建新的环境开始新局。
官方 HTTP metadata/schema/state/reset 等用于描述或独立请求，不保持跨请求会话，
持久训练必须使用 WS。游戏目录 `/api/games` 提供 `openenv_url/schema_url`。

仓库 `training/snake_dqn.py` 和 `training/tetris_dqn.py` 保留 DQN 训练/评估能力，
默认 `--backend local`。使用 `--backend remote` 时，训练及每局评估均显式关闭连接，
训练槽必须低于服务器容量，为评估留一个槽（当前最多 63，默认分别 16、32）。详见脚本 `--help`。这些说明描述代码契约，
不表示任何线上实例已经更新部署。

## 本地 SDK smoke 与上游环境注意事项

Python 要求为 >=3.10，与 OpenEnv 0.4.1 的包 metadata 一致。官方 OpenEnv 导入链
包含 Gradio/httpx；本机带裸 IPv6/方括号 IPv6 的 `NO_PROXY/no_proxy` 配置
（如 `::1,[::1]`）会触发上游 `httpx.InvalidURL: Invalid port: ':1]'`。
SDK 不修改全局代理变量；针对 loopback 测试可在进程级使用下面的合法配置。
本机 `PYTHONPATH` 指向 ROS 的 site-packages，pytest 会因此自动加载缺依赖的 ROS
插件；下面的命令用 `env -u PYTHONPATH` 规避（等价于设置
`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`）：

```sh
env -u PYTHONPATH .venv/bin/python -m pytest tests/test_sdk_v2.py -q   # 纯离线：只用假传输

env -u PYTHONPATH NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost \
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 CUDA_VISIBLE_DEVICES="" \
.venv/bin/python -m pytest tests/test_sdk_training.py -q
```

在仓库根目录执行；`tests/test_sdk_v2.py` 在导入 SDK 前会清理 `NO_PROXY` 里的
非法 IPv6 条目（原因同上），因此上面的纯离线命令在没有手工设置代理变量时也能通过。
`tests/test_sdk_training.py` 使用 `live_server` 隔离 fixture，不替换线上服务。
远端训练若依赖企业代理，按实际目标配置合法的代理排除项，而非照搬 loopback 配置。
