# 15 · 接入 OpenEnv 预研

> **历史设计，不作为当前环境 API 手册。** 本文保留当时的决策、接口示例与验收记录；
> 环境交互相关内容已被 [OpenEnv 契约](../api/openenv.md) 取代。旧环境 API 已删除，
> 不保留兼容；当前架构见 [架构总览](../architecture.html)，平台业务与回放见
> [运行时契约](../api/runtime-contracts.md)。下文不代表本次切换已部署或通过测试。

> **预研状态**：2026-09 完成资料调研与复杂度评估，结论与建议待用户拍板。
> **一句话结论**：OpenEnv 是 HuggingFace 面向 **agentic RL（LLM 执行环境）** 的实验期协议，其「有状态 WebSocket 会话 + 单环境单步」模型与我们「无状态批处理 HTTP」的架构根本相反；**不建议全线接入**。值得做的是低成本「入向桥」（OpenEnv 环境 → 我们的 gymnasium SDK）与协议对齐，其余保持自研协议为骨（延续 D2）。

## 1. OpenEnv 是什么（事实清单）

| 项 | 事实 |
|---|---|
| 项目 | huggingface/OpenEnv（BSD-3-Clause） |
| 定位 | 「Agentic execution environments」——为 **LLM agent 强化学习（agentic RL）** 提供 HTTP/容器化的隔离执行环境；README 自称要建立 agentic 环境标准 |
| 现状 | **实验期**（README 明示 Early Development），PyPI 最新 **0.4.1**（0.2.2 → 0.4.1，API 快速变动中） |
| 依赖 | fastapi、pydantic>=2、uvicorn、websockets>=15（刻意轻依赖，numpy/torch 等放 optional） |
| 部署 | Docker 容器 / HuggingFace Space / UV 运行时；K8s coming soon |
| 生态 | 面向 agentic 场景：代码执行、MCP 工具化环境（/mcp JSON-RPC）、Inspect 评估集成（core/evals）、Transform/Rubric/TaskProvider 等训练辅助接口 |

## 2. OpenEnv 协议模型（截至 main，2026-09 源码抓查）

| 层 | OpenEnv | 我们（gameplatform） | 差异等级 |
|---|---|---|---|
| 状态归属 | **服务端持有**：每个 WebSocket 会话 = 一个 Environment 实例（_sessions 字典、容量上限、空闲回收 reaper） | **调用方持有**：无状态，state JSON 来回传 | 🔴 根本冲突 |
| 步进 | **单环境单步**：step({action, timeout_s?}) → {observation, reward, done, metadata}（HTTP /step 每次临时建 env 用完即关；生产走 WS 消息） | **批量**：/env/step 一次推进 ≤256 个 state | 🔴 核心差异 |
| reset | reset({seed?, episode_id?}) → {observation, ...}，**支持 seed 复现** | /env/new {seed, ...}，同 seed 同轨迹 | 🟢 语义一致 |
| 端点 | GET /health /schema /metadata /tasks*；POST /reset /step /mcp（simulation mode）；WS /ws；生产模式下不注册 /reset /step | GET /env/info；POST /env/new /env/step；另有 /ai/action /scores | ⚪ 风格类似 |
| Schema | Action/Observation/State 均为 **Pydantic 子类**，/schema 返回三者 JSON Schema | /env/info 的 schemas.{state,action,observations}（_environment_schemas()） | 🟢 理念一致 |
| 动作 | 任意 JSON dict（Pydantic 校验，extra=forbid）→ 支持复合动作 | int / list / dict 透传 + 服务端 validate_action → microrts 复合动作同构 | 🟢 |
| 批处理/向量 | **未发现**（无 VectorEnv、无 batch 端点） | RemoteVecEnv + MAX_BATCH=256 | 🟡 对面缺失 |
| terminated/truncated | 无 truncated 概念，只有 done | gymnasium 5 元组（terminated/truncated）由 wrapper 补 | 🟢 可桥接 |
| 任务集 | ORS 兼容 split/task 端点（ListTasks/NumTasks/GetTask/GetTaskRange） | 无（以 seed 为 episode 生成器） | 🟡 语义平移 |

## 3. 三种接入语义与复杂度评估

### 3.1 出向：平台作为 OpenEnv Server（A 向，最重）
把每个游戏引擎暴露成 OpenEnv 协议（WS 会话 + /reset /step /schema + 任务端点），让 HuggingFace agentic 训练栈直接采 sample。

