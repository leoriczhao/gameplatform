# CHANGE-20261016-ugplay-layout ui-handoff

> 角色：UXUI · 对照 `specify.md` + `web/DESIGN.md` · **不改** `web/` / `backend/` / `specify.md` / `STATUS.yaml`  
> 范围：SPA `UgPlay` `/games/:slug`（游客态为主；已登录态布局同壳）；**不动** OpenEnv 契约 / 路由硬约束（无 `/arena`）。  
> 非目标：不删模型挑战能力；不改 UgPvp；不做全站改版。

---

## penpot

- **url**: https://design.penpot.app/#/workspace?team-id=42558d4e-b644-80d6-8008-4d5a54f92294&project-id=42558d4e-b644-80d6-8008-4d5a54f92295&file-id=0f3fb038-01f9-8046-8008-c961df342ceb&page-id=PLACEHOLDER_TBD
- **file**: Stream UI Redesign（同仓既有文件）
- **file-id**: `0f3fb038-01f9-8046-8008-c961df342ceb`
- **team-id**: `42558d4e-b644-80d6-8008-4d5a54f92294`
- **project-id**: `42558d4e-b644-80d6-8008-4d5a54f92295`
- **page**: `UgPlay Layout` · page-id **PLACEHOLDER TBD**（UXUI 建板后回填）
- **board**: `01 UgPlay Guest / Desktop` · board-id **PLACEHOLDER TBD**
- **status**: **shell pending** — 交互与多尺寸以 HTML mock 为实现真相；Penpot 只定壳层分区与 token
- **说明**: 棋盘内部缩放 / 侧栏独立滚为布局行为，**以 `ui/export/ugplay-layout-mock.html` 为准**。

---

## 页面/状态清单（相对现网 `UgPlay.jsx`）

| 页面 | 路径 | 相对现网 | 本变更要求 | 成功指标触点 |
|---|---|---|---|---|
| **UgPlay** | `/games/:slug` | **改（IA+布局）** | 双栏解耦棋盘高度；单一登录门；侧栏只排行；模型挑战迁出为本页链至 `/models` | microrts + snake 游客无双登录卡、无底部空挑战壳 |
| UgPvp | `/games/:slug/pvp` | **保持** | 「去对战」仍从本页头进入；本 CHANGE 不改 PvP 页 | — |
| Models | `/models` | **保持可达** | 本页仅链过去；不在 UgPlay 内嵌 `ModelChallenge` | 挑战主路径仍在 Models |
| UgUpload | `/ugc` | **保持可达** | 上传入口降权（次链/壳层），不抢本页主 CTA | — |

### 页内状态（设计态）

| 状态 | 说明 |
|---|---|
| **游客 · 有预览** | 左：只读棋盘 + 「棋盘预览」Badge + **唯一**登录门；右：排行榜；无侧栏登录卡；无底部模型挑战壳 |
| **游客 · 无预览** | 左：占位/动作空间说明 + 同一登录门文案（「登录后才能开始对局；游客可看棋盘和排行榜」）；右同左 |
| **已登录 · 对局中** | 左：棋盘 + 动作控件 / 再来一局 / 内置 AI（若有）；右：排行榜；登录门隐藏 |
| **已登录 · 终局 Dialog** | 保持现有提交排行 Dialog；不改业务流 |
| **窄屏** | 双栏改堆叠：棋盘在上、排行在下；侧栏 `max-height` 仍独立滚 |

---

## IA 定稿（与 specify 对齐）

1. **左栏**：棋盘预览区 + **单一**登录门（棋盘正下方；去掉侧栏第二块登录卡）。
2. **右栏**：排行榜为主（Card）；去掉侧栏登录 Alert。
3. **模型挑战**：不贴本页下方空白；改为次要链/按钮 → `/models`（文案如「去模型托管发起挑战」）。有 `meta.contract` 才显示该链。
4. **UGC / 上传**：不抢主 CTA。「上传我的游戏」改为侧栏底部 ghost/link 或依赖 AppShell，不再与登录门并列为 info Alert 内 CTA。
5. **「去对战」**：保留在 `PageHeader` actions（`pvpEnabled` 时），作为游戏内 PvP 入口（验证支线）。
6. **文案统一**：游客可预览棋盘与看排行；**登录后**可对局并上榜。禁止再出现「游客也可游玩与上榜」与左侧矛盾。

