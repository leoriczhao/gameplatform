# 剩余用例闭环走查 · 2026-10-23

> 承接 2026-10-23-p1-verify.md。目标：把 06 矩阵中仍「未验」的用例跑完并留证。
> 方法：脚本化 API 走查（53 步 + 修正后重跑 15 步 + U09 模型 vs 模型单独验证）＋ UI 截图（命令面板/深色/720 宽）。
> 环境：本地 dev（:8080 + :5173，演示库 /tmp/gp-dev）；账号 loopuser / loopuser2 / verifyuser / labadmin。

## 结果（全部通过）

| 用例 | 结果 | 关键证据 |
|---|---|---|
| U01 游客浏览环境/契约 | 通过 | 匿名 /api/games 返回 3 游戏；/api/openenv/list_environments 正常 |
| U03 游客看公开信息/回放 | 通过 | 匿名 GET 公开 waiting 会话 200；匿名 GET 回放 200 |
| U04 注册/登录/游客/token | 通过 | 游客 /auth/me 401（设计如此）；游客可读分数；游客开局 401；verifyuser 登录成功 |
| U05 资料查看/编辑 | 通过 | PUT 成功并持久化；超长昵称后端截断到 24（前端已拦截，观测记录） |
| U07 ONNX 上传 + 契约 | 通过 | snake 夹具上传 200；用 tetris 契约上传返回可读 400（输入 shape 不匹配） |
| U10 模型列表/详情/删除 | 通过 | 列表/详情/删除/删除后 404/列表排除全部通过 |
| U12 内置 AI 演示 | 通过 | /api/snake/ai/action 返回动作 2 |
| U14 快速匹配 | 通过 | 两人排队 → matched → active 会话 |
| U16 排行榜/ELO | 通过 | total/weekly 各 2 条；ratings 返回 ELO |
| U20 UGC 作者上传→草稿→smoke→提交 | 通过 | sokoban zip 上传 200（自动 smoke）→ submit 进入 pending |
| U21 UGC 审核→公开→可玩 | 通过 | 管理员审核队列 pending → approve → /api/games 出现 sokoban → 可创建试玩会话 |
| U23 用户封禁/解封 | 通过 | banned 后登录 401；解封后登录 200 |
| U24 模型下架/恢复 | 通过 | banned 后模型 404；恢复后 200 |
| U25 举报处理 | 通过 | 提交举报 → 管理员 open 列表 → resolved 后可见 |
| U26 看板/后台列表 | 通过 | dashboard / admin models / matches / ugc 均 200 |
| U27 搜索/⌘K 命令面板 | 通过 | 面板可打开并列出全部导航项（截图） |
| U28 通知未读→已读 | 通过 | 加好友产生 friend_add 通知；unread 1 → 全部已读 → 0 |
| U29 好友添加/删除 | 通过 | 添加成功、列表包含、删除后排除 |
| U30 错误/权限/空态 | 通过 | 401 / 403 / 404 / 400 均有可读响应 |
| U31 主题/响应式 | 通过 | 亮色默认；深色截图；720 宽无横向溢出（截图） |
| U09 模型挑战（补全） | 通过 | AI 挑战（microrts，931 moves）；模型 vs 模型（1500 moves，平局） |

## 观测与说明

1. 游客 /auth/me 返回 401 是既有设计（游客 token 不用于资料接口）；U04 判据按「游客可读公开数据、开局需登录」执行。
2. 资料接口对超长昵称是截断到 24 字符而非报错（前端已做校验）；若产品要求后端报错，可另开改动。
3. UGC 包上传的沙箱白名单不允许 __pycache__ 与 .pyc；打包时必须排除（已用 clean zip 验证）。
4. 排行榜接口需要登录（401），与前端「排行榜需账号」一致。
5. 模型 vs 模型使用两个 microrts 近零权重夹具，跑了 1500 tick 平局；只证明链路闭环，不代表策略质量。
6. 演示库中新增了测试用户/UGC 游戏 sokoban/模型，均为 /tmp/gp-dev 本地数据，未提交仓库。

## 证据

- docs/pm/qa/evidence/2026-10-23/run_rest.py / run_rest2.py / run_rest.json / run_rest2.json
- docs/pm/qa/evidence/2026-10-23/u09_mvm.py / u09_mvm.json
- docs/pm/qa/evidence/2026-10-23/u27-command-palette.png
- docs/pm/qa/evidence/2026-10-23/u31-dark-theme.png
- docs/pm/qa/evidence/2026-10-23/u31-mobile-720.png