| 工作项 | 量级 | 说明 |
|---|---|---|
| WS 会话桥层 | 3–5 人日 | 每会话 env 实例 ↔ 转发到现有 step_state；会话管理（容量/空闲回收/超时）是**新状态层**，与无状态架构并行存在 |
| 每游戏 Pydantic Action/Observation 类型 | 2–4 人日 | 官方 3 游戏可从 schemas.py 生成；**UGC 动态游戏无法静态生成** → 需动态 schema 桥（auto/ 有类似机制但未验证） |
| 任务端点（seed→task 映射） | 1–2 人日 | 把 seed 语义映射成 split/task 概念 |
| MCP 端点（可选） | 1–2 人日 | 作用有限：我们的环境不是 LLM 工具场景 |
| 测试与回归 | 2–3 人日 | 双协议对拍（OpenEnv bridge vs 原生 /env/step） |
| **合计** | **约 9–16 人日（2–3 人周）** | 另需承担 OpenEnv 实验期 API 变更的持续跟进成本 |

### 3.2 入向：OpenEnv 环境接入我们 SDK（B 向，最轻）
在 sdk/gameplatform/ 增加一个包装类：OpenEnvClient → gym.Env（沿用 gym.py 的「双包装器」模式，注册 platform-openenv-*），让 SB3 也能训 OpenEnv 托管的环境。

| 工作项 | 量级 |
|---|---|
| OpenEnvRemoteEnv(gym.Env) 包装（obs/action 映射 + 每环境 spaces 定义） | 1–2 人日 |
| 注册与测试 | 0.5–1 人日 |
| **合计** | **约 1–3 人日**，不动服务端 |

注意：OpenEnv 观测/动作是任意 JSON（无固定 spaces），包成 Box/Discrete 需逐环境自定义映射；且 WS 单步往返延迟高，只适合低步频 agentic 任务，不适合我们的 DQN 高频采样。

### 3.3 协议对齐（C 向，免费）
/env/info 的 schemas 结构与 OpenEnv /schema 对齐字段命名、补 seed 语义说明。约 0.5 人日，零风险。

## 4. 关键冲突与风险

1. **架构模型相反（最大成本来源）**：OpenEnv 服务端有状态 + 单步，我们无状态 + 批量。A 向接入 = 引入一个完整的状态会话层，等于维护第二套架构；我们的限流（60/120 req/s）、水平扩展、引擎唯一（一引擎原则）全都不适用于它的 WS 会话模型。
2. **定位错位**：OpenEnv 是 agentic（LLM）环境协议（代码执行/文本/浏览器），**没有游戏类环境先例，没有批处理/向量支持**。我们的核心价值（经典 RL + 批量训练 + 人机对战闭环）不在它的设计目标内。
3. **实验期风险**：0.2→0.4 已见破坏性变更；无 stable API 承诺；依赖锁定时如果上游继续变，A 向的桥接层要持续返工。
4. **吞吐**：WS 单步不适合 DQN/PPO 高频采样；若把生产训练切到 OpenEnv 协议，单机训练吞吐会断崖下跌。
5. **UGC**：沙箱游戏动态加载与 OpenEnv 静态 Pydantic 类型期望冲突（D25 沙箱只有标准库+numpy，无法装 openenv）。

## 5. 决策建议

- **不做 A 向（平台当 OpenEnv server）**：投入产出比最差，与 D2（无状态批处理）、D1（游玩会话制）、D18（沙箱）均有冲突。
- **推荐低成本动作**：
  1. C 向协议对齐（0.5 人日，顺手做）；
  2. B 向入向桥 PoC（1–3 人日）——价值是演示「我们 SDK 能吃 OpenEnv 生态」，为未来 agentic 方向留接口；**不承诺维护**，标注 experimental。
- **保持自研协议为骨**（延续 D2）：我们的无状态批处理协议在经典 RL 场景没有替代品；若未来想扩大生态，性价比更高的动作是把该协议**文档化/开源**为「Gymnasium-compatible stateless batch environment HTTP protocol」，而不是迁到 OpenEnv。
- **Watch list**（每季度复查一次）：OpenEnv RFC/roadmap 是否出现 vector/batch 或多智能体支持；其「standard」地位是否被训练框架采纳；HuggingFace 是否新增游戏类环境示例。
---

## 7. 落地记录（2026-09，MVP 已交付）

> 拍板（用户）：**单独提供一套 OpenEnv 兼容接口**（并行附加面，不迁移现有 API）·
> **自实现 wire 对齐**（不依赖 openenv 包）· **HTTP + WebSocket 全做**。

