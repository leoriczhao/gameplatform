# CHANGE-20261015-ugplay-openenv-state plan

## 范围
- FE：`web/src/pages/UgPlay.jsx`、`UgPvp.jsx`（及同类 `inf.meta` 用法）对 `env.state()` 结果做空安全；目录 meta 回退；失败走现有 Alert，不抛未捕获。
- BE / 契约：核对 OpenEnv `state` 是否应含 `environment`；若应有则修服务端；若故意精简则文档化并保证 FE 不依赖。
- QA：新增 P0 `SMK-G01`（进 `/games/:slug`）；回归 microrts + 抽 1；写 `report-qa.md`。
- 不部署：Dev 交 `report-dev.md` → QA → human-ship → KR。

## 派工
1. **Stream Dev**：实现 + 自测（本地/对照线上复现路径）→ `report-dev.md`
2. **Stream QA**：用例入库 + 发版前冒烟 → `report-qa.md`
3. **KR 运维**：仅在 STATUS.user_ack 后发版

## Done
- report-dev + report-qa 绿
- 线上抽检 SMK-G01 P0 绿后 ship
