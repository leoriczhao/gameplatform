# Stream PM 产品文档（docs/pm）

> 面向：Stream PM / Game UI / Stream Frontend / Stream Backend / KR 运维  
> 代码根：共享盘 `/workspace/gameplatform`（线上 `games.cree1p.com`）  
> 本目录是**产品与信息架构归档**，不替代 `docs/design/` 的历史技术设计，也不替代 `web/DESIGN.md` 视觉规范。

## 与 docs/design 的关系

| 目录 | 职责 |
|---|---|
| **`docs/pm/`（本目录）** | 产品定位、用户、旅程、功能/模块清单、IA 目标、页面组件地图；供全新 UX/UI 与跨 bot 对齐 |
| **`docs/design/`** | 历史设计与决策日志（D1–D30）、批次实施与验收记录；技术契约细节仍以分册 + `docs/api/` 为准 |
| **`docs/api/`** | 当前 OpenEnv / runtime / UGC 隔离等**现行**契约 |
| **`web/DESIGN.md`** | 前端亮色极简视觉规范（实现层）；PM 文档只引用、不改其正文 |
| **根 `README.md`** | 仓库总览与本地开发入口 |

读法建议：先读本目录 `01` → `02` → `03`；做视觉时对照 `03`+`04`；改 API/引擎时回 `docs/design` + `docs/api`。

## 已确认产品决策（2026-10，用户拍板）

1. **定位**：RL 实验室大厅——主卖 OpenEnv/SDK → 导出 ONNX → 托管 → 模型对抗；网页玩是验证层  
2. **主用户**：P3 模型作者；P1/P2/P4/P5 为辅  
3. **主旅程**：训练闭环；玩 / PvP 为验证支线  
4. **IA**：顶栏优先「模型托管」「API 文档」；大厅 Hero 推训练闭环；游戏卡强调环境/契约；对战为次要入口；**不恢复 `/arena`**（硬约束 D27）

## 文档索引

| 文档 | 内容 |
|---|---|
| [01-定位与用户.md](./01-定位与用户.md) | 定位、用户主次、主/支旅程、成功指标草案 |
| [02-功能与模块清单.md](./02-功能与模块清单.md) | **核心**：按产品域的 feature 清单（路径/API/状态/主次） |
| [03-信息架构草案.md](./03-信息架构草案.md) | 现网 IA vs 目标 IA、硬约束 |
| [04-组件与页面地图.md](./04-组件与页面地图.md) | 前端页面/组件职责 + 后端路由模块对照 |
| [05-协作契约.md](./05-协作契约.md) | **PM 主导**的跨 bot 制品交接：信封、流水线、Done、人闸 |

## 协作边界（提醒）

- **Game UI**：Penpot 全新 UX/UI；以本目录规格为准，对照 `web/DESIGN.md` 做落地反馈  
- **Stream Frontend**：改 `web/` 实现；重大 IA/路由变更先经用户确认  
- **Stream Backend**：`backend/` FastAPI 单体；重大 Schema/API 变更先征得同意  
- **KR 运维**：部署 `games.cree1p.com`；PM/设计不擅自发版  

本目录文档**不授权**改业务代码或部署；仅归档产品共识。

## 维护约定

- 用户拍板的定位/IA/旅程变更：先更新 `01`/`03`，再通知 Game UI  
- 代码新增 feature：同步补 `02` 与 `04`  
- `docs/design` 决策号（Dxx）变更：在 `03` 硬约束节交叉引用，不在本目录重写整份技术设计  

## 变更单（changes）

按 [05-协作契约.md](./05-协作契约.md)：每张变更在 `docs/pm/changes/<id>/`，含 `STATUS.yaml` + 阶段制品。

| id | 主题 | status |
|---|---|---|
| [CHANGE-20261014-rl-lab-ux](./changes/CHANGE-20261014-rl-lab-ux/) | RL 实验室定位下的全新 UX/UI | draft / specify |
| [CHANGE-20261014-docs-cleanup](./changes/CHANGE-20261014-docs-cleanup/) | 文档清理（§4 就地修订） | done |
