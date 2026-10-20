# CHANGE-20261014-docs-cleanup · 文档可清理清单（扫描稿）

> **本阶段零删除、零搬迁。** 仅供 Stream PM / 用户确认。  
> 扫描根：`/workspace/gameplatform` · 日期：2026-10-14（Asia/Shanghai）  
> 产品真相：`docs/pm/01–04` · 技术历史：`docs/design/` · 协作：`docs/pm/05` + `changes/` · 现行契约：`docs/api/`（openenv / runtime / ugc）

---

## 0. 结论摘要（给用户勾选）

| 动作 | 条数（约） | 建议 |
|---|---|---|
| **硬删除** | 0 必删 | 无空文件、无现行契约的纯副本；本轮不建议直接 `rm` |
| **归档 / 标 deprecated** | ~10–12 | 过时线框、已交付交接单、旧协议验收证据 |
| **就地修订** | ~8 处 | README「对战中心」、Decision Log 旧 D27、蓝图模块表与第一天旅程、分册状态头 |
| **必须保留** | pm + 现行 api + 关键 design | 见 §5 |

请用户按 §2 / §3 / §4 勾选后，再开执行回合（仍经 human-scope）。

---

## 1. 完整文件树（名 · 约行数 · 修改意图）

### 1.1 根目录 `*.md`

| 路径 | 行数 | 意图 / 现状 |
|---|---|---|
| `README.md` | ~165 | 仓库总览与本地开发入口；**过时**：`web/src/pages/` 仍写「对战中心」 |

### 1.2 `web/DESIGN.md`（实现层规范，不在 docs/ 下但被 pm 引用）

| 路径 | 行数 | 意图 / 现状 |
|---|---|---|
| `web/DESIGN.md` | ~57 | 亮色极简 / shadcn 硬规则；**保留**（PM 只引用不改） |

### 1.3 `docs/` 顶层

| 路径 | 行数 | 意图 / 现状 |
|---|---|---|
| `docs/architecture.html` | ~537 | 现行架构总览（OpenEnv-only 已写明）；Decision Log 行仍混有「磁贴条」旧 D27 措辞 |

### 1.4 `docs/api/`（现行契约 + 历史验收）

