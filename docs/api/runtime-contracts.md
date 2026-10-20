# 运行时 API 契约

本文档定义前端和 SDK 依赖的三类游戏运行接口：Environment、Session、
Match/Replay。平台业务接口以 `/openapi.json` 中的 Pydantic Schema 为机器可读规范；
环境 wire schema 由各 OpenEnv 子应用的 `/schema` 提供。本文解释字段语义、状态迁移
和回放规则，环境细节以 [OpenEnv 契约](openenv.md) 为准。

## 1. 边界与术语

- Environment API 仅通过官方 OpenEnv 公开环境交互，WS 一连接一实例。
- 训练算法和模型计算可以在调用方运行，reset/step 的环境计算在后端执行，不是
  完全离线训练。SDK 的 Gymnasium 向量包装管理多条连接，不是单 HTTP 批量推进。
- Session API 保存一次进行中游玩的权威状态。
- Match API 保存已经提交或结束的对局记录。
- Replay 保存初始化输入和动作序列，不保存每个 tick 的完整状态快照。

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
成功、错误和取消路径都应关闭连接。游客预览 reset 获取初始状态后立即关闭连接，
不创建 play Session、不计成绩。

SDK 继续提供 Gymnasium 单环境/向量包装；向量槽各有独立 OpenEnv 连接，seed 推进、
自动重开和终止观测由 SDK 管理，不再用单个 HTTP 请求推进整批环境，不承诺旧批处理性能。

## 3. Session API

创建会话需要登录账号（游客只能读公开房间与观战）。

主要路径：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/api/v1/{game}/play/sessions` | 创建 PvE/PvP Session 或凭邀请码加入 |
| GET | `/api/v1/{game}/play/sessions/{sid}` | 获取当前快照；公开对局可观战 |
| POST | `/api/v1/{game}/play/sessions/{sid}/actions` | 提交动作 |
| POST | `/api/v1/{game}/play/sessions/{sid}/leave` | 退出、取消或认输 |
| GET | `/api/v1/{game}/play/sessions/{sid}/replay` | 获取当前累计回放，可为部分轨迹 |

### 3.1 Session 枚举

`SessionKind`：

| 值 | 含义 |
| --- | --- |
| `pve` | 单人、内置 AI、托管模型或外部 bot 对局 |
| `pvp` | 两名用户的权威 Session |

`SessionStatus`：

| 值 | 含义 | 终态 |
| --- | --- | --- |
| `waiting` | PvP 房间等待第二名玩家 | 否 |
| `active` | 可以提交动作 | 否 |
| `finished` | 正常结束、认输或超时判负 | 是 |
| `abandoned` | PvE 被退出 | 是 |
| `cancelled` | 等待中的 PvP 房间被房主取消 | 是 |

允许的主要迁移：

```text
PvE: active -> finished | abandoned
PvP: waiting -> active -> finished
     waiting -> cancelled
```

其他枚举：

- `MatchMode`: `ranked | casual`
- `SessionVisibility`: `public | private`
- `PlayerSide`: `p0 | p1`

### 3.2 动作幂等与成绩上榜

`POST .../actions` 可带可选字段 `expected_tick`：与服务端当前 tick 不一致返回 409，
客户端应重新读取快照后重试。这保证网络重试不会多推一 tick 或覆盖待提交动作。

PvE 对局结束后，动作响应与 `GET .../sessions/{sid}` 会返回权威 `match_id`。
`POST /api/{game}/scores` 只接受 `{match_id, name?}`：分数由服务端从该对局读取
（客户端不能自报），仅本人的 `pve` 对局可领，同一对局只能上榜一次。

## 4. Match API

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/api/v1/matches` | 创建异步模型对战 |
| GET | `/api/v1/matches` | 当前用户相关的对局列表 |
| GET | `/api/v1/matches/{match_id}` | 对局详情，包括原始存储回放 |
| GET | `/api/v1/matches/{match_id}/replay` | 规范化公开回放 |

`MatchKind`：`pve | pvp | model_vs_model`。

`MatchStatus`：

| 值 | 含义 | 终态 |
| --- | --- | --- |
| `queued` | 模型对战已创建，等待 worker | 否 |
| `running` | worker 正在执行 | 否 |
| `finished` | 对局完成，结果和回放可用 | 是 |
| `failed` | 模型加载或执行失败 | 是 |

