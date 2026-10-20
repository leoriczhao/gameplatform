# GamePlatform Python SDK

在仓库根目录安装：

```sh
pip install -e sdk
# 运行仓库训练脚本还需要 torch；ONNX 导出另需 onnx/onnxruntime。
```

## 持久环境：官方 OpenEnv WebSocket

SDK 固定依赖 `openenv==0.4.1`，每个槽使用一个官方
`GenericEnvClient(...).sync()`，连接 `/api/openenv/{game}/ws`。
不再调用旧环境 HTTP 接口，也不接受无状态 `{state, action}` 信封。
账号、模型上传和对局等 `PlatformClient` 功能仍使用各自的平台 HTTP API。

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
- `PlatformRemoteEnv` 保留 Gymnasium 单环境手动 reset；
  `PlatformRemoteVecEnv` 为 SAME_STEP，提供 `final_obs/final_info` 和对应掩码。
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
训练及每局评估均显式关闭连接；训练槽必须低于服务器容量，为评估留一个槽
（当前最多 63，默认分别 16、32）。详见脚本 `--help`。这些说明描述代码契约，
不表示任何线上实例已经更新部署。

## 本地 SDK smoke 与上游环境注意事项

Python 要求为 >=3.10，与 OpenEnv 0.4.1 的包 metadata 一致。官方 OpenEnv 导入链
包含 Gradio/httpx；本机带裸 IPv6/方括号 IPv6 的 `NO_PROXY/no_proxy` 配置
（如 `::1,[::1]`）会触发上游 `httpx.InvalidURL: Invalid port: ':1]'`。
SDK 不修改全局代理变量；针对 loopback 测试可在进程级使用下面的合法配置。
本机还有无关 ROS pytest 自动插件缺依赖，所以 smoke 显式禁用自动插件加载：

```sh
NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
CUDA_VISIBLE_DEVICES="" .venv/bin/python -m pytest tests/test_sdk_training.py -q
```

在仓库根目录执行；测试使用 `live_server` 隔离 fixture，不替换线上服务。
远端训练若依赖企业代理，按实际目标配置合法的代理排除项，而非照搬 loopback 配置。