| 路径 | 行数 | 意图 / 现状 |
|---|---|---|
| `openenv.md` | ~93 | **现行** OpenEnv 环境契约 |
| `runtime-contracts.md` | ~286 | **现行** 业务 / 回放等运行时契约 |
| `ugc-isolation.md` | ~45 | **现行** UGC 隔离说明 |
| `openenv-validation.md` | ~52 | OpenEnv-only 迁移本地验收（2026-09-15）；紧贴契约，**建议保留在 api/** |
| `kr-deployment-validation.md` | ~187 | **历史** KR 部署/浏览器验收（旧环境协议时期，文首已声明） |
| `reliability-validation.md` | ~111 | **历史** 可靠性验收（旧环境协议时期） |
| `reliability-benchmark.json` | ~56 | 可靠性基准数据（配合上条） |
| `evidence/openenv-only-20260915.json` | — | OpenEnv-only 迁移证据 |
| `evidence/kr-20260908/candidate-browser.json` | ~60 | KR 候选浏览器证据 |
| `evidence/kr-20260908/production-browser.json` | ~8 | 生产浏览器证据 |
| `evidence/kr-20260908/*.png`（3） | — | 截图证据（lobby / tetris / replay） |

### 1.5 `docs/design/`（技术历史与决策）

| 路径 | 行数 | 意图 / 现状 |
|---|---|---|
| `00-README.md` | ~84 | 设计索引 + Decision Log；**矛盾**：正文索引写 D27=撤销 /arena，Log 表旧 D27=磁贴条控制台 |
| `00-平台蓝图与路线图.md` | ~178 | 产品总纲草稿；**过时**：状态仍「草案」、模块状态表多处 ⬜/🚧、第一天旅程玩法优先、架构图含「对战中心」与旧 `/api/{game}/env` |
| `01-总体架构与API分类.md` | ~158 | 分层与 API 全景（历史；环境面已被 OpenEnv 取代） |
| `02-账号体系.md` | ~88 | 账号 / JWT / 游客 |
| `03-游玩API与PvP-PvE流程.md` | ~184 | 会话制游玩与 PvP/PvE |
| `04-模型托管与对抗.md` | ~132 | ONNX 托管与模型对战 |
| `05-旧代码清理与迁移.md` | ~68 | **已完成**的清理清单 / 迁移计划 |
| `06-匹配机制与房间系统.md` | ~251 | 匹配 / 房间设计；文首仍「草案」但能力已上线 |
| `07-v1.0实施计划与交接.md` | ~250 | **已交付** HANDOFF；文内仍出现 `/arena` 路由示例 |
| `08-成长与赛事数值.md` | ~55 | XP / 等级简表（随 v1.0-c） |
| `09-游戏接入指南.md` | ~138 | **现行 GDK**（游戏包接入） |
| `10-用户上传游戏设计.md` | ~292 | UGC 设计；文首「草案」，能力已交付 |
| `11-用户上传游戏实施计划.md` | ~129 | **已交付**；文首仍写「待排期」（与 00-README「已交付」冲突） |
| `12-游戏完全解耦重构设计.md` | ~251 | D26 设计；文首「待确认」，实已上线 |
| `13-游戏完全解耦实施计划.md` | ~163 | **已交付**；文首仍「待排期」 |
| `14-对战交互重构设计.md` | ~118 | **D27 权威正文**：撤销 /arena、对战按 slug；**必须保留** |
| `15-接入OpenEnv预研.md` | ~188 | OpenEnv 预研 + 落地史（v1→v2） |
| `16-前端渲染能力开放设计.md` | ~344 | 渲染 v2（D28–D30）；**现行技术参考** |
| `arena-wireframe.html` | ~338 | 标题已标「历史原型」；内容对应**旧**磁贴条 /arena 方案，已被设计 14 取代 |

> 目录 `docs/design/archive/` **尚不存在**。

### 1.6 `docs/pm/`（产品真相 + 协作）

| 路径 | 行数 | 意图 / 现状 |
|---|---|---|
| `00-README.md` | ~57 | pm 索引与已确认决策 |
| `01-定位与用户.md` | ~76 | **现行**定位 / 用户 / 旅程 |
| `02-功能与模块清单.md` | ~397 | **现行** 31 feature 清单（替代蓝图模块表作产品真相） |
| `03-信息架构草案.md` | ~112 | **现行** IA + D27 硬约束 |
| `04-组件与页面地图.md` | ~149 | **现行** 页面/组件地图 |
| `05-协作契约.md` | ~187 | **现行** 制品流水线 |
| `changes/CHANGE-20261014-rl-lab-ux/STATUS.yaml` | ~18 | RL Lab UX 变更信封 |
| `changes/CHANGE-20261014-rl-lab-ux/specify.md` | ~15 | 该变更 specify |
| `changes/CHANGE-20261014-docs-cleanup/`（本目录） | — | 本文档清理变更 |

---

## 2. 建议 **删除**（重复 / 空 / 明确作废）

| 项 | 依据 |
|---|---|
| **本轮无必删文件** | 扫描未见空文件；未见「与 pm/api 完全重复且无历史价值」的副本；证据与交接单仍有审计价值 |

**可选激进删除（仅当用户明确不要保留证据时）**：

| 路径 | 为何可删 | 风险 |
|---|---|---|
| `docs/api/evidence/kr-20260908/*` | 旧环境协议时期截图/JSON，文首已声明不作现行证明 | 丢失部署审计痕迹 |
| `docs/api/reliability-benchmark.json` | 配合旧 reliability 验收 | 同上 |

> **推荐**：不删，改走 §3 归档。硬删需用户逐条勾选。

---

## 3. 建议 **归档**（移入 `docs/design/archive/` 或标 deprecated）

> 有历史价值，**勿当现行产品/接口手册**。归档后在 `docs/design/00-README.md` 索引中改链并加「已归档」列。

| 路径 | 建议动作 | 一句依据 |
|---|---|---|
| `docs/design/arena-wireframe.html` | → `docs/design/archive/` | 旧 D27 磁贴条线框；现网无 /arena，权威在设计 14 |
| `docs/design/05-旧代码清理与迁移.md` | 标 deprecated 或 archive | 迁移已完成，仅作历史清单 |
| `docs/design/07-v1.0实施计划与交接.md` | 标 deprecated 或 archive | 五批次已交付；内含过时 `/arena` 操作说明 |
| `docs/design/11-用户上传游戏实施计划.md` | 标 deprecated（设计 10 可留作 UGC 设计史） | 实施已完成；文首「待排期」误导 |
| `docs/design/13-游戏完全解耦实施计划.md` | 标 deprecated（设计 12 可留作 D26 设计史） | 同上 |
| `docs/api/kr-deployment-validation.md` | → `docs/api/archive/` 或 `docs/design/archive/api-evidence/` | 文首已自称历史验收（旧协议） |
| `docs/api/reliability-validation.md` | 同上 | 同上 |
| `docs/api/reliability-benchmark.json` | 随上条一并归档 | 配套数据 |
| `docs/api/evidence/kr-20260908/` | 随旧验收一并归档 | 旧协议证据包 |
| （可选）`docs/api/evidence/openenv-only-20260915.json` | 可留 api/ 或进 archive | 较新；若留，与 `openenv-validation.md` 同层更清晰 |

**不建议整目录搬走**：`01–04`、`06`、`08–10`、`12`、`14–16`、`00-README` 仍被 GDK / D27 / 渲染 / 决策号交叉引用；用「文首 deprecated + 索引状态列」即可，避免断链风暴。

---

## 4. 建议 **就地修订**（最小改动说明）

| 文件 | 最小改动 | 一句依据 |
|---|---|---|
| **`README.md`** | `src/pages/` 一行：删「对战中心」，改为「大厅 / UgPlay+UgPvp / Records / 资料 / 好友 / …」 | 现网无 Arena；pm/02 已记此过时点 |
| **`docs/design/00-README.md` Decision Log · D27 行** | 改写为与设计 14 一致：「撤销独立对战中心 `/arena`；对战按 `/games/{slug}/pvp`；模型挑战在 `/models`」；可脚注「早期磁贴条草案已废弃」 | Log 旧文与索引行、设计 14、现网路由冲突（已知线索） |
| **`docs/design/00-README.md` 文档索引「状态」列** | 对齐正文交付事实：`01–06/10/12` 勿再笼统「草案」；`11/13` 标「已交付」 | 索引与文件头、顶部总状态三方不一致 |
| **`docs/design/00-平台蓝图与路线图.md`** | ① 文首加：「产品定位/用户/第一天旅程以 `docs/pm/01` 为准」；② §2 第一天旅程旁注「历史验收路径，非现行大厅主 CTA」；③ §3 模块状态表加过期横幅或链到 `pm/02`；④ §5 图去掉「对战中心」、旧 env 路径改指 OpenEnv | 蓝图玩法优先 vs pm/01；模块表过期；图含已移除 IA |
| **`docs/design/11-…` / `13-…` 文首状态** | 「待排期」→「已交付（日期见 00-README）」 | 避免实施 bot 误读为未开工 |
| **`docs/design/06` / `10` / `12` 文首状态** | 「草案/待确认」→「已交付（历史设计）」 | 同上 |
| **`docs/architecture.html` Decision 表 D27** | 「游戏磁贴条 + …」→「/arena 移除；对战按游戏 slug」（可保留「历史曾讨论磁贴条」一句） | 与设计 14 对齐；该页其余 OpenEnv 叙述已较新 |
| **`docs/pm/00-README.md` 变更表** | 增一行本 CHANGE `docs-cleanup` | 索引完整 |

**明确不在本 CHANGE 改**：`web/DESIGN.md` 正文、业务代码、OpenAPI、生产配置。

---

## 5. **必须保留**（现行契约 / pm / 关键技术）

| 路径 | 一句依据 |
|---|---|
| `docs/pm/00–05` 与 `docs/pm/changes/**` | 产品真相 + 协作契约 + 变更信封 |
| `docs/api/openenv.md` | 唯一现行环境契约 |
| `docs/api/runtime-contracts.md` | 现行业务/回放契约 |
| `docs/api/ugc-isolation.md` | 现行隔离说明 |
| `docs/api/openenv-validation.md` | 最近一次破坏式迁移验收锚点 |
| `docs/design/14-对战交互重构设计.md` | D27 权威（无 /arena） |
| `docs/design/09-游戏接入指南.md` | 现行 GDK |
| `docs/design/16-前端渲染能力开放设计.md` | 现行渲染 v2 |
| `docs/design/15-接入OpenEnv预研.md` | OpenEnv 决策史（被 api 引用） |
| `docs/design/00-README.md` | Decision Log 索引（修订后仍为入口） |
| `docs/architecture.html` | 人读架构总览（小修 D27 后保留） |
| `web/DESIGN.md` | 前端视觉硬规则 |
| `README.md` | 仓库入口（修订过时词后保留） |

---

## 6. 已知过时线索 · 核对结果

| 线索 | 核对结果 | 落入 |
|---|---|---|
| 根 README 仍写「对战中心」/arena | **属实**（约 L49 `src/pages/`） | §4 修订 |
| Decision Log 旧 D27 与现网冲突 | **属实**：Log=磁贴条控制台；设计 14 / 索引行 / 代码=撤销 /arena | §4 修订；线框 → §3 归档 |
| 蓝图第一天旅程玩法优先 vs pm/01 | **属实**（蓝图 L39–41 vs pm/01 训练闭环） | §4 修订（加「以 pm 为准」横幅，不删蓝图） |
| 模块状态表过期 | **属实**：D/G/J/L 等多处 ⬜，与 v1.0 已交付及 pm/02 不符 | §4 修订或指向 pm/02 |
| 重复/被 pm 替代的产品向草稿 | **部分属实**：蓝图 §1–§3 产品叙述与 pm 重叠，但是技术路线图容器 → **修订+降级为历史总纲**，不删 | §3 不整份归档；§4 挂 pm 为准 |

附带发现（扫描新增）：

- `11`/`13` 文首「待排期」vs `00-README`「已交付」  
- `architecture.html` D27 行仍写磁贴条  
- `07` 交接手册仍教 `/arena`  
- api 下旧协议验收文已自觉标历史，适合归档而非删  

---

## 7. 建议执行顺序（用户确认后）

1. **human-scope**：用户勾选 §2（若有）/ §3 / §4  
2. 先做 §4 就地修订（低风险、立刻减少误导）  
3. 再建 `docs/design/archive/`（及可选 `docs/api/archive/`），`git mv` §3 项并改 `00-README` 索引  
4. 更新 `docs/pm/00-README` 变更表；本 CHANGE → `status: done` / 或进入下一阶段  
5. **永不**在未确认时 `rm` 证据或契约文件  

---

## 8. 给用户的勾选板（可直接回复）

```
[ ] A 只修订 §4（README + D27 Log + 蓝图横幅 + 分册状态头），本轮不搬文件
[ ] B 修订 + 归档 §3 列表（建 archive/）
[ ] C 在 B 基础上激进删除 kr-20260908 证据（不推荐）
[ ] D 暂缓，清单再改一版
```