---

## 布局硬约束（棋盘尺寸无关）

> 根因：现网 `flex flex-wrap` + 左栏自然高度随格数（如 microrts 16×16 × `cellSize≈36`）撑高，侧栏跟整页被带着走，小棋盘则下方大片留白。

| 规则 | 要求 | Dev 提示（非本阶段改代码） |
|---|---|---|
| **双栏容器** | `display: grid`；桌面 `grid-template-columns: minmax(0, 1fr) 300px`；`align-items: start`；**禁止**写死「棋盘宽 : 侧栏宽」比例绑死某游戏 | 替换现 `flex flex-wrap justify-center` |
| **棋盘区视口上限** | 棋盘外层 `.board-frame`：`max-height: min(70vh, 640px)`（可微调）；`max-width: 100%`；溢出不撑高整页 | 包裹 `UgBoard` |
| **内部缩放** | 按格数适配：`scale = min(1, frameW / (cols*cell), frameH / (rows*cell))`；或给 `UgBoard` 传入算好的 `cellSize`；棋盘在 frame 内居中 | 不改 UgBoard API 也可外层 CSS `transform: scale` + 占位尺寸 |
| **侧栏独立滚** | 右栏 `position: sticky; top: <header偏移>; max-height: calc(100vh - …); overflow-y: auto`；宽度固定 ~300px | 排行再长也不被棋盘拖高 |
| **小棋盘** | 左栏不设人为 `min-height` 对齐侧栏；`align-items: start` → 不留大片白 | snake / 小 board |
| **大棋盘** | 触顶视口上限后只缩内部格，侧栏关键信息（榜前几名）始终在首屏可读 | microrts 16×16 |
| **窄屏** | `< md`：单列堆叠；棋盘 frame 仍受视口上限；排行在下可自然滚 | `grid-cols-1` |

### 多尺寸对照（验收用）

| 游戏 | 典型格数 | 期望 |
|---|---|---|
| **microrts** | 16×16 | 棋盘缩进 `board-frame`；侧栏 sticky 可读；无整页被撑出超长空白带挑战壳 |
| **snake**（或更小） | 较小 | 棋盘自然居中偏上；侧栏顶对齐；无「棋盘矮、右侧悬空一大截」观感 |
| **tetris** | 中等 | 同规则，不写死特例 |

---

## 组件差分（新 / 改 / 弃用）

### 新（布局模式，非新业务页）

| 名称 | 用途 |
|---|---|
| **UgPlayGrid** | 双栏 grid 壳：`board-col` + `side-col`；`align-items: start` |
| **BoardFrame** | 视口 `max-height` / `max-width` + 内部缩放宿主；白底对齐 DESIGN `.board-shell` |
| **SingleLoginGate** | 棋盘下唯一登录 Alert +「登录 / 注册」；文案见下 |
| **ModelsChallengeLink** | 有 contract 时：outline/ghost「去模型托管发起挑战」→ 裸 `/models`（取代整卡 `ModelChallenge`；不发明 `?game=`） |

### 改

| 项 | 要点 |
|---|---|
| **UgPlay 主布局** | `flex flex-wrap` → UgPlayGrid；左：BoardFrame + gate/控件；右：排行 Card + 可选次链 |
| **PageHeader** | 保持得分 / 去对战 / UGC badge / 作者 / 回大厅；不把上传升为主 CTA |
| **登录文案** | 统一为真实能力（见 Copy） |
| **上传入口** | 侧栏底部 `variant="ghost"` 或 `link`「上传我的游戏」→ `/ugc`；去掉与登录并列的 info 卡 |

### 弃用（本页）

