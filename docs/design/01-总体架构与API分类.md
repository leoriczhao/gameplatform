# 01 · 总体架构与 API 分类

> **历史设计，不作为当前环境 API 手册。** 本文保留当时的决策、接口示例与验收记录；
> 环境交互相关内容已被 [OpenEnv 契约](../api/openenv.md) 取代。旧环境 API 已删除，
> 不保留兼容；当前架构见 [架构总览](../architecture.html)，平台业务与回放见
> [运行时契约](../api/runtime-contracts.md)。下文不代表本次切换已部署或通过测试。

## 1. 平台定位

**多用户游戏对战平台**，围绕三个核心能力：

1. **玩游戏**：每个游戏暴露**全量游玩 API**（会话制，人可玩、程序可玩）+ 网页界面
2. **训模型**：每个游戏暴露**远程环境 API**（无状态批处理，训练算法在调用方运行）
3. **打对抗**：用户**上传训练好的模型**参加 PvE/PvP 对战；也可以不走网页，直接用全量 API 写 bot 玩

目标用户：

| 角色 | 使用方式 |
|---|---|
| 玩家 | 网页玩（PvE 打 AI / PvP 匹配人） |
| bot 开发者 | 用全量 API 或 SDK 写 bot 直接连平台对战 |
| RL 训练者 | 用环境 API 采样并在本地运行训练算法 → 上传模型 → 自动参战 |
| 平台管理员 | 管理游戏、用户、模型、对战 |

## 2. 系统分层

