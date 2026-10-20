# sdk/examples

本目录已清空——我们自己的训练脚本已提升为仓库顶层的 `training/`：

- `training/snake_dqn.py`（贪吃蛇 DQN）
- `training/tetris_dqn.py`（俄罗斯方块 DQN）

运行方式见脚本头部注释（仓库根目录执行
`pip install -r sdk/requirements.txt torch && pip install -e sdk`，
再执行 `python training/<script>.py --help`）。

环境交互已迁移到官方 OpenEnv WS，多槽为同步逐连接推进，不再是批量 HTTP。
安装、容量、种子、自动 reset 和连接释放约定见 [SDK README](../README.md)。

需要给新用户抄的“最小起步示例”如果将来要恢复，放回本目录即可。
