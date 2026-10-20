# CHANGE-20261014-rl-lab-ux ui-handoff

> 角色：Game UI · 对照 `docs/pm/01–04` + `specify.md` · **不改** `web/` / `backend/` / `specify.md` / `STATUS.yaml`  
> 硬约束：**D27** — 不恢复 `/arena`、顶栏无「对战中心」；URL 语义保持（`/` · `/models` · `/games/{slug}/pvp` 等）  
> 非目标：不暗示模型广场 / 赛季 / 锦标赛等 `02` 中「规划」能力

---

## penpot

- **url**: https://design.penpot.app/#/workspace?team-id=42558d4e-b644-80d6-8008-4d5a54f92294&project-id=42558d4e-b644-80d6-8008-4d5a54f92295&file-id=0f3fb038-01f9-8046-8008-c961df342ceb&page-id=0f3fb038-01f9-8046-8008-c961df342cec
- **file**: Stream UI Redesign
- **file-id**: `0f3fb038-01f9-8046-8008-c961df342ceb`
- **status**: **done**（2026-10-15 修订：stage.rejected Models 列表+评估/挑战难用 → 列表 IA + 工作台双态）
- **修订**: 保留亮色紧凑与 IA；Models 改为「列表 + 右侧工作台」；新增评估结果态板 `02b`
- **boards**:
  - `01 Lab Lobby / Desktop`（AppShell 新导航 + Hero 训练闭环 + 契约优先 GameCard）
  - `02 Lab Models / Desktop`（主路径：上传条 + 我的模型表 + 挑战工作台）
  - `02b Models / Eval result`（同壳同列表；右侧工作台为评估结果态）
  - `03 Lab UgPvp / Desktop`（验证支线三 Tab；明示无 /arena）

---

## 页面/状态清单（相对 04 的增删改）

| 页面 | 路径 / 入口 | 相对 04 | 本变更要求 | 成功指标触点 |
|---|---|---|---|---|
| **AppShell** | 壳层导航 | **改** | 顶栏视觉权重与顺序：`大厅` · **模型托管** · **API 文档** · 上传游戏 · 战绩 · 好友 · 资料 · 通知 · 登录；战绩降权（可达、非主视觉）；无「对战中心」项 | 顶栏模型/API 优先 |
| **Lobby** | `/` | **改** | Hero：一句话 RL 实验室（OpenEnv/SDK → ONNX → 托管 → 对抗）；**主 CTA** → 模型托管、API/文档；次 CTA → 上传游戏 / 登录；**禁止**战绩作主按钮、禁止玩/PvP 作主 CTA。公告条保留。游戏卡见下 | 大厅主 CTA → 训练闭环 |
| **Models** | `/models` | **改（主路径 IA）** | 上传条 + **我的模型**表（名称/游戏/契约/最近评估/操作）+ 右侧**工作台**双态：挑战向导（步进）/ 评估结果（指标）；见下方 Models 专节；路径仍 `/models` | Models 触点 |
| **API 文档入口** | `/api.html`（外链可接受） | **改（壳层露出）** | AppShell 顶栏高权重链到 `static-docs/api.html`（或现网等价外链）；大厅 Hero 次主 CTA / 底栏可并存；不新建站内 docs SPA（本变更不扩范围） | API 入口触点 |
| **Game cards**（Lobby 内） | `/` 网格 | **改** | 强调：OpenEnv URL/Schema、model-contract 支持、官方/UGC 标记；「进入游戏」「对战」为**次要**操作；房间数可作活跃度提示，不主导叙事 | 游戏卡触点 |
| **UgPvp** | `/games/:slug/pvp` | **改（框定）** | 保留三 Tab：找对手 / 对局 / 排行榜；叙事为**游戏内验证**，非平台中心；无 arena hub、无跨游戏选战大厅 | 对战从游戏上下文进入 |
| UgPlay | `/games/:slug` | **可选 / 轻量** | 本变更**不做**全页重设计；仅若 AppShell/chrome 暗色体系统一需要时对齐壳层，棋盘与玩法区可延后 | — |
| Records / Friends / Profile / Notifications / UgUpload / Admin / Watch* | 既有路径 | **保持可达** | 路由与能力不变；顶栏权重按上表；不新增未上线产品面 | — |
| ~~Arena / 对战中心~~ | `/arena` | **弃用（维持）** | **禁止**恢复；`NotFound` 旧提示可保留 | D27 |

### Lobby Hero 状态（设计态）

| 状态 | 说明 |
|---|---|
| 未登录 | 主 CTA：模型托管 · API 文档；次：上传游戏 · 登录 |
| 已登录 | 同左；登录位换用户菜单（壳层） |
| 有公告 | 公告条在 Hero 上方或紧贴；不抢主 CTA |

