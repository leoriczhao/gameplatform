# CHANGE-20261016-ugplay-layout report-dev

- commits / 变更摘要: FE only。`UgPlay` 主布局 `flex flex-wrap` → UgPlayGrid；BoardFrame（`max-height: min(70vh, 640px)` + transform 内部缩放）；侧栏 sticky 只排行；删侧栏第二登录卡与「游客也可游玩与上榜」；删底部内嵌 `ModelChallenge`，有 `meta.contract` 时改链裸 `/models`；上传改侧栏 ghost。未部署。
- 覆盖任务:
  - [x] UgPlayGrid：`minmax(0,1fr) 300px`，`align-items: start`；窄屏堆叠
  - [x] BoardFrame：视口上限 + 内部缩放（解耦 microrts 16×16 / snake 等）
  - [x] 侧栏 sticky + 独立滚；排行主卡；上传 ghost → `/ugc`
  - [x] 单一登录门；删侧栏第二登录 Alert
  - [x] 删底部 ModelChallenge 整卡；ModelsChallengeLink → `/models`
  - [x] Copy 按 handoff（预览 Badge + 统一登录文案）
  - [x] `report-dev.md` + 自测对照 handoff 1–7
- 触及: web（FE only）
- 开发自测: 通过（静态 + 缩放公式；现网浏览器冒烟交 QA）

## 对照 handoff「Dev 验收检查」1–7

| # | 检查项 | 结果 | 说明 |
|---|---|---|---|
| 1 | 游客 microrts / snake **仅一处**「登录 / 注册」（棋盘下）；侧栏无第二登录卡 | **PASS（代码）** | 侧栏 `!user && <Alert>游客也可…` 已删；全页仅 SingleLoginGate 一处 `登录 / 注册` |
| 2 | 无底部「模型挑战」空壳；有 contract 则链 `/models` | **PASS（代码）** | 移除 `ModelChallenge` import 与 section；`hasModelChallenge` → outline「去模型托管发起挑战」→ 裸 `/models` |
| 3 | microrts：棋盘不把侧栏撑超长；侧栏首屏可读 | **PASS（公式）** | BoardFrame `max-height: min(70vh,640px)`；16×16@36px → 短视口 scale&lt;1（例 vh=600 → s≈0.69, hostH≈396）；侧栏 `position:sticky` |
| 4 | snake：无大片留白逼出挑战带；侧栏顶对齐 | **PASS（公式+布局）** | 小棋盘 s=1；`align-items:start` 左栏随内容高度；无底部挑战壳 |
| 5 | 无「游客也可游玩与上榜」；与「登录后才能对局并上榜」一致 | **PASS（代码）** | 预览态文案已统一；矛盾侧栏文案已删 |
| 6 | `pvpEnabled` 时「去对战」仍在；上传为次链 | **PASS（代码）** | PageHeader 保留；上传 `variant="ghost"` → `/ugc` |
| 7 | 已登录：登录门消失，动作区正常；布局规则仍适用 | **PASS（代码）** | `{!user ? gate : controls}`；BoardFrame / grid 与登录无关 |

### 缩放公式抽检（与 BoardFrame 同式）

- microrts 576×576、frameW=700、vh=800 → s≈0.93, host≈536（触顶 70vh）
- microrts 同上、vh=600 → s≈0.69, host≈396
- snake 288×288、frameW=700、vh=800 → s=1（不缩）

## 变更文件

- `web/src/pages/UgPlay.jsx` — BoardFrame + UgPlayGrid 布局；删双登录 / 内嵌 ModelChallenge
- `web/src/index.css` — `.ug-play-grid` / `.ug-board-frame` / `.ug-side-col` 等
- `docs/pm/changes/CHANGE-20261016-ugplay-layout/report-dev.md`

## 非目标（未做）

- OpenEnv / 路由 / UgPvp / Models 业务；未发明 `?game=`；未部署

## 交 QA

现网 `/games/microrts` + `/games/snake` 游客态对照 handoff 1–7 + G01 回归 → `report-qa.md`。
