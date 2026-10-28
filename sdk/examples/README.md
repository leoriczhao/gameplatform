# sdk/examples

本目录没有独立脚本——我们自己的训练脚本已提升为仓库顶层的 `training/`：

- `training/snake_dqn.py`（贪吃蛇 DQN）
- `training/tetris_dqn.py`（俄罗斯方块 DQN）

运行方式见脚本头部注释（仓库根目录执行
`pip install -r sdk/requirements.txt torch && pip install -e sdk`，
再执行 `python training/<script>.py --help`）。

环境交互已迁移到官方 OpenEnv WS，多槽为同步逐连接推进，不再是批量 HTTP。
安装、容量、种子、自动 reset 和连接释放约定见 [SDK README](../README.md)。

## 最小起步示例：用 v2 对局 API 跑一个 bot

**最低平台版本**：设计 17 M4（API v2）或更新；SDK 1.0 不再调用已删除的 v1
会话/房间/快速匹配接口。v1 → v2 的字段映射与 API 变更清单见
[SDK README](../README.md)。

```python
from gameplatform import PlatformClient

c = PlatformClient(base_url="http://127.0.0.1:8080")
c.login("alice", "secret")

# 单机练习（mode=practice / visibility=unlisted 由 SDK 自动带上）
s = c.session("snake").start_pve(seed=42)
while not s.done:
    s.act(0)                                  # 返回最新 MatchView；动作语义由游戏包决定
print(s.status, s.winner, s.cause, s.tick)
```

```python
# 模型对战：p0/p1 两个 model 座位，返回对局 uid；结果用 v2 快照轮询
uid = c.create_match(game="microrts", model_a=my_model_id, model_b="ai:worker_rush")
view = c.wait_match(uid)
replay = c.match_replay(uid)                  # /frames 分页组装的封存帧
```

需要给新用户抄的更多示例放回本目录即可（训练/评估入口仍以 `training/` 为准）。
