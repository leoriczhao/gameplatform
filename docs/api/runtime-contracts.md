# 运行时 API 契约

本文档定义前端和 SDK 依赖的远程 Environment 与 v2 Match/Replay 接口。平台业务
接口可通过 `/openapi.json` 查看；环境 wire schema 由各 OpenEnv 子应用的
`/schema` 提供。本文解释字段语义、状态迁移和回放规则，环境细节以
[OpenEnv 契约](openenv.md) 为准。

## 1. 边界与术语

- Environment API 仅通过官方 OpenEnv 公开环境交互，WS 一连接一实例。
- 训练算法和模型计算可以在调用方运行，reset/step 的环境计算在后端执行，不是
  完全离线训练。SDK 的 Gymnasium 向量包装管理多条连接，不是单 HTTP 批量推进。
- 本地 `LocalVecEnv` 下载游戏包后在调用进程运行；UGC 游戏包需作者开放本地训练，
  使用者显式信任其代码。
- Match API 统一创建、操作、观战和记录对局，进行中状态由服务端维护。
- Replay 通过 Match 的帧接口读取实时或封存帧，无需调用 OpenEnv 重算。

## 2. Environment API（官方 OpenEnv 0.4.1）

环境交互的权威契约见 [OpenEnv 环境交互](openenv.md)。唯一环境基址是
`/api/openenv/{game}`；旧环境接口已破坏式删除，无别名、重定向或兼容服务器。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/games` | 目录中的 `openenv_url` 和 `schema_url` 用于发现环境 |
| WS | `/api/openenv/{game}/ws` | 一连接一实例，同一连接内执行 reset/step/state |
| GET | `/api/openenv/{game}/schema` | 当前发布版本的官方 wire schema，不是历史包渲染配置 |
| GET | `/api/openenv/{game}/state` | 临时实例状态；不读取某个 WS 会话 |
| POST | `/api/openenv/{game}/reset`、`/step` | 官方 HTTP 端点，每请求新建临时实例，不跨请求保留局面 |

官方 HTTP reset 不会为下一次 HTTP step 留下状态，也不接受旧的 state/action
注入信封。连续交互请使用 WS，或用官方 `GenericEnvClient` 管理该连接。

reset 时可选 `version`，只执行仍可用的已审核包；省略使用当前发布版本。
reset 固定本局版本，发布/回滚不改变正在进行的局面，下架/暂停仍使会话不可用。
SDK 默认持续钉住初始化时读取的版本；切换版本应由调用方显式选择新一局配置。

### 2.1 会话环境描述与 `state`

WS `{"type":"state"}`（客户端 `env.state()`）返回官方 state 响应，其中 `data`
包含 `episode_id`、`step_count`、`game_state` 与 `environment`。reset 前
`game_state=null`，environment 描述当前版本；reset 后描述固定到本局版本。
reset 的 `observation.metadata.environment` 也包含同一环境描述，step 不重复发送。

environment 核心字段：

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `game` | string | 游戏 slug |
| `name` | string | 展示名称 |
| `version` | string | reset 前为当前发布版本，reset 后为本局固定版本 |
| `actions` | object/array/null | 动作名称摘要 |
| `obs_modes` | string[] | 可请求的 observation 模式 |
| `max_concurrent_envs` | integer | 当前每游戏最多 64 个并发环境，所有客户端共享 |
| `meta` | object | 本局版本的棋盘/控件等元数据，供历史回放渲染 |
| `schemas.state` | JSON Schema | 当前适配器完整游戏状态的结构，不是 step 入参 |
| `schemas.action` | JSON Schema | step 的 `value` 所承载的游戏原始动作 |
| `schemas.observations` | object | 按 `obs_mode` 索引的 observation Schema |

`schemas.*` 使用 JSON Schema Draft 2020-12。张量 Schema 额外包含两个注解字段：

- `x-shape`: 固定张量形状。
- `x-dtype`: 当前为 `float32`。

旧游戏包没有声明 Schema 时，平台会返回允许任意 JSON 对象的 state Schema，并
根据 `actions`、`obs_modes`、`obs_shape` 生成尽可能准确的兼容 Schema。新游戏包
应直接从 `info()` 返回完整 `schemas`。

发布/注册时平台会用 `schemas` 交叉校验 `game.yaml contract.*`：`obs_mode` 必须
在 `obs_modes` 中；声明 `obs_mode` 时 `in_shape`（去掉前导 batch 维）必须等于该
observation 的 `x-shape`；`simple` 协议的 `out_shape` 末维必须等于
`schemas.action.enum` 的动作数。不一致直接拒绝注册（UGC 审核返回 400）。
未声明 `obs_mode` 的复合动作游戏（如 microrts）跳过形状比对，其模型形状仍由
上传 ONNX 时的契约校验把关。

### 2.2 `reset`

WS 请求：

```json
{"type":"reset","data":{"seed":42,"version":"1.0.0","options":{},"obs_mode":"state","rewards":{},"include_state":true}}
```

- `seed` 为非负整数，默认 0；`options` 由游戏定义。
- `obs_mode` 缺省取首个服务端观测模式；显式 `state` 请求当前适配器完整状态，
  其他值必须由游戏声明。
- `rewards` 只覆盖游戏声明的奖励键，在整局内固定；数值必须有限且绝对值不超过 1000。
- `include_state` 默认 false；true 时张量观测也附带完整 state。非法配置明确报错。

### 2.3 `step` 与 observation

WS 请求仅提交动作，不由调用方注入游戏状态：

```json
{"type":"step","data":{"value":1}}
```

`value` 可以是整数、命令列表或复合对象，具体由游戏的 `schemas.action` 定义。
reset/step 响应沿用官方形状：
`{type:"observation", data:{observation, reward, done, ...}}`。其中 observation 为：

- 张量：`{type:"tensor", data:[...], shape:[...], dtype:"float32", state:null, metadata:{...}}`；
  `include_state=true` 时 state 为完整游戏局面。
- 状态：`{type:"state", state:{...}, metadata:{...}}`。

完整状态是现有快照型 `EnvAdapter` 的能力，不意味着任意未来游戏必须公开内部状态，
也不表示复杂外部游戏引擎已接入。环境本身在 done 后不会自动 reset。

### 2.4 客户端与生命周期

```python
from openenv.core import GenericEnvClient