### UgPvp 状态（框定，非本变更主画板）

| Tab | 职责 | 文案口径 |
|---|---|---|
| 找对手 | 公开房 / 匹配 / 邀请码 | 「在本游戏内验证」 |
| 对局 | 棋盘 / 聊天 / 认输 / 重赛 | 验证支线 |
| 排行榜 | 本游戏 ratings | 非平台总榜中心 |

---

## 组件差分（新 / 改 / 弃用）

### 改

| 组件 | 变更要点 |
|---|---|
| **AppShell** | 导航顺序与视觉权重；API 文档与模型托管临近、加重视觉（字重/位置，非新路由）；暗色壳默认 |
| **Lobby Hero** | 文案与 CTA 重排：训练闭环优先；步骤条/片段示意 OpenEnv → ONNX → 托管 → 评估/挑战（纯 UI，不隐含未上线能力） |
| **Lobby GameCard** | 契约优先布局：Schema/OpenEnv 链接、model-contract badge、official/UGC；Enter / PvP 降为 secondary / outline |
| **Models 页头/列表/工作台** | 紧凑上传条；列表列 IA + 评估/挑战操作；右侧工作台承载挑战步进与评估指标（非仅 Dialog）；不引入广场/赛季/锦标赛 |
| **UgPvp 页头** | 副文案标明验证支线；三 Tab 结构不变 |

### 新（设计 token / 模式，非新业务页）

| 名称 | 用途 |
|---|---|
| **Lab surface tokens** | 暗色底、表面层级、边框、indigo/violet 主色（见下节例外） |
| **Mono / tabular accent** | Schema URL、OpenEnv path、API 路径用等宽或 tabular 展示 |
| **Training-loop step strip** | Lobby Hero 内 3–4 步示意（可点击跳转 `/models` 或 `/api.html`） |
| **ContractBadge** | 游戏卡上「支持模型契约 / Schema」类中性或 info 徽章 |

### 弃用（产品叙事 / 入口层面）

| 项 | 说明 |
|---|---|
| 顶栏「对战中心」/ `/arena` 入口 | D27；本变更不得出现 |
| Lobby Hero「战绩」主按钮 | 战绩保留在顶栏降权位与 `/records` |
| 亮色 `#fafafa` 壳作为**新默认** | 见 DESIGN.md 例外；棋盘画布色可另议，壳层改暗色 lab |

---

## 对照 web/DESIGN.md

**总体：一致（亮色极简）+ 全新 UX 布局（非旧壳换皮）。** 业务逻辑、路由、API、hooks 仍遵 DESIGN §1；视觉遵 DESIGN §3 亮色极简。

### 仍一致

- 禁止 antd / `@ant-design/icons`；图标 `lucide-react`
- toast = sonner；壳层 header + `useLogin()`；页面根 `page-shell`
- shadcn/ui + Tailwind；路由与 API 不变
- 底色 `#fafafa`；卡片纯白 + `shadow-sm` / 边框 `#e4e4e7`
- 文字近黑 `#19191c`；次级 muted（实现可用 `#71717a`）
- 强调色靛蓝 `#4f46e5`（主按钮、链接、激活、焦点）
- **禁用**光晕 glow、彩色渐变滥用；状态徽章按语义色

### UX 布局差分（相对现网内容层级，非换皮）

| 点 | 说明 |
|---|---|
| AppShell 导航权重 | 模型托管 · API 文档优先；战绩降权；无对战中心 |
| Lobby Hero | 训练闭环步骤条 + 主 CTA→模型/API |
| GameCard | Schema/OpenEnv/契约优先；进入/对战次要 |
| Models | 列表列 IA + 工作台（评估/挑战）双态；主路径叙事 |
| UgPvp | 验证支线口径；路径仍 `/games/{slug}/pvp` |

### 可选实现提示（不破 DESIGN）

- Schema / OpenEnv / API 路径可用 `font-mono` 或 tabular
- 圆角 ~6–8px（`rounded-md`）偏控制台清晰度
- 游戏画布浅色板可保持 DESIGN 既有值

---

## 导出

- 目录：`docs/pm/changes/CHANGE-20261014-rl-lab-ux/ui/export/`
- 文件：
  - `01-lab-lobby-desktop.png`
  - `02-lab-models-desktop.png`
  - `02b-lab-models-eval-desktop.png`
  - `03-lab-ugpvp-desktop.png`

---

## Penpot boards（本阶段已齐）

