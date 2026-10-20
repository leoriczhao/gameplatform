# CHANGE-20261015-api-docs-light ui-handoff

> 角色：UXUI · 对照 `specify.md` + `web/DESIGN.md` · **不改** `web/` / `backend/` / `specify.md` / `STATUS.yaml`  
> 范围：静态 `/api.html`（`static-docs/api.html`）页内 IA + 亮色壳；**非 SPA**；顶栏外链保持；`architecture.html` 不纳入。  
> 非目标：不发明新 API；不改 OpenAPI 契约正文真相。

---

## penpot

- **url**: https://design.penpot.app/#/workspace?team-id=42558d4e-b644-80d6-8008-4d5a54f92294&project-id=42558d4e-b644-80d6-8008-4d5a54f92295&file-id=0f3fb038-01f9-8046-8008-c961df342ceb&page-id=264b121a-4ed6-8057-8008-cae3c5eb38ae
- **file**: Stream UI Redesign（同仓既有文件）
- **file-id**: `0f3fb038-01f9-8046-8008-c961df342ceb`
- **page**: `API Docs Light` · page-id `264b121a-4ed6-8057-8008-cae3c5eb38ae`
- **board**: `01 API Docs / Desktop` · board-id `264b121a-4ed6-8057-8008-cae3c5ec5d5c`
- **status**: **done**（2026-10-15）
- **说明**: 粘性 TOC / 检索过滤为交互行为，**以 HTML mock 为实现真相**；Penpot 板只定壳层分区与 token。

---

## 页面/状态清单（相对现网 `static-docs/api.html`）

| 页面 | 路径 | 相对现网 | 本变更要求 | 成功指标触点 |
|---|---|---|---|---|
| **API 文档** | `/api.html` | **改（IA+亮色）** | 亮色壳对齐 DESIGN；粘性侧栏 TOC；训练闭环入口；检索过滤 mock；亮色 `code/pre` | 找「模型/OpenEnv/鉴权」短于现长滚 |
| AppShell 外链 | 顶栏「API 文档」 | **保持** | 仍链 `/api.html`；不新建站内 docs SPA | 入口不变 |
| architecture | `/architecture.html` 等 | **不纳入** | — | — |

### 页内状态（设计态）

| 状态 | 说明 |
|---|---|
| 默认落地 | 顶：训练闭环入口卡 + 接口分类总览；侧栏「快速开始」高亮 |
| TOC 定位 | 点击侧栏 → 锚到真实 h2 id（见下表） |
| 检索过滤 | 输入过滤侧栏分组与条目；提示文案标明「非全文引擎」 |
| 窄屏 | 侧栏改堆叠在正文上方（mock 已示意） |

---

## TOC 分组（锚定真实 `api.html` h2 id）

| 分组标签 | 锚点 id |
|---|---|
| **快速开始** | `#quickstart`（新增训练闭环入口）· `#overview`（给「接口分类总览」补 id） |
| **鉴权与账号** | `#auth` |
| **环境 OpenEnv** | `#env` · `#openenv` |
| **游玩** | `#play` |
| **模型** | `#models` · `#custom` · `#sdk` |
| **对战积分** | `#matches` · `#scores` |
| **平台/游戏** | `#platform` · `#snake` · `#tetris` · `#microrts` · `#ai` |
| **运营与社交** | `#ops` · `#growth` · `#social` · `#ugc` · `#gdk` |

> Dev 落地时：现网正文 h2 id **保持不变**；仅新增 `#quickstart` 区块与 `#overview` id；侧栏 TOC 按上表重组（替换页内旧 `.toc` 块）。

---

## 组件差分（新 / 改 / 弃用）

### 新

| 名称 | 用途 |
|---|---|
| **DocsShell** | 顶栏（Stream · 大厅 · 模型托管 · API 文档 · Swagger）+ 双栏 layout |
| **StickyToc** | `position: sticky` 侧栏；分组标签 + 锚链；滚动高亮当前节 |
| **TocSearch** | 轻量过滤（TOC 文案 / 标题 / id）；非全文搜索引擎 |
| **TrainingLoopHero** | 快速开始卡：OpenEnv → SDK → 托管 → 游玩 → 积分；链到对应锚点 |
| **LightCode** | `pre/code` 亮色：底 `#f4f4f5`、边 `#e4e4e7`、字 `#18181b` |

### 改

| 项 | 要点 |
|---|---|
| 色板 | 暗色 `--bg:#0d1117` → DESIGN 亮色 `#fafafa` / 表面白 / 墨字 `#19191c` / 强调 `#4f46e5` |
| 页内 TOC | 从正文顶部长列表 → 左侧粘性分组 TOC |
| note / warn | 亮色语义底（indigo-soft / red-soft），保持左边线 |

### 弃用

| 项 | 说明 |
|---|---|
| 正文顶部旧 `.toc` 卡片 | 由侧栏取代（避免双目录） |
| 暗色 code 面板 | 改为 LightCode |

---

## 对照 web/DESIGN.md

**总体：一致（亮色极简）。**

| token | 值 |
|---|---|
| 底色 | `#fafafa` |
| 表面 / 卡片 | `#ffffff` + `1px #e4e4e7` + 轻 shadow |
| 文字 | `#19191c` · muted `#71717a` |
| 强调 | `#4f46e5` · soft `#eef2ff` |
| 禁用 | glow / 彩色渐变滥用 |

例外：本页为**静态 HTML**（非 React/shadcn），token 以 CSS 变量对齐 DESIGN，不引入 antd。

---

## 导出

路径：`docs/pm/changes/CHANGE-20261015-api-docs-light/ui/export/`

| 文件 | 内容 |
|---|---|
| `api-docs-light-mock.html` | **可交互实现稿**（粘性 TOC + 检索 + 亮色 code；正文摘自现网 api.html，未捏造契约） |
| `00-penpot-api-docs-desktop.png` | Penpot 壳层板导出 |
| `01-api-docs-light-overview.png` | 落地：闭环入口 + 总览 |
| `02-api-docs-light-models.png` | `#models` 节 + 亮色 code |
| `03-api-docs-light-openenv.png` | `#openenv` 节 |
| `04-api-docs-light-mobile.png` | 窄屏 TOC 堆叠 |
| `05-api-docs-light-search-models.png` | 检索「模型」过滤 TOC |
| `06-api-docs-light-code-auth.png` | `#auth` 亮色 code 块 |

---

## Dev 落地提示（非本阶段改代码）

1. 以 `ui/export/api-docs-light-mock.html` 为壳层/IA 参考，把样式与侧栏结构合入 `static-docs/api.html`（保留全部现有章节正文）。
2. 给「接口分类总览」加 `id="overview"`；在其前插入 `#quickstart` 训练闭环卡（文案可用 mock，勿改接口表真相）。
3. 删除或不再渲染旧 `.toc`；侧栏 TOC 严格用上表 id。
4. 顶栏外链保持与 AppShell 一致（大厅 / 模型托管 / API 文档 / Swagger）。
5. 检索保持轻量过滤即可（specify 已允许）。