| 项 | 说明 |
|---|---|
| **侧栏第二块登录 Alert** | 「游客也可游玩与上榜…」整块删除 |
| **页底 `ModelChallenge` 整卡 section** | 有 `hasModelChallenge` 时不再渲染内嵌组件；改为 ModelsChallengeLink |
| **双登录 CTA** | 全页仅 SingleLoginGate 一处 `openLogin` 按钮（游客态） |

---

## Copy 规则

| 位置 | 文案 | 禁止 |
|---|---|---|
| 预览 Badge | `棋盘预览（登录后可操作）` | — |
| 登录门（有 preview） | `上面是初始棋盘预览；登录后才能对局并上榜。` | 「游客也可游玩与上榜」 |
| 登录门（无 preview） | `登录后才能开始对局；游客可以看棋盘和排行榜。` | 与上条矛盾的侧栏文案 |
| 模型挑战链 | `去模型托管发起挑战`（次要） | 本页再挂空壳挑战工作台 |
| 上传 | `上传我的游戏`（ghost/link） | 与登录门抢主按钮样式 |

> 真实能力（现网代码口径）：游客只读预览 + 看排行；开局/提交动作需登录。Copy 必须与此一致。

---

## 对照 web/DESIGN.md

**总体：一致（亮色极简）。**

| token | 值 |
|---|---|
| 底色 | `#fafafa` |
| 表面 / 卡片 | `#ffffff` + `1px #e4e4e7` + `shadow-sm` |
| 文字 | `#19191c` · muted `#71717a` |
| 强调 | `#4F46E5` / `#4f46e5` · soft `#eef2ff` |
| 棋盘容器 | 白底 BoardFrame；格面可沿用 Snake/Tetris `#f8fafc`、Microrts `#f4f4f5/#ebebee` |
| 禁用 | glow、彩色渐变滥用、双主按钮抢 CTA |

组件：继续用既有 shadcn `Alert` / `Card` / `Button` / `Badge` / `PageHeader` / `EmptyState`；图标 `lucide-react`。

---

## 导出

路径：`docs/pm/changes/CHANGE-20261016-ugplay-layout/ui/export/`

| 文件 | 内容 |
|---|---|
| `ugplay-layout-mock.html` | **可交互/可视实现稿**：游客态双尺寸（microrts 大棋盘 + snake 小棋盘示意）；单一登录门；侧栏仅排行；无底部挑战壳；DESIGN 亮色 token |

Penpot 板导出图：建板后由 UXUI 补 `00-penpot-ugplay-guest.png` 等。

---

## Dev 验收检查（落地后 / QA 可对）

1. 游客打开 `/games/microrts` 与 `/games/snake`：**仅一处**「登录 / 注册」主按钮（棋盘下）；侧栏无第二登录卡。
2. 两页均**无**底部「模型挑战」空壳 Card；若该游戏有 contract，可见链到 `/models`。
3. microrts：棋盘不把侧栏整列撑到超长悬空；侧栏排行在首屏可读（sticky 或同视口）。
4. snake（或更小棋盘）：左栏下方无大片无意义留白逼出「模型挑战」带；侧栏顶对齐。
5. 文案无「游客也可游玩与上榜」；与「登录后才能对局并上榜」一致。
6. `pvpEnabled` 时 PageHeader「去对战」仍在；上传仅为次链。
7. 已登录态：登录门消失，动作区正常；布局规则仍适用。

---

## Dev 落地提示（非本阶段改代码）

1. 以 `ui/export/ugplay-layout-mock.html` + 本节布局表为 SoT；Penpot id 回填前勿等视觉像素级。
2. 改 `web/src/pages/UgPlay.jsx` 结构即可；优先不动 `UgBoard` API；缩放可外层 frame 或算 `cellSize`。
3. 删除侧栏 `!user && <Alert>…游客也可游玩…`；删除底部 `{hasModelChallenge && <section>…ModelChallenge…}`；改为链。
4. 路由 / hooks / OpenEnv / 分数 API **不变**。

---

## 定稿补充

**模型挑战出口**：链到裸 `/models`（现网 Models 无 `?game=` 预选；本 CHANGE 不扩查询参数）。有 `meta.contract` 才显示「去模型托管发起挑战」。
