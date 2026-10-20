# Stream QA · 测试夹具

> 用途：解锁 H02 / H03（登录进局）/ H05 / D02–D05 等需账号或样例模型的用例。  
> 无夹具时对应用例标 **blocked**，不编造通过。  
> 机密：密码/token **不要**写进本文件；只写账号标识与获取方式。

## FIX-QA-01 · 可登录测试账号

| 字段 | 值 |
|---|---|
| 状态 | **就绪**（2026-10-15 Stream Dev 经公开 `/api/v1/auth/register` 创建） |
| 标识 | 用户名 `qa_smoke_1015`（user id 25，role=user） |
| 权限 | 普通用户；专用 QA 测号，非任何人日常号 |
| 提供方式 | 密码已私聊 Stream QA（**勿写入仓库**）；需重置时再找 Stream Dev |
| 解锁用例 | H02、H03（若需登录）、D01–D05、H05 |

## FIX-QA-02 · 样例 ONNX（已托管或可上传）

| 字段 | 值 |
|---|---|
| 状态 | **就绪**（文件入库；现网已上传到 `qa_smoke_1015`） |
| 路径/资产 | `docs/pm/qa/fixtures/snake-rotwin-min.onnx`（~16 KB） |
| 游戏 | `snake`（契约：`in [1,1334]` / `out [1,3]` / simple / rotwin） |
| 校验 | `inference.check_contract(path, "snake")` → `game.snake`（2026-10-15） |
| 上传说明 | 登录（需 FIX-QA-01）→ `/models` 选游戏 snake → 选本文件上传；勿当评估基线（近零权） |
| 现网模型 | `qa-smoke-snake-1015`（#4，契约 game.snake，评估通过·0；2026-10-15 H05） |
| 解锁用例 | H05、D04、D05（文件步）；完整绿仍依赖 FIX-QA-01 |

## FIX-QA-03 · `pvp_enabled` 公开游戏

| 字段 | 值 |
|---|---|
| 状态 | 现网抽检：microrts / snake 有 `/games/{slug}/pvp` 路由（2026-10-15 HTTP 200） |
| 备注 | 游客可达入口即可验 H03 壳；完整匹配/对局仍可能需 FIX-QA-01 |
| 解锁用例 | H03 |

## 使用规则

1. QA 跑批前读本文件；状态非「就绪」→ 对应用例 **blocked** + 原因。  
2. 夹具就绪后：更新本表状态 → 重跑 blocked 项 → 回填 `smoke-cases.md` / `report-qa.md`。  
3. 发版基线：无夹具时 **不得**宣称训练闭环「全绿」；文档/游客壳类 CHANGE 可不挡。
