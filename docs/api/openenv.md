# OpenEnv 环境交互（破坏式更新）

环境交互只使用官方 OpenEnv 0.4.1。旧的 `/api/{game}/env/info`、
`new_batch`、`step` 已删除，无重定向、无兼容服务器。平台账号、游玩、
排行榜、模型、对局记录等业务 API 不变。底层游戏包与沙箱引擎仍复用。

## 会话与发现

- `GET /api/games` 返回 `openenv_url` 与 `schema_url`，不再有 env_info_url。
- 环境基址 `/api/openenv/{game}`；官方客户端连接其 `/ws`。
- 一条 WebSocket 对应一个环境。reset/step 必须在同一连接上执行。
- 当前每游戏最多 64 个并发环境（所有客户端共享）；这是容量上限，不是吞吐保证。
- 关闭连接销毁会话。超时或连接中断后不要盲目重发 step：先前动作可能已执行。
  当前不提供断线续局；重新建立连接后显式 reset。
- 官方 HTTP 端点仍存在，但每个 reset/step/state 请求均是临时实例，
  HTTP reset 不会给下一次 HTTP step 留下局面。没有旧的 state/action 注入信封。

## reset

WS 请求形状：

~~~json
{"type":"reset","data":{"seed":42,"version":"1.0.0","options":{},"obs_mode":"state","rewards":{},"include_state":true}}
~~~

参数：seed 是非负整数，默认 0；version 可省略（使用当前已发布版本），指定时必须
是仍可用的已审核包版本；options 由游戏定义。obs_mode 缺省为首个服务端观测模式，
显式 `state` 请求当前适配器的完整状态视图，其他值必须由游戏声明。
rewards 在初始化时覆盖已声明的奖励键，并在整局内固定；数值必须有限且绝对值不超过 1000。
include_state 默认为 false；true 时张量观测也附带完整 state。非法配置明确报错。

reset 固定本局游戏版本。发布新版本不影响正在进行的局面；下架或暂停仍使会话不可用。
新一局的 version 由调用方选择，SDK 默认持续钉住初始化时读取的版本。

## step 与 observation

~~~json
{"type":"step","data":{"value":1}}
~~~

value 是游戏原始动作，可以是整数、命令列表或复合对象，不包含由调用方注入的游戏状态。
响应沿用官方形状 `{type:"observation", data:{observation, reward, done, ...}}`。

observation 为下列之一：

- 张量：`{type:"tensor",data:[...],shape:[...],dtype:"float32",state:null,metadata:{...}}`。
  include_state=true 时 state 是完整游戏局面。
- 状态：`{type:"state",state:{...},metadata:{...}}`。

reset 的 `observation.metadata.environment` 包含 game/name/actions/obs_modes/
schemas/meta/version/max_concurrent_envs 等环境描述；step 不重复发送整份描述。
完整状态是现有快照型游戏适配器的能力，不意味着所有未来游戏的策略观测必须公开内部状态。

## state 与版本元数据

发送 `{"type":"state"}`，响应：

~~~json
{"type":"state","data":{"episode_id":null,"step_count":0,"game_state":null,"environment":{"game":"tetris","version":"1.0.0","max_concurrent_envs":64}}}
~~~

reset 前 game_state 为 null，environment 描述当前版本；reset 后 game_state 是会话局面，
environment.schemas 和 environment.meta 均属于冻结的包版本，可用于历史回放渲染。
HTTP /schema 展示当前发布版本的 wire schema；不要把它当成历史包的渲染配置。

## 官方 Python 客户端

~~~python
from openenv.core import GenericEnvClient

with GenericEnvClient(base_url="http://127.0.0.1:8080/api/openenv/tetris").sync() as env:
    info = env.state()["environment"]
    first = env.reset(seed=42, version=info["version"],
                      obs_mode="state", include_state=True)
    result = env.step({"value": 3})
    print(result.reward, result.done, result.observation["state"])
~~~

平台 SDK 继续提供 Gymnasium 包装。向量包装管理多个独立 OpenEnv 连接，不再使用
一个 HTTP 请求推进整批环境；它不承诺旧批处理的性能。各槽 seed 推进、自动重开与
终止观测由 SDK 管理，环境本身不会在 done 后自动重置。多实例要服从实际资源预算。

## 网页与回放

网页从会话 environment 描述读取动作信息；游客预览通过 reset 获取初始局面后关闭连接。
回放记录仍由平台业务 API 提供；重建使用历史 version + seed + options reset，随后
逐条 step 已记录动作，从返回状态渲染。成功、错误、取消均应关闭连接。
确定性重放保证只适用于固定版本、相同初始化参数与动作输入的当前游戏引擎；
不宣称任意外部游戏引擎都支持 seed 回放或状态快照。

MCP 仍走官方会话机制；new_episode 支持相同的版本、观测与奖励配置。

本次本地验证与边界见 [迁移验收](openenv-validation.md)；未部署线上。
