# CHANGE-20261015-api-docs-light specify

- 要解决的问题：`/api.html`（`static-docs/api.html`）暗色长文难翻、难找、不好用；与亮色 lab 不一致。用户要**好用**（IA/导航/分区），不只换皮。
- 壳子（已定）：**继续静态** `/api.html`（非 SPA）；顶栏外链保持。`architecture.html` 不纳入。
- 非目标：不发明新 API；不改 OpenAPI 契约正文真相；不做站内 SPA 同壳（另开 CHANGE）；不部署（本阶段）。
- 用户与主旅程触点：P3 → 顶栏/大厅「API 文档」。
- IA / 路由影响：路径仍 `/api.html`；页内 IA 重做（粘性侧栏 TOC、分区、检索/过滤式好找、亮色、训练闭环叙事入口）。
- 成功指标：
  - 亮色壳对齐 DESIGN.md
  - 侧栏 TOC 可定位主要章节；找「模型/OpenEnv/鉴权」明显短于现长滚
  - code/pre 在亮色下可读；无契约内容捏造
- 风险：页内检索可为 UI 提示/轻量过滤，不要求全文搜索引擎。
