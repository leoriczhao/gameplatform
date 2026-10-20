# CHANGE-20261015-qa-smoke-lib report-qa

- 环境: 现网 `games.cree1p.com`（游客 + 登录 `qa_smoke_1015`）
- 范围: H01–H08；对照 `docs/pm/qa/smoke-cases.md` · `fixtures.md`
- 结果: **H01–H08 全部通过**（H02/H05 于 2026-10-15 补跑）
- 非目标: 不改业务代码；密码不入库

## 结果表

| id | 优先级 | 结果 | 备注 |
|---|---|---|---|
| H01 游客进局预览 | P1 | **通过** | `/games/microrts` 预览/规则/分数可见；登录门清晰；无 meta TypeError |
| H02 登录后 PvE 一局 | P1 | **通过** | 登录后 `/games/microrts` 内置 AI 演示；TICK 0→15；金矿变动；无 meta TypeError / 无 5xx |
| H03 游戏内 PvP 入口 | P1 | **通过**（游客壳） | `/games/microrts/pvp` 可达；文案「验证支线 · 非对战中心」；需登录对战；非 `/arena` |
| H04 OpenEnv state 契约 | P0 | **通过** | microrts/snake/tetris 均含 `episode_id`/`step_count`/`game_state`/`environment` |
| H05 评估·挑战加深 | P1 | **通过** | 上传 `qa-smoke-snake-1015` #4 契约通过；评估通过·0；挑战台打开；无内置 AI 策略时明确错误「请选择内置 AI 策略」（非静默） |
| H06 战绩/好友/资料壳 | P2 | **通过** | `/records` `/friends` `/profile` 200 + 登录引导 |
| H07 上传游戏壳 | P2 | **通过** | `/ugc` 200 +「登录后即可上传」 |
| H08 F01+G01+H04 | P0 | **通过** | `/` `/api.html` `/models` 200；G01 已绿；H04 绿 |

## 夹具

- FIX-QA-01：`qa_smoke_1015`（Dev 公开注册；密码私聊 QA，未入库）
- FIX-QA-02：`docs/pm/qa/fixtures/snake-rotwin-min.onnx`；现网模型 #4 `qa-smoke-snake-1015`

## 非阻塞备注

- H05 挑战发起：snake 账号下 AI 策略选项仅「无 / 未声明对手策略」（disabled）；点「发起挑战」得到清晰校验错误，符合「明确失败原因、不静默」。完整挑战闭环仍可能依赖内置 AI 策略配置（另议）。

## 结论

H 批现网收口：**全绿**。训练闭环发版基线可宣称 H02/H05 已抽检；D02–D05 加深仍可按需另开。