```
┌──────────────────────── 前端（React + shadcn/ui + Tailwind，亮色） ────────────────────────┐
│  大厅 · 账号页 · 游戏页(PvE/PvP) · 模型管理页 · 战绩页 · 文档/管理页                │
└──────────────┬─────────────────────────────────────────────────────────────────────┘
               │ HTTP/JSON
┌──────────────▼─────────────────────────────────────────────────────────────────────┐
│  API 层（FastAPI，/api/v1/*）                                                       │
│  ├─ 账号服务      auth：注册/登录/JWT/资料/配额                                     │
│  ├─ 会话服务      play：PvE/PvP 会话（有状态，超时/掉线管理）                       │
│  ├─ 环境服务      env：无状态批处理（训练面，限流）                                  │
│  ├─ 模型服务      models：上传/校验/元数据/配额                                     │
│  ├─ 对战服务      matches：匹配/异步执行/结果/回放/积分                              │
│  ├─ 排行榜/积分   scores + ratings                                                  │
│  └─ 平台/管理     games、health、admin                                             │
├─────────────────────────────────────────────────────────────────────────────────────┤
│  游戏层（games/*，纯函数 EnvAdapter —— 规则内核唯一实现）                            │
│  snake · tetris · microrts · (未来新游戏)                                            │
│  会话服务与环境服务都调用同一 EnvAdapter.step_state —— 引擎只有一份                 │
├─────────────────────────────────────────────────────────────────────────────────────┤
│  存储：SQLite（users / models / matches / ratings / scores / sessions 短期）        │
│  模型推理：onnxruntime（仅模型对战 worker 使用，无 torch）                           │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

**一个引擎原则（最重要）**：`games/*/EnvAdapter` 是游戏规则的唯一实现。
- 网页/会话游玩 = 服务端持有 state，每 tick 调 `step_state` 推进
- 环境 API = 不持有 state，调用方自己持有 state 批量推进
- 模型对战 worker = 加载用户 ONNX 模型，按模型 I/O 契约推进同一 `step_state`
三者的游戏动力学**逐位一致**，不存在"训练一套、线上另一套"。

## 3. API 全景（分类总表）

所有接口前缀 `/api/v1`，除标注外均需 `Authorization: Bearer <JWT>`。

### A. 账号（auth）—— 新增

| 接口 | 鉴权 | 说明 |
|---|---|---|
| `POST /auth/register` | 无 | 注册：username + password |
| `POST /auth/login` | 无 | 登录 → JWT |
| `GET /auth/me` | 用户 | 我的资料/配额 |
| `PATCH /auth/me` | 用户 | 改昵称/头像 |
| `POST /auth/guest` | 无 | 创建游客令牌（限 PvE） |

### B. 平台级

| 接口 | 鉴权 | 说明 |
|---|---|---|
| `GET /games` | 无 | 游戏目录（含每游戏元数据、API 地址） |
| `GET /health` | 无 | 健康检查 |
| `GET /docs` `/api.html` | 无 | 文档 |

### C. 全量游玩 API（play，会话制）—— 新形态

| 接口 | 鉴权 | 说明 |
|---|---|---|
| `POST /{game}/play/sessions` | 用户/游客 | 创建会话（PvE 或 PvP） |
| `GET /{game}/play/sessions/{id}` | 参与者/允许的观战者 | 当前 state + 状态（轮询） |
| `POST /{game}/play/sessions/{id}/actions` | 参与者 | 提交本方动作，推进 tick |
| `POST /{game}/play/sessions/{id}/leave` | 参与者 | 认输/退出 |
| `GET /{game}/play/sessions/{id}/replay` | 公开/参与者 | 对局回放（动作序列） |

### D. 环境 API（env，远程状态转移，无状态批处理）—— 保持

| 接口 | 鉴权 | 说明 |
|---|---|---|
| `GET /{game}/env/info` | 无 | 环境描述 + state/action/observation JSON Schema |
| `POST /{game}/env/new_batch` | 无* | `{seeds[], options}` → `{results[]}` 批量初始 state（可复现，1–256） |
| `POST /{game}/env/step` | 无* | 批量推进：`{states[], actions[]}` → `{results[]}` |

\* 环境 API 无账号也可用，但按 IP 限流（60 req/s）；登录后按用户配额放宽（见 02-账号体系）。

### E. 内置 AI 与排行榜

| 接口 | 鉴权 | 说明 |
|---|---|---|
| `POST /{game}/ai/action` | 无* | 内置 AI 演示（网页用） |
| `GET /{game}/scores` | 无 | PvE 排行榜 |
| `POST /{game}/scores` | 用户 | 提交 PvE 成绩（游客仅可昵称提交？→ 见 D5，统一要求登录） |
| `GET /{game}/ratings` | 无 | PvP 积分榜（ELO） |

### F. 模型托管（models）—— 新增

| 接口 | 鉴权 | 说明 |
|---|---|---|
| `POST /models` | 用户 | 上传模型（游戏 + 模型类型 + ONNX 文件 + 元数据） |
| `GET /models` | 用户 | 我的模型列表 |
| `GET /models/{id}` | 所有者/公开 | 模型详情 + 战绩 |
| `POST /models/{id}/eval` | 所有者 | 跑一次标准评估（vs 内置 AI，返回指标） |
| `DELETE /models/{id}` | 所有者 | 删除 |

### G. 对战与匹配（matches / matchmaking / rooms）—— 新增

| 接口 | 鉴权 | 说明 |
|---|---|---|
| `POST /matches` | 用户 | 创建对战：模型 vs 模型 / 模型 vs 内置 AI（约战，不计分） |
| `GET /matches` | 用户 | 我的对局列表 |
| `GET /matches/{id}` | 参与者 | 对局详情/结果 |
| `GET /matches/{id}/replay` | 参与者/公开 | 回放（已结束对局只读） |
| `POST /matches/queue` / `DELETE /matches/queue/{model_id}` | 用户 | 模型入/出**排位池**（自动匹配打积分，v2） |
| `GET /{game}/ratings` | 无 | 人 PvP 积分榜（ELO）；另有 `/{game}/ratings/models` 模型分榜（v2） |

> 完整的**房间 + 快速匹配**端点（rooms / matchmaking 队列 / rematch / 观战 /
> 断线重连 active 列表）见 [06-匹配机制与房间系统](./06-匹配机制与房间系统.md) §8。
> 人 vs 人从"邀请码私房"升级为"房间 + 匹配队列"双轨（D6 修订）。

### H. 管理（admin）—— 新增（v2）

`POST /admin/…`：游戏上下线、用户封禁、模型审核、对局仲裁。

## 4. 关键横切机制

- **限流与配额**：见 02-账号体系。
- **事件推送**：游玩/对战用 SSE（`text/event-stream`），网页免轮询；SDK 提供事件封装。
- **鉴权**：JWT（HS256，secret 由环境变量注入）；`X-Accel` 不需要（无大文件）。
- **错误格式**：统一 `{"detail": "人类可读信息", "code": "MACHINE_CODE"}`。

## 5. 与现状的映射（迁移后）

| 现状 | 迁移后 |
|---|---|
| `/api/{game}/env/*` | `/api/v1/{game}/env/*`（内容不变，加用户配额） |
| `/api/{game}/ai/action`、`/scores` | 并入 v1，语义不变 |
| 网页客户端自己持有 state（人工/AI/自定义模型） | 网页改走**会话 API**；内置 AI 在会话服务端执行 |
| 🔌 自定义模型 URL 模式 | 保留为模型托管的一种"外部模型"类型（模型在你机器上跑） |
| 无账号 | 游客（PvE 有限）+ 注册用户（全功能） |

## 6. 技术选型补充

- **onnxruntime**：仅模型推理 worker 需要（`pip install onnxruntime`，~50MB，无 torch）
- **会话存储**：进程内 dict + 短期持久化（重启丢未结束会话可接受；对局结果必须先落库）
- **异步对战 worker**：FastAPI 后台任务 / 独立 asyncio worker（v1 用后台任务池，并发上限控制）
