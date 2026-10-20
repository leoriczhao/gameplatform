# 03 · 游玩 API 与 PvP / PvE 流程

> **历史设计，不作为当前环境 API 手册。** 本文保留当时的决策、接口示例与验收记录；
> 环境交互相关内容已被 [OpenEnv 契约](../api/openenv.md) 取代。旧环境 API 已删除，
> 不保留兼容；当前架构见 [架构总览](../architecture.html)，平台业务与回放见
> [运行时契约](../api/runtime-contracts.md)。下文不代表本次切换已部署或通过测试。

## 1. 为什么是"会话制"

现状问题：网页客户端自己持有游戏 state 并调用无状态 env API——单人玩没问题，但：
- **PvP 双方都提交动作时没有权威方**（谁合并动作、谁仲裁顺序？）
- 断线/刷新即丢局，无法恢复、无法观战、无法回放
- 成绩可信度差（客户端可伪造 state 提交）

因此游玩面改为**服务端会话制**：服务端持有对局状态、校验动作合法性、推进 tick、记录回放。环境 API（训练面）保持无状态不变。

**一个引擎原则**：会话服务每 tick 调用的就是 `games/*/EnvAdapter.step_state`，与环境 API 同一份规则代码。

## 2. 会话模型

```
play_session
  id            UUID
  game          snake | tetris | microrts | …
  kind          pve | pvp
  players       [{principal_id, side, controller}]   controller: human|ai|model|external_bot
  state         JSON（当前游戏 state，唯一权威副本）
  tick          当前回合
  status        waiting | active | finished | abandoned
  turn          pve: 单方；pvp: 双方各自已提交的动作集合
  winner/cause
  events_seq    事件游标（回放/增量拉取）
  created_at / updated_at
```

- 会话**短期驻留内存**，结果落库（`matches` 表）；未结束会话重启即丢（可接受，见 00 决策）
- 同时有"人"的会话上限：游客 1 / 用户 8

## 3. 全量游玩 API（/api/v1/{game}/play/*）

### 3.1 创建会话

```
POST /{game}/play/sessions
{
  "kind": "pve",                       // pve | pvp
  "side": "p0",                        // 我在 pvp 中扮演哪一方（pve 忽略，默认 p0）
  "opponent": "light_rush",            // pve: 内置AI策略 | 模型ID | "external_bot:https://…"
  "seed": 12345,                       // 可选，固定地图/轨迹
  "invite": "ABC123"                   // pvp 可选：加入指定房间
}
→ {"session": {"id","status","state","tick","side","players"}}
```

### 3.2 查询会话

```
GET /{game}/play/sessions/{id}
→ {"session":{"id","status","state","tick","winner","cause","players"},
   "side":"p0"|"p1"|null}
```

### 3.3 提交动作（推进 tick）

```
POST /{game}/play/sessions/{id}/actions
{"actions": [[0,5,1,"worker"], …]}     // 该游戏的动作格式（int / 列表 / {"p0":..,"p1":..} 按游戏）
→ {"state","tick","reward?","done","winner","cause","status",
   "advanced?","waiting_for?"}
```

- **PvE**：每次提交立即推进一 tick（我方动作 + 内置 AI/模型对手动作在服务端合成）
- **PvP**：双方各自提交本方动作；**双方都提交后**才推进一 tick；查询接口可见对方是否已提交

### 3.4 退出/认输

```
POST /{game}/play/sessions/{id}/leave
→ {"status","winner?"}
```

### 3.5 进行中状态同步

```
GET /{game}/play/sessions/{id}
→ 当前权威快照
```

当前实现由客户端轮询 Session 快照，没有 SSE/WebSocket 事件流。

### 3.6 回放

```
GET /{game}/play/sessions/{id}/replay
→ {"schema_version":1,"game","game_version","kind","seed","options",
   "players","moves":[每 tick 动作序列],"result":{…}}
```

回放使用同版本游戏的 Environment API，以 `seed + options + moves` 重建轨迹。
完整契约见 [运行时 API 契约](../api/runtime-contracts.md)。

## 4. PvE 流程（单人闯关/打 AI）

