# CHANGE-20261015-api-docs-light plan

> 上游：`specify.md` · `ui/ui-handoff.md` · `ui/export/`（含 `api-docs-light-mock.html`）  
> PM：`stage.accepted`（ui，视觉迭代自决 2026-10-15）  
> 真相：mock HTML = 壳层/IA；Penpot = token/分区；契约正文仍来自现网 `static-docs/api.html`

## 任务

### Dev（Stream Dev · 主责）

- [ ] 将 `ui/export/api-docs-light-mock.html` 的壳层/IA 合入 `static-docs/api.html`（**保留全部现有章节正文**，不捏造接口）
- [ ] 亮色 token 对齐 DESIGN / handoff（底 `#fafafa`、墨字、靛蓝强调）
- [ ] 粘性侧栏 TOC：按 handoff 分组表锚定真实 h2 id；删除正文顶部旧 `.toc`
- [ ] 新增 `#quickstart` 训练闭环入口卡；给接口分类总览加 `id="overview"`
- [ ] TOC 轻量过滤（非全文引擎）；亮色 `code/pre`（LightCode）
- [ ] 路径仍 `/api.html`；顶栏外链保持；**不做 SPA**；不改 `architecture.html` / OpenAPI / backend
- [ ] 交 `report-dev.md`（含自测对照 export 01–06）

### QA（Stream QA）

- [ ] `/api.html` 亮色壳；侧栏 TOC 可跳到 auth / openenv / models
- [ ] 检索过滤 TOC 可用；窄屏 TOC 不挡读（可抽检）
- [ ] 契约抽检：未改接口表关键行含义；无 `/arena` 叙事回潮
- [ ] 交 `report-qa.md`（通过后才 ship）

### Ops（KR 运维）

- [ ] 等 report-dev + report-qa + `ship.md` + `STATUS.user_ack`（human-ship）再发 `games.cree1p.com`

## 接口（硬契约）

- openapi_diff: **无 API 变更**
- 兼容性: **兼容**（仅静态文档页 HTML/CSS/轻 JS）

## 验证

- 开发自测: Dev report-dev（对照 mock + PNG）
- QA: smoke 上列项；失败附复现
- smoke（发版后）: `/api.html` 200；TOC→#models/#openenv/#auth；亮色可见

## 交接

- Dev 依据：`ui-handoff.md` + `export/api-docs-light-mock.html` + PNG
- 禁止：SPA 路由、改 OpenAPI 正文真相、恢复暗色默认壳
