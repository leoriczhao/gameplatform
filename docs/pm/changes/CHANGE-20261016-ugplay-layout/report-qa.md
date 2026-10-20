# CHANGE-20261016-ugplay-layout report-qa

- 环境: 制品冒烟=本地 FE；**现网复测**=`games.cree1p.com` 镜像 `ugplay-layout-20261016-1827`；测号 `qa_smoke_1015`
- 范围: handoff「Dev 验收检查」1–7 · microrts + snake · SMK-G01 回归
- 结果: **PASS**（制品 + 现网）
- 非目标: 不改业务代码；密码不入库

## 结果表

| # | 检查项 | microrts | snake | 备注 |
|---|---|---|---|---|
| 1 | 游客仅一处「登录 / 注册」（棋盘下）；侧栏无第二登录卡 | **通过** | **通过** | 主 CTA 在 `.ug-login-gate`；顶栏「登录」不计；侧栏仅排行+挑战链+ghost 上传 |
| 2 | 无底部「模型挑战」空壳；有 contract 则链 `/models` | **通过** | **通过** | 文案「去模型托管发起挑战」→ 裸 `/models`；无内嵌挑战工作台 |
| 3 | microrts：棋盘不撑超长；侧栏首屏可读 | **通过** | — | `.ug-board-frame` `max-height: min(70vh,640px)`；侧栏 `position:sticky; top:3.75rem` |
| 4 | snake：无大片留白逼出挑战带；侧栏顶对齐 | — | **通过** | 登录门紧贴 frame 下；侧栏与棋盘列顶对齐 |
| 5 | 无「游客也可游玩与上榜」；文案与能力一致 | **通过** | **通过** | 定稿：`上面是初始棋盘预览；登录后才能对局并上榜。` |
| 6 | `pvpEnabled` 时「去对战」仍在；上传为次链 | **通过** | **通过** | microrts 保留「去对战」；上传 ghost；snake 无 pvp 入口属预期 |
| 7 | 已登录：登录门消失、动作区正常、布局规则仍适用 | **通过** | — | 控件：动作/`提交`/`再来一局`/`内置 AI 演示`；仍 `.ug-play-grid`+`.ug-board-frame` |
| G01 | 进 `/games/:slug` 可加载、无 meta TypeError | **通过** | **通过** | 棋盘绘制正常 |

## 非阻塞备注

- 制品冒烟时 snake UGC `food/head.png` 曾见 403（色块回退）；现网复测未再记为阻断。
- 会话级曾见指向 `127.0.0.1:5173` 的 `ERR_CONNECTION_REFUSED`（非现网 origin），与本次页监听 0 error 无关。

## 现网复测（2026-10-16 18:28+ CST · `ugplay-layout-20261016-1827`）

| # | microrts | snake | 备注 |
|---|---|---|---|
| 1–6 游客 | **通过** | **通过** | 新 bundle：`index-8WET_-7M.js`；`ug-play-grid` / `ug-board-frame` / sticky 侧栏 / 单一登录门 / 挑战链 `/models` |
| 7 已登录 | **通过** | — | 登录门消失；动作/`提交`/`再来一局`/`内置 AI 演示` |
| G01 | **通过** | **通过** | 棋盘绘制；`pageerror`=0；无 meta TypeError |

截图：`/workspace/smoke-20261016/microrts-guest.png` · `snake-guest.png` · `microrts-logged-in.png`

## 结论

handoff 1–7 + G01：**制品 PASS · 现网 PASS**。本 CHANGE QA 收口。