```
玩家(网页或API)                    服务端
    │ POST /play/sessions {kind:pve, opponent:…}
    │──────────────────────────────────────▶ 创建会话：new_state(seed)
    │ ◀────────── {"id","state"} ─────────── 对手=内置AI/模型/external_bot 注册到会话
    │
    │ POST /actions [我方指令]              合成对手指令（内置AI本地算/模型worker/外挂URL）
    │──────────────────────────────────────▶ step_state(state, 双方动作) → 新 state
    │ ◀────────── {"state","done",…} ─────── 若 done → 落库成绩（scores，mode=human/ai/model）
    │ … 循环 …
```

- 成绩 `mode`：玩家是人工 → `human`；玩家用"模型代打"→ `model`
- 排行榜即现有 `/scores`，加 `user_id`
- 超时/空闲策略：会话 30 分钟无动作自动结束（不记录成绩）

## 5. PvP 流程（玩家对战）

### 5.1 人 vs 人（在线实时）

> **v2 重设计**：本节描述的"邀请码私房"只是 PvP 的入口之一。完整的
> 房间系统（公开房间列表、ranked/casual、再来一局）、快速匹配队列、
> 模型排位池、观战与回放见 **[06-匹配机制与房间系统](./06-匹配机制与房间系统.md)**。
> 下文状态机与超时/结算规则是 v2 的基础，保持不变。

```
A 玩家                   服务端                      B 玩家
 │ POST /play/sessions {kind:pvp}  创建会话(status=waiting)
 │────────────────────────▶ 返回 {id, invite:"ABC123"}
 │ （把邀请码给 B）
 │                          ◀────────── POST /play/sessions {kind:pvp, invite:"ABC123"}
 │ 双方就位，status=active，开局
 │ POST /actions(p0) ──────▶ 等 B 也提交
 │                          ◀─────── POST /actions(p1)
 │ 双方到齐 → step_state → tick+1 → SSE 推送新 state 给双方
 │ ◀───────── SSE tick ────────────────────────────────▶
 │ 一方 done → winner 落库 → ratings 结算
```

- 每 tick 双方各提交一次；提交后可改（覆盖自己未消费的动作）
- **超时策略**：60 秒未提交 → 自动"等待"（空动作）推进；连续 5 次超时 → 判负并结束
- 断线重连：重新 GET 会话即可继续（state 在服务端）

### 5.2 模型 vs 模型（异步，无需同时在线）

走对战服务（见 04-模型托管与对抗 + 01 的 matches 接口）：创建对战 → worker 跑完整局 → 双方在战绩页看结果与回放。

### 5.3 人 vs 模型（异步不成立，走 PvE）

人 vs 上传的模型 = PvE 会话，`opponent` 填模型 ID。实时人 vs 实时外部 bot = PvE，`opponent: "external_bot:<url>"`。

## 6. PvP 与 PvE 的流程区分（对照表）

| 维度 | PvE | PvP |
|---|---|---|
| 参与者 | 单玩家 + 服务端对手 | 两名真人玩家 |
| 动作推进 | 玩家提交即 tick | 双方都提交才 tick（超时自动等待） |
| 对手来源 | 内置AI / 上传模型 / 外部 bot | 匹配或邀请码 |
| 结果去向 | scores（PvE 排行榜） | matches + ratings（ELO） |
| 掉线处理 | 会话超时丢弃 | 重连恢复 / 超时判负 |
| 鉴权 | 游客可 | 必须登录 |
| 观战 | 无 | v2（公开对局观战，见 06） |

## 7. 会话服务的实现要点

- 会话表内存 dict + `asyncio.Lock` 保证单会话串行（同一会话的动作/状态更新原子化）
- 每次 `actions` 调用：校验动作（复用 `EnvAdapter.validate_action(state, action)`）→ 合成对手动作 → `step_state` → 更新 → 事件队列（SSE 广播）
- 会话清理：后台任务周期回收超时会话
- 回放：每 tick 记录双方动作数组（顺序压缩存 JSON），结束时写 `matches` 表
- 内置 AI 对手：直接调用 `strategies.builtin_commands`（与现在相同）
- 上传模型对手：把 state 转 obs → onnxruntime 推理 → 动作（见 04 的 I/O 契约）

## 8. 与"全量 API 玩"的关系（用户用代码玩）

用户可以不看网页，直接：
1. `POST /auth/login` 拿 JWT
2. `POST /{game}/play/sessions {kind:pve}` 或 `{kind:pvp, invite}`
3. 轮询/SSE 拿 state，`POST /actions` 下指令
4. `GET /replay` 复盘

这就是"走全量 API 玩"。SDK 提供 `SessionClient` 封装（`connect() → state() → act() → events`）。