1. **AppShell** 亮色顶栏 + 导航：大厅 · **模型托管** · **API 文档** · 上传游戏 · 战绩 · 好友 · 资料（战绩降权；无对战中心）
2. **Lobby** Hero 训练闭环步骤 + 主 CTA 模型托管/API；GameCard×3（Snake/Tetris 官方 + GridWorld UGC），契约/Schema 优先，进入/对战为次要
3. **Models（02）** 上传条 + 我的模型表 + 右侧**挑战**工作台（步进 1–4 + 最近挑战）
4. **Models Eval（02b）** 同壳同表；右侧**评估**工作台（排队→跑局→指标 + CTA「用此模型发起挑战」）
5. **UgPvp** 三 Tab +「验证支线」口径 + 无 /arena 脚注

---

## Models 专节（FE 实现对照）

### 信息架构

| 区域 | 内容 |
|---|---|
| 页头 | 标题「模型托管」；副文案「ONNX 上传 → 契约校验 → 评估 → 挑战」 |
| 上传条（单行） | 游戏 Select · 名称 Input · 文件/.onnx · primary「上传」· 注「每游戏最多 5 个 · 契约不符会拒」 |
| 左：我的模型 | 可选游戏 filter chips；表列见下 |
| 右：工作台 | 模式 pill：**挑战**（02）或 **评估**（02b）；标题带所选模型名 |

### 列表列

| 列 | 说明 |
|---|---|
| 名称 | 如 `snake-dqn-v3` |
| 游戏 | slug（snake / tetris / microrts） |
| 契约 | badge：通过 / 不符 |
| 最近评估 | 未评估 · 通过+score · 失败 ·（可选）评估中 |
| 操作 | outline「评估」· primary/link「挑战」· 删除 |

样例行态：`snake-dqn-v3` 已评估通过（选中）· `tetris-ppo` 未评估 · `microrts-bc` 评估失败。

### 工作台 · 挑战（板 02）

- Stepper：`1 游戏` → `2 我的模型` → `3 对手` → `4 发起`（示意步 3 激活）
- 字段：游戏 chip（来自所选模型）· 我的模型锁定 · 对手 radio「内置 AI | 对手模型 ID」· AI 策略 Select · primary「发起挑战」
- 下方「最近挑战」迷你表：对局 id · 结果 · 状态（运行中/完成）·「回放」链接

### 工作台 · 评估（板 02b）

- Stepper：`1 排队` → `2 跑局` → `3 指标`（示意已完成到指标）
- 状态条：评估完成 + episodes/契约摘要
- 指标卡：`win_rate` · `avg_reward` · `episodes`（可附 avg_len 等）
- CTA：primary「用此模型发起挑战」· outline「重新评估」
- 口径：评估结果常驻工作台，避免只靠 Dialog；**不宣称 API 变更**（仍可对接既有 `POST /api/v1/models/{id}/eval` 与 ModelChallenge）

### 禁止

- 无 `/arena` · 无广场/赛季/锦标赛 · URL 保持 `/models`

---

## 给 PM / FE 的交接摘要

- 制品路径：本文件 + Penpot canonical link  
- 无 API 变更预期（视觉/IA 权重）；破坏性 API 不在本阶段  
- FE 锁视觉前须 PM `stage.accepted`（见 `05` §2.2）  
- 实现时禁止恢复 `/arena`；禁止把玩/PvP/战绩做成大厅主 CTA

---


## 密度 / 间距（紧凑修订）

| 项 | 约定 |
|---|---|
| 画板 | Desktop ≈ 1280 宽；顶栏 48 |
| 主区 padding | 12–20（勿再回到 32–48 大留白） |
| 区块 gap | 主列 ≈ 10–12；Hero 内 ≈ 8 |
| 卡片 | padding 10–12；卡间距 ≈ 10；圆角 4–6 |
| 字号 | Hero 标题 ≈ 20；正文 12；辅助 10–11 |
| FE | 实现时优先 `gap-2/3`、`p-3/4`、`h-12` 顶栏节奏，避免大面积空带 |

## 修订

- 2026-10-15：`stage.rejected`（用户不要暗色 lab 默认壳）→ Penpot / export / 本文件改为亮色极简；IA 与页面清单不变；重新 `stage.ready`。
- 2026-10-15：`stage.rejected`（太空太散）→ 压缩顶栏/主区留白、Hero/步骤/CTA/GameCard 密度；亮色+IA 不变；重新 `stage.ready`。
- 2026-10-15：`stage.rejected`（Models 列表 + 评估/挑战难用）→ 重建 `02` 列表列 IA + 挑战工作台；新增 `02b` 评估结果态；Lobby/UgPvp 未改；重新 `stage.ready`。

- 2026-10-15 Models 工作台「3 对手」布局疏开重排（用户反馈挤/错位）。