with GenericEnvClient(base_url="http://127.0.0.1:8080/api/openenv/tetris").sync() as env:
    info = env.state()["environment"]
    first = env.reset(seed=42, version=info["version"],
                      obs_mode="state", include_state=True)
    result = env.step({"value": 3})
    print(result.reward, result.done, result.observation["state"])
```

每游戏 64 个并发环境是共享容量上限，不是吞吐保证。关闭连接销毁会话；超时或断线
后不要盲目重发 step（先前动作可能已执行）。当前不支持断线续局，重连后显式 reset。
成功、错误和取消路径都应关闭连接。

SDK 继续提供 Gymnasium 单环境/向量包装；向量槽各有独立 OpenEnv 连接，seed 推进、
自动重开和终止观测由 SDK 管理，不再用单个 HTTP 请求推进整批环境，不承诺旧批处理性能。

## 3. Match API v2

创建和操作对局需要登录。练习、PvP、模型对战、观战和回放共享一个 Match，创建时
获得字符串 `uid`，一直用于快照、命令和回放。前端舞台地址为 `/m/{uid}`。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/api/v2/matches` | 创建对局，返回 201 MatchView |
| GET | `/api/v2/matches?game={game}&mode={mode}` | 等待中的公开房间；`mode` 可省略 |
| GET | `/api/v2/me/matches` | 当前用户的 waiting/active 对局 |
| GET | `/api/v2/matches/{uid}` | 当前视角的 MatchView 快照 |
| GET | `/api/v2/matches/{uid}/stream` | SSE 事件流 |
| GET | `/api/v2/matches/{uid}/frames?from={offset}&limit={limit}` | 帧分页 |
| POST | `/api/v2/matches/{uid}/seats/{seat}/join` | 入座，私有房提交邀请码 |
| POST | `/api/v2/matches/{uid}/actions` | 提交当前 tick 的动作 |
| POST | `/api/v2/matches/{uid}/controller` | 切换练习局自己座位的控制器 |
| POST | `/api/v2/matches/{uid}/resign` | 认输或取消等待中的房间 |
| POST | `/api/v2/matches/{uid}/rematch` | 人类 PvP 终局后发起或接受再来一局 |
| POST | `/api/v2/matches/{uid}/chat` | 座位玩家发送聊天消息 |
| POST/DELETE | `/api/v2/{game}/matchmaking/queue` | 加入或取消快速匹配 |
| GET | `/api/v2/{game}/matchmaking/status` | 查询排队状态与匹配后的 `match_id` |

### 3.1 创建、状态与座位

例如登录用户创建固定 seed 的 snake 练习局：