- 新文件：`backend/openenv_routes.py`（wire 层）；`tests/test_openenv.py`（11 用例，与原生 `/env/*` 逐位对拍）。
- 挂载：`main.py` 的 `_mount_ugc_routes` 为每个游戏挂 `/api/openenv/{game}/*`；全局 `GET /api/openenv/list_environments`（= 已注册游戏）。
- 端点：
  - HTTP：`GET /schema /metadata /health /splits`；`POST /reset /step /tasks /num_tasks /task /task_range`。
  - WS `/ws`：每连接一个会话槽位（服务端持有 state），消息 `reset/step/state/close`，错误码 `INVALID_JSON/VALIDATION_ERROR/EXECUTION_ERROR/UNKNOWN_TYPE/CAPACITY_REACHED/SESSION_ERROR`。
- 语义决策：
  - 动作信封统一 `{"value": <raw action>}`（int / list / dict 均可，语义见 `/schema.action` 与 `/env/info`）。
  - HTTP `/step`（无状态仿真）要求 `{"value": {"state": <state>, "action": <raw>}}`；持久状态走 `/ws`（对应 OpenEnv client 生产路径）。
  - 观测归一 float32 tensor：`{"type":"tensor","data":<nested list>,"shape":[...],"dtype":"float32"}`；无服务端 obs 时回退 `{"type":"state","state":...}`。
  - `metadata` 附带 `score/cause/tick/step_count/seed/episode_id`。
  - task = seed 序列：split `default`，10000 个任务（`/tasks` 返回前 100 条防大响应）。
  - WS 每游戏并发上限 64。
- 一致性验证：HTTP 与 WS 均与原生 `/env/*` 同 seed 同轨迹（测试覆盖 snake/tetris/microrts 复合动作）。
- 明确不做：`/mcp`、production/simulation 双模式、HTTP `/state`（用 WS state 消息替代）。



### UGC 游戏怎么获得 OpenEnv 面（2026-09 实测确认）

**结论：UGC 作者零额外工作，审核发布即自动获得 /api/openenv/{slug}/… 兼容面。**

链路：UGC 上传 → 提交审核 → 管理员 approve → ugc._register_game() 把游戏注册进 registry
并调用路由挂载器（main._mount_ugc_routes，只挂一次）→ OpenEnv 兼容路由与原生 env
路由一起挂上。OpenEnv 桥层与原生 env 走的是同一个 ProxyAdapter（沙箱 worker 转发），
所以沙箱内（D25：标准库 + numpy）什么都不用装。

需要满足（就是 v2 游戏包本来就要求的鸭子契约，见 docs/design/09）：

| 契约方法 | OpenEnv 面怎么用 | 必须吗 |
|---|---|---|
| info() | /schema、/metadata、obs_modes 探测 | 是（v2 本来就有） |
| new_state(seed, options) | /reset + WS reset | 是 |
| step_state(state, action) | /step + WS step（同一引擎，逐位一致） | 是 |
| validate_state / validate_action | 400/422 与错误帧校验 | 强烈建议（v2 本来就有） |
| obs(state, mode) | 观测包装；未实现/无 obs_modes 时 observation 回退 {type: state, state: …} 透传 | 可选 |

行为约定（写死在这层，作者无需感知）：
- 动作信封 {"value": <raw action>}；raw 形状由你的 validate_action 定义（int/list/dict 都行，microrts 的复合命令列表无改动直接可用）。
- 观测归一 float32 张量：{type: tensor, data: <nested list>, shape: […], dtype: float32}。obs 返回 numpy 或嵌套 list 即可。
- /metadata：version 来自 game.yaml，author = 作者昵称（管理员所有者显示「官方」）。
- 生命周期：下架/暂停/熔断 → registry.unregister → 该 slug 的 OpenEnv 路由与原生 env 一起 404，无需额外处理。

新增测试 tests/test_openenv_ugc.py（5 用例）：上传→发布→目录可见、schema+metadata、
无 obs_modes 回退、HTTP 与原生 env API 对拍至终止、WS 会话完整可玩。

> **v2 已交付**：上述 v1 记录保留作历史；2026-09 起 OpenEnv 面已升级为
> 「完整接入官方 openenv 栈」，见下方 §7.2。

## 7.2 落地记录 v2（2026-09：接入完整的 openenv 环境）

> 决策：**不再自实现 wire 对齐，改为直接运行官方 huggingface/OpenEnv 栈**
> （PyPI `openenv==0.4.1`，hard dependency 进 `backend/requirements.txt`）。
> 动机：v1 的「按快照自对齐」已落后于官方协议——0.4.x 真实 WS 响应带
> `type` 判别器、step 消息的 data 直接就是动作 dict、错误帧为 WSErrorResponse、
> simulation 模式有 GET /state、Task API 为 /{env}/splits… 与 v1 形状均不同。
> 「完整接入」= wire 正确性由官方包保证，官方 EnvClient/GenericEnvClient 开箱即用。

