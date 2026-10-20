# CHANGE-20261015-ugplay-openenv-state specify

- 要解决的问题：线上 `/games/:slug`（microrts / snake / tetris 同链路）进不去，报 `Cannot read properties of undefined (reading 'meta')`。根因：OpenEnv WS `state` 现只回 `{episode_id, step_count}`，无 `environment`；`UgPlay`/`UgPvp` 对 `inf.meta` 无兜底。
- 非目标：不改 IA/路由；不做 PvP 全面回归；不扩评估/meta 持久化；与 `api-docs-light` 无关。
- 用户触点：大厅 → 进游戏页（网页玩 / 验证支线，仍须可开）。
- 成功指标：
  - `/games/microrts`（及至少 snake 或 tetris 抽 1）可加载，不炸 `meta`
  - `state` 缺 `environment` 时 FE 用目录 `g.meta` / 空对象兜底，并给出可读错误而非白屏异常
  - 若契约要求 `environment`：BE 对齐；契约变更写进 plan / OpenAPI 备注
- 风险：仅 FE 兜底会掩盖契约漂移；优先 **FE 兜底 + 契约核对**，破坏性 Schema 才 human-scope。
