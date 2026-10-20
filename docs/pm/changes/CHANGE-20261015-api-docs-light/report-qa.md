# CHANGE-20261015-api-docs-light report-qa

- 环境: 本地（`static-docs/api.html` via `http://127.0.0.1:8765/api.html`）
- 范围: 冒烟 | 契约/路径抽检（对照 plan 验证节）
- 结果: **通过**
- 非目标: 不代替 Dev 开发自测；不改代码

## 用例

| id | 检查 | 结果 |
|---|---|---|
| QA-1 | 亮色壳（`--bg: #fafafa`，非暗色 `#0d1117`） | 通过 |
| QA-2 | 侧栏 TOC → `#auth` / `#openenv` / `#models` 可跳转且节可见 | 通过 |
| QA-3 | `#toc-search` 过滤「模型」：模型组保留，其他组 `hidden`；清空后恢复 | 通过 |
| QA-4 | 窄屏（~800px / `max-width: 900px`）：侧栏堆叠在正文上，不遮挡阅读 | 通过（见备注） |
| QA-5 | `#quickstart` 训练闭环入口卡可见 | 通过 |
| QA-6 | 契约抽检：auth 含 `/v1/auth/register|login|guest|me`；models 含 `/v1/models` 与 `{id}`；全文无 `/arena` | 通过 |

## 备注（非阻断）

1. TOC scroll-spy（`rootMargin: -20% 0px -65%`）在 `#models` 标题置顶时，高亮可能落在下一节「对战与积分」——锚点跳转本身正确。
2. 窄视口 ~800px 时正文内容盒约 860px，会出现横向滚动条裁切右缘；侧栏已堆叠、不挡读。

## 对照

- 上游：`report-dev.md`（自测通过）· `plan.md` QA 任务
- 发版后建议再抽检生产：`/api.html` 200 + TOC→#models/#openenv/#auth + 亮色可见