- 新文件：`backend/openenv_native.py`（约 350 行）：
  - `PlatformEnvironment(Environment)` 实现官方 reset/step/state/get_metadata/TaskProvider
    接口，底层仍调同一个 EnvAdapter 纯函数引擎（一引擎原则 D3；状态归属改为会话实例）。
  - 每游戏 Action 子类由 info().schemas.action 动态生成（pydantic create_model +
    WithJsonSchema），/schema.action 展示真实动作形状；无 schema 回退泛型平台信封。
  - 观测归一 `{"type":"tensor",…}`，无服务端 obs_modes 回退 `{"type":"state",…}`。
  - 每游戏一个官方 FastAPI 子应用（`create_fastapi_app`），发布时挂载
    `/api/openenv/{game}/*`；全局 `GET /api/openenv/list_environments` 保留。
- 移除：`backend/openenv_routes.py`（v1 自实现 wire 层，形状已与官方协议不一致）。
- 端点（官方形状）：GET /schema /metadata /health /state /list_environments /{env}/splits；
  POST /reset /step /{env}/tasks /{env}/num_tasks /{env}/task /{env}/task_range /mcp；WS /ws /mcp。
- 语义决策：
  - 动作信封仍是 `{"value": <raw>}`（raw 可为 int/list/dict，microrts 复合命令直通）。
  - 官方 HTTP /step 是无状态仿真（每次新建 env 实例、无会话 state）——保持 v1 语义：
    `{"value": {"state": …, "action": …}}`；持久状态走 WS（官方生产路径）。
  - WS 每连接一个会话（服务端持有 state，max_concurrent_envs=64）；state 消息返回官方
    State（episode_id/step_count），完整游戏 state 留在会话内；观测 metadata 附
    score/tick/cause 等统计，与原生 /env/* 对拍一致。
  - task = seed 序列：split default，10000 个任务（ORS 形状）。
  - 下架/暂停/熔断 = registry.unregister → 该 slug 的 OpenEnv 面整体 404
    （子应用 http 中间件守卫）+ WS 工厂错误帧。
  - 限流：复用 /env/* 的 60/120 req/s（只作用于 /reset /step）。
- 依赖注意：openenv 硬依赖 gradio>=4.0.0；gradio>=6.16 要求 starlette>=1.0，与平台锁定的
  fastapi==0.116.1（starlette<0.48）冲突，故 requirements.txt 锁定 gradio 6.15.1 /
  gradio-client 2.5.0 / hf-gradio 0.4.1 / griffelib 2.3.0（已实测共存导入）。gradio 仅用于
  可选 /web UI（默认关闭）。另：gradio 导入期构造 httpx.Client(transport=None)，httpx 0.28.1
  会解析进程代理变量——宿主环境存在形如 [::1] 的 no_proxy 值时触发 InvalidURL；
  openenv_native 导入时临时摘除代理变量规避（生产容器无此问题）。
- 测试（19 用例）：tests/test_openenv.py（12：官方 wire 形状/确定性 reset/HTTP 无状态对拍/
  任务端点/WS 官方协议/WS 与原生对拍/错误帧/microrts 复合/下架 404）、
  tests/test_openenv_ugc.py（5：发布即获得官方面）、tests/test_openenv_client.py（2：
  真实 uvicorn + 官方 GenericEnvClient 端到端，与原生 /env/* 对拍）。
- MCP（2026-09 追加：用户要求官方能力全接入）：`PlatformEnvironment` 暴露 FastMCP
  `mcp_server`，工具 `describe / new_episode / observe / act`（官方保留名
  `reset/step/state/close` 不可用）；JSON-RPC `tools/list` + `tools/call`，会话走
  `openenv/session/{create,close}`——带 `session_id` 时状态跨调用保持，不带时每次
  新建实例。工具调用在线程池执行，不阻塞事件循环。
- 明确不做（保持）：gradio /web UI、Docker 镜像化环境（平台自身即环境服务器）。
  production/simulation 在 openenv 0.4.1 没有开关：子应用同时注册 `/reset /step`
  与 `/mcp`（直接 MCP 访问）。
## 6. 参考

- OpenEnv repo：https://github.com/huggingface/OpenEnv
- 协议源码（抓查时间 2026-09）：src/openenv/core/env_server/http_server.py（会话/端点）、types.py（ResetRequest/StepRequest/SchemaResponse）、interfaces.py（Environment 基类）、env_client.py（WS 客户端）
- PyPI：https://pypi.org/project/openenv/（最新 0.4.1）
- 本平台对照：backend/env_routes.py、sdk/gameplatform/remote.py、sdk/gameplatform/gym.py、决策 D1/D2/D18