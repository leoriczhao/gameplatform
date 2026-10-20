# 猜数字（GDK-UG 范例 1）

- 演示：PvE 游玩、通用渲染器（10×10 palette 板）、内置 AI（binary 二分）、榜单（score_bounds 0-100）
- 动作：0-99 整数
- 自测：`python gdk-ug/test_runner.py gdk-ug/examples/guess_number`
- 发布后通过官方 OpenEnv 的 `GenericEnvClient.reset/step/state` 交互（一条 WS 连接一个实例）；
  包内仍用 EnvAdapter。版本/seed/options 与连接释放规则见 [OpenEnv 契约](../../../docs/api/openenv.md)。
