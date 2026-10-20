# CHANGE-20261015-ugplay-openenv-state report-qa

- 环境拆分（必读）:
  - **现网** `games.cree1p.com`：仍为旧镜像（未发本 CHANGE）
  - **制品** `/workspace/gameplatform`：Dev 已合入 FE 兜底 + BE `PlatformState` 重挂 `/state`
- 范围: P0 冒烟（含 **SMK-G01**）+ 契约抽检；对照 `plan.md` / `smoke-cases.md`
- 结果: **制品侧通过 → 已 ship**；**现网 G01 发版后复测通过（qa.post-ship）**
- 非目标: 不代替 Dev 自测；不改代码；不部署

## P0 结果

| id | 环境 | 结果 | 证据 |
|---|---|---|---|
| SMK-G01 进 `/games/microrts` | 现网 | **FAIL（预期）** | 「无法加载游戏」`Cannot read properties of undefined (reading 'meta')`；`GET /api/openenv/microrts/state` → `{"episode_id":null,"step_count":0}` 无 `environment` |
| SMK-G01 修复有效性 | 制品 | **通过** | `UgPlay`/`UgPvp`：`snap?.environment` + `(inf && inf.meta) \|\| catalogMeta`；`replay.js` 空安全；`openenv_native` `response_model=PlatformState` 重挂 `/state`；`node --test tests/openenv.test.js tests/replay.test.js` **36 pass / 0 fail**；瘦 state 元数据回退模拟不抛 |
| SMK-A01 顶栏/大厅壳 | 现网 | 通过 | 大厅「RL 实验室大厅」+ 环境卡片 + 顶栏模型/API；后端在线 |
| SMK-A02 `/arena` | 现网 | 通过 | `404` `{"detail":"Not Found"}`，非对战中心 |
| SMK-C01 `/api.html` 亮色壳 | 现网 | 通过 | 200；`#fafafa`；TOC/快速开始可见（本 CHANGE 未改文档页） |
| SMK-C02 TOC→#auth/#openenv/#models | 现网 | 通过 | 静态核对 GROUPS + 锚点仍在（同 api-docs-light 基线） |
| SMK-C05 契约抽检 | 现网+文档 | 通过 | auth/models 路径仍在；api.html 无 `/arena`；`docs/api/openenv.md` 要求 `state.environment` |
| SMK-D02 `/models` 登录工作台 | — | **缺夹具** | 无登录测号；本 CHANGE 非模型页，不挡 ship |
| SMK-F01 发版后三件套 | 现网（发版前基线） | 部分 | `/` `/api.html` 200；**G01 红**（旧镜像） |
| SMK-F02 ready | 现网 | 通过 | `/api/ready` 200 |

## 结论

1. 根因与 Dev 报告一致：现网 `/state` 瘦响应 + FE 无兜底 → G01 红。
2. 制品已同时修 BE（`environment` 应在）与 FE 防御；单元/静态/逻辑抽检通过。
3. **建议 PM 开 `ship.md`**；发版后 QA 必修跑现网 **SMK-G01**（microrts + 再抽 snake/tetris）与 `GET .../state` 含 `environment`，全绿才算本 CHANGE 真正收口。

## 发版后必跑（回填）

- 镜像：`ugplay-openenv-state-20261015-1720`（KR ops.done 2026-10-15）
- 环境：现网 `games.cree1p.com`

| 检查 | 结果 |
|---|---|
| `GET /api/openenv/microrts/state` 含 `environment` | **通过**（keys含 episode_id/step_count/game_state/environment） |
| snake/tetris `/state` 含 `environment` | **通过** |
| `/games/microrts` 无 `reading 'meta'`；画布/预览可见 | **通过** |
| 抽检 `/games/snake` | **通过**（画布 20×20 预览） |
| 抽检 `/games/tetris` | **通过**（无 meta TypeError；未登录无棋盘属登录门，非本 bug） |

**qa.post-ship：通过** — 本 CHANGE 现网收口完成。
