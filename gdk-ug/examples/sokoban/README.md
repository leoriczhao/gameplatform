# 推箱子（GDK-UG 范例 2）

- 演示：PvE 游玩、units 渲染约定（worker/box 两类单位 + 地形 palette）、榜单
- 动作：方向 0=上 1=右 2=下 3=左
- 自测：`python gdk-ug/test_runner.py gdk-ug/examples/sokoban`
- 发布后通过官方 OpenEnv 的 `GenericEnvClient.reset/step/state` 交互（一条 WS 连接一个实例）；
  包内仍用 EnvAdapter。版本/seed/options 与连接释放规则见 [OpenEnv 契约](../../../docs/api/openenv.md)。
