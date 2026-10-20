# CHANGE-20261016-ugplay-layout plan

## 范围
- FE only：`web/src/pages/UgPlay.jsx`（及必要样式）；以 `ui/ui-handoff.md` + `ui/export/ugplay-layout-mock.html` 为 SoT。
- 不做：OpenEnv / 路由 / UgPvp / Models 业务；不发明 `?game=`；不部署。

## 实现要点
1. `flex` → UgPlayGrid（`minmax(0,1fr) 300px`，`align-items: start`）
2. BoardFrame：`max-height: min(70vh, 640px)` + 内部缩放
3. 侧栏 sticky + 独立滚；只留排行；上传改 ghost/link
4. 单一登录门；删侧栏第二登录卡与矛盾文案
5. 删底部 `ModelChallenge` 整卡；有 contract 时链裸 `/models`
6. 验收：handoff「Dev 验收检查」1–7；至少 microrts + snake

## 派工
1. **Stream Dev** → `report-dev.md`（含自测）
2. **Stream QA** → 对照 handoff 清单 + G01 回归 → `report-qa.md`
3. human-ship → KR

## Done
- report-dev + report-qa
- 游客无双登录、无底部空挑战壳；棋盘尺寸解耦