```json
{"game":"snake","mode":"practice","visibility":"unlisted","settings":{"seed":42}}
```

请求支持 `game`、`seats`、`mode`、`visibility`、`settings`；当前 `settings`
只支持 `seed`。省略 `seats` 时服务端根据游戏配置创建座位和默认对手。显式座位
形如 `{"seat":"p0","occupant":"me","controller":{"type":"human"}}`；
控制器类型为 `human`、`ai`、`model` 或 `bot`。无人占座的模型对战至少需要一个
创建者自己的模型。

`kind` 由座位推导，为 `pve | pvp | model_vs_model`；人类 PvP 的 `mode` 为
`casual | ranked`，其余为 `practice`。`visibility` 为 `public`、`unlisted` 或
`private`；前两者可凭 id 读取，private 只允许座位玩家读取，私有房入座需要邀请码。

`status` 为 `waiting | active | finished | cancelled | aborted`，后三者为终态。
进行中状态与匹配队列在内存中，记录创建时即写入 SQLite；终局时服务端尝试封存帧。
重启后的对局记录仍可读取，进行中状态不会继续运行。

MatchView 主要字段包括 `id`、`game`、`version`、`kind`、`mode`、`visibility`、
`status`、`result`、`seats`、`you.seat`、`tick`、`frame`、`to_act`、
`deadline_at`、`frames`、`chat` 和 `seq`。观战者的 `you.seat` 为 null；
进行中的帧按观看者视角裁剪。

### 3.2 动作、事件与重连

提交动作必须提供当前快照的 tick，例如：

```json
{"tick":0,"action":1}
```

成功返回 202 `{"accepted":true,"seq":...}`，是接收确认而不是新局面。动作格式由
游戏定义；同座位同 tick 在结算前重复提交会覆盖待提交动作，过期 tick 返回 409
`stale_tick`。新状态由快照或事件流读取。业务错误的响应包含
`{"detail":{"code":"...","message":"..."}}`。

SSE 首次连接发送快照，随后发送 tick、seat、status、chat 等事件；客户端可用
`Last-Event-ID` 或 `since` 续传，超出服务端保留范围时重新接收快照。服务端会发送
ping。对局聊天仅供座位玩家读取，消息保留在进行中对局的内存中，不写入封存回放。

### 3.3 成绩与历史

`GET /api/{game}/scores` 只读。服务端在符合条件的 PvE 练习局结束时自动写榜：
认输、指定 seed、缺少分数和分数超出声明范围的对局不上榜。
ranked 人类 PvP 结算 ELO；casual 不结算 ELO。

`GET /api/v1/matches` 和 `GET /api/v1/matches/{id}` 仍是需要登录的只读记录接口，
其中数字 `id` 是记录 id；返回的 `uid` 用于 v2 快照和帧。列表按参与玩家筛选，
可能包含进行中对局；`GET /api/v2/me/matches` 专门用于进行中对局和重连。

## 4. 帧与回放

`GET /api/v2/matches/{uid}/frames?from=0&limit=1` 返回示意：

```json
{"frames":[{"tick":0,"frame":{},"actions":null,"events":[]}],"next":1,"total":2}
```

每帧包含 `tick`、`frame`、`actions`、`events`，还可能
包含时间线 `marks`；初始帧的 `actions` 为 null。`from` 是帧数组偏移，不是 tick；
`limit` 为 1–500，最后一页 `next` 为 null。进行中的帧按观看者视角裁剪，终局记录
读取已封存帧。浏览器和 SDK 不需要连接 OpenEnv 逐动作重算。

旧记录可通过迁移脚本生成 uid 和帧；原版本、seed 或数据不足时，可能仍没有可用帧。
历史记录仍可查询；能否回放取决于该记录的实际迁移结果。

## 5. 破坏性切换边界

- 远程环境仅使用官方 OpenEnv；旧环境 API 不再提供兼容。
- 对局创建、操作、观战和回放使用 v2 Match；旧 v1 play、rooms、matchmaking、模型
  对战创建和 replay API 已删除。客户端不得依赖旧路径或旧响应形状。
- v1 对局记录列表、记录详情和 ELO 积分榜仍作为只读接口使用，不代表旧游玩协议
  仍可用。
- 游戏特定 state/action/observation 由游戏包定义。SDK 的单环境 Gym wrapper
  不自动重置终局；向量 wrapper 使用 Gymnasium `SAME_STEP`，通过 `final_obs`、
  `final_info` 及对应掩码提供终局信息。
