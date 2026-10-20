# report-fe · CHANGE-20261014-rl-lab-ux

> 角色：Stream Frontend · 仅改 `web/` · 无部署 · 无 `backend/` / `docs/api` 变更  
> 依据：`plan.md` · `ui/ui-handoff.md` · `ui/export/01|02|02b|03-*.png` · `web/DESIGN.md`（亮色极简）  
> 日期：2026-10-15（Asia/Shanghai）

## 结论

**FE 落地完成。** `npm run build` 通过；`npm test` 52/52 通过。无 API/Schema 变更。未部署。

## 改动文件

| 文件 | 变更 |
|---|---|
| `web/src/components/AppShell.jsx` | 顶栏 h-12；顺序/权重：大厅 · **模型托管** · **API 文档** · 上传游戏 · 战绩(降权) · 好友 · 资料；无对战中心 |
| `web/src/pages/Lobby.jsx` | Hero = RL 实验室 + 训练闭环步骤条；主 CTA → `/models` + `/api.html`；次 CTA → 上传/登录；GameCard 契约/Schema/官方·UGC 优先，进入/对战 outline |
| `web/src/pages/Models.jsx` | 上传条 + 我的模型表（名称/游戏/契约/最近评估/评估·挑战·删除 + filter）+ 右侧工作台双态：挑战（步进 1–4 +「3 对手」疏开）/ 评估（排队→跑局→指标）；结果常驻工作台，去掉 Dialog-only |
| `web/src/pages/UgPvp.jsx` | 页头「验证支线」口径；找对手区「在本游戏内验证」+ 无 /arena 脚注；三 Tab 保留 |
| `web/src/index.css` | `.page-shell` 密度收紧（pt-4 / px-3–5 / pb-12） |
| `web/src/App.jsx` | 断线横幅 `top-12` 对齐新顶栏 |
| `web/src/pages/Watch.jsx` | D27：去掉指向 `/arena` 的「对战中心」链，改为「战绩」 |
| `web/src/pages/Profile.jsx` | D27：空态文案去掉「对战中心」 |

未改：`ModelChallenge.jsx`（仍供 `UgPlay` 页内嵌 compact 用）；`api.js` / hooks / 路由表（`/arena` 仍走 NotFound）。

## Smoke checklist（对照 plan.md 验证节）

| # | 项 | 结果 |
|---|---|---|
| 1 | 顶栏可见模型托管 + API 文档优先；无对战中心 | ✅ AppShell NAV；grep 无 `to="/arena"` |
| 2 | `/` Hero 主 CTA → 模型或 API；游戏卡契约信息可见 | ✅ Lobby 主按钮 + Schema/OpenEnv/契约 |
| 3 | `/models`：列表选中 ↔ 右侧工作台；挑战/评估双态可切换；对照 export 02/02b | ✅ 实现；需登录后手工点验 |
| 4 | `/games/{slug}/pvp` 仍三 Tab；直链 `/arena` 仍 NotFound（D27） | ✅ UgPvp Tabs；App.jsx `*` → NotFound |
| 5 | 亮色紧凑密度 | ✅ DESIGN 底色未改；page-shell / h-12 / gap-2–3 / p-3–4 |
| 6 | 无 antd | ✅ 无 antd import |
| 7 | build / test | ✅ `vite build`；`node --test` 52 pass |

## API / 契约观察（非 blocked）

- **无破坏性缺口**：列表/上传、`POST /api/v1/models/{id}/eval`、`POST /api/v1/matches` 均按既有契约消费。
- **观测（非 blocked）**：`POST .../eval` 路由摘要写「结果写回 meta」，但实现只返回 `metrics`、**未持久化**到 `model.meta`。FE 用会话内 `evalCache` 驱动「最近评估」与评估工作台；刷新后若 BE 未写 meta，列表会回到「未评估」。若产品要跨刷新保留，需 BE 小差分写 `meta.metrics`（破坏性无；建议另开变更，勿在本 FE 范围改 BE）。
- UGC/官方徽章：`/api/games` 无显式 official 字段；FE 以 `author` 有无近似区分（有作者 → UGC）。与 G3「注册表不区分内置/UGC」一致，仅 UI 提示。

## 范围外（未做）

- 模型广场 / 赛季 / 锦标赛
- 恢复 `/arena` 或顶栏「对战中心」
- UgPlay 全页重设计
- 部署 / Ops

## 后续

- PM：`stage` 收口；需要人工在登录态下点验 Models 工作台与 export 02/02b 观感
- BE：可选开「eval 写回 meta」小差分（非本变更阻断）
- Ops：等 `ship.md` + `human-ship` 再部署
