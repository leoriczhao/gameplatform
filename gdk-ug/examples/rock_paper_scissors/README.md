# 石头剪刀布（GDK-UG 范例 3）

- 演示：choice 型 PvP（`pvp.action: choice` + `choices` 按钮组）、PvE、1×3 记分条渲染
- PvP 动作是选项索引 0-2；平台把双方选择拼成 `{"p0": a, "p1": b}` 调用 step_state
- 自测：`python gdk-ug/test_runner.py gdk-ug/examples/rock_paper_scissors`
- 发布后通过官方 OpenEnv 的 `GenericEnvClient.reset/step/state` 交互（一条 WS 连接一个实例）；
  包内仍用 EnvAdapter。版本/seed/options 与连接释放规则见 [OpenEnv 契约](../../../docs/api/openenv.md)。