模型对战的迁移为：

```text
queued -> running -> finished | failed
```

PvE/PvP 在 Session 结束后直接写入 `finished` Match。

## 5. Replay v1

### 5.1 端点差异

- Session 回放端点直接返回 `SessionReplay`，允许读取进行中的部分轨迹。Session
  保存在内存中，清理或后端重启后不可再读取。
- Match 回放端点返回 `{ "replay": MatchReplay }`，只提供 `finished` Match，持久化
  保存且无需登录，支持分享链接。
- Match 回放覆盖 `pve`、`pvp` 和 `model_vs_model`。

### 5.2 公共字段

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `schema_version` | `1` | 回放载荷版本 |
| `game` | string | 游戏 slug |
| `game_version` | string/null | 生成轨迹时的游戏包版本 |
| `seed` | integer/null | 初始化 seed；旧记录可能为空 |
| `options` | object/null | 原始初始化 options，重放时传给 OpenEnv reset |
| `moves` | ReplayMove[] | 按执行顺序保存的动作 |
| `players` | ReplayPlayer[] | 人类参与者 |
| `models` | ModelParticipant[] | Match 回放中的模型或内置 AI 参与者 |
| `result` | object | 状态、胜者、原因和游戏特定指标 |

`ReplayMove`：

```json
{
  "tick": 0,
  "action": {},
  "opponent": null
}
```

- `tick` 是应用该动作之前的 tick。
- `action` 的结构由对应游戏的 `schemas.action` 定义。
- PvP 和模型对战的 `action` 通常已经包含 `p0`、`p1`。
- PvE 中服务器实际生成了对手动作时，动作保存在 `opponent`；没有对手时为
  `null`。

### 5.3 重放算法

1. 从平台回放 API 读取记录，连接 `/api/openenv/{game}/ws`（或使用 `GenericEnvClient`）。
2. 用历史 `version=game_version`、原始 `seed`、`options` reset，并请求 `obs_mode="state"`；
   seed=0 有效。确认返回的 `observation.metadata.environment.version` 与记录一致。
3. 按顺序读取 `moves`，有实际 PvE 对手动作时组合为 `{p0: action, p1: opponent}`。
4. 在同一连接逐条 `step({"value": action})`，从返回状态渲染；渲染配置使用 reset 的
   environment 或 `state()` 返回的 `environment.schemas/meta`，不得用当前 HTTP `/schema`
   或当前目录元数据替代历史包配置。
5. 成功、错误、取消均关闭连接。对于正常终局，固定版本与相同初始化参数/动作输入的
   当前游戏引擎应重建相同 state；不扩展为任意外部引擎的保证。认输/超时由会话记录表达，
   不要求游戏引擎 state 本身标记 done。

进行中的 Session 在创建时绑定 adapter 和原始 seed；升级不会替换它。模型对战
在入队时绑定游戏版本，推理和状态转移使用同一 adapter。worker 按游戏和包路径
隔离，历史包无需和当前包争用同一个实例。

归档的已审核版本可以重建，未审核版本不能执行。下架、暂停或删除游戏后不允许
通过历史版本入口恢复执行；缺失的包返回明确错误。旧记录仍可读取，但浏览器对
缺少 `game_version` 或 `seed` 的记录明确拒绝重建，不尝试用最新版猜测历史。

SDK 的单环境 Gym wrapper 不自动重置终局；向量 wrapper 使用 Gymnasium
`SAME_STEP`：返回重置后的 observation，并通过 `final_obs`/`_final_obs` 和
`final_info`/`_final_info` 提供终局观测与掩码。显式 reset(seed=...) 不会额外跳过一次 seed。

## 6. 兼容规则

- 环境接口破坏式切换为 OpenEnv，不保留旧环境路径；账号、play、模型、排行榜、
  对局记录等平台业务路径及 Session 回放的顶层形状不变。
- Replay v1 只增加字段，不删除已有字段。
- 历史 Match 中 `replay` 为纯 moves 数组时，API 规范化为 `seed=null`、
  `options=null`、`game_version=null`。
- 游戏特定 state/action/observation 仍由游戏包拥有；平台共享 Schema 不复制游戏
  规则。
