# CHANGE-20261014-rl-lab-ux plan

> 上游：`specify.md` · `ui/ui-handoff.md` · `ui/export/`  
> 人闸：`stage.accepted`（ui，leoric 2026-10-15）  
> 视觉真相：export PNG + `web/DESIGN.md` 亮色极简 + handoff「密度/间距」；handoff 组件表若残留「暗色壳」字样，以修订节与 DESIGN 为准忽略。

## 任务

### FE（Stream Frontend · 主责）

- [x] **AppShell**：顶栏顺序/权重 = 大厅 · **模型托管** · **API 文档** · 上传游戏 · 战绩（降权）· 好友 · 资料 · …；**禁止**恢复「对战中心」/`/arena`
- [x] **Lobby `/`**：Hero = RL 实验室一句话 + 训练闭环步骤条（OpenEnv → ONNX → 托管 → 对抗）；主 CTA → `/models` 与 API 文档；次 CTA → 上传/登录；**禁止**战绩/玩/PvP 作主 CTA
- [x] **GameCard**：Schema/OpenEnv/model-contract/官方·UGC 优先；「进入」「对战」为 secondary/outline
- [x] **Models `/models`**（主路径）：
  - 上传条（游戏 · 名称 · .onnx · 上传；每游戏最多 5）
  - 左：我的模型表（名称/游戏/契约/最近评估/评估·挑战·删除）+ 游戏 filter
  - 右：工作台双态 — **挑战**（步进 1–4 + 对手区按 export `02`「3 对手」疏开）/ **评估**（排队→跑局→指标，见 `02b`）；结果常驻工作台，不单靠 Dialog
- [x] **UgPvp** `/games/:slug/pvp`：三 Tab 保留；页头「验证支线」口径；无 arena hub
- [x] **密度**：顶栏 ~48；主区 padding 12–20；`gap-2/3`、`p-3/4`；对照 `01`/`02`/`02b`/`03` PNG
- [x] **技术栈**：shadcn + Tailwind + lucide；无 antd；路由/API hooks 不变

### BE（Stream Backend）

- [x] **本变更无代码任务**（确认无改）（无 API / Schema 变更）
- [ ] 待命：若 FE 对接既有 Models eval/challenge 时发现契约缺口 → `blocked` + 说明，再开差分（破坏性 → `gate: human-scope`）

### Ops（KR 运维）

- [ ] 本阶段不部署；等 `report-fe` + `ship.md` + `human-ship`

## 接口（硬契约）

- openapi_diff: **无 API 变更**
- 兼容性: **兼容**
- 既有对接（FE 只消费，不改契约）：Models 列表/上传、`POST /api/v1/models/{id}/eval`、ModelChallenge 相关既有端点（以 `/openapi.json` 为准）

## 验证

- contract_test: 无（无 OpenAPI 差分）；回归时冒烟既有 models/eval/challenge 调用仍 2xx
- smoke:
  - 顶栏可见模型托管 + API 文档优先；无对战中心
  - `/` Hero 主 CTA → 模型或 API；游戏卡契约信息可见
  - `/models`：列表选中 ↔ 右侧工作台；挑战/评估双态可切换；对照 export `02`/`02b`
  - `/games/{slug}/pvp` 仍三 Tab；直链 `/arena` 仍 NotFound（D27）

## 交接

- FE 锁视觉依据：`ui/ui-handoff.md` + `ui/export/01|02|02b|03-*.png`
- 完成后交 `report-fe.md`；BE 若无改可交空或省略 `report-be.md`（注明无变更）
- 禁止范围膨胀：模型广场 / 赛季 / 锦标赛 / 恢复 arena

