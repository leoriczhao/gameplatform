# 韩国服务器部署与浏览器验收（2026-09-08）

> **历史验收记录（旧环境协议时期）**：保留当时的部署、测试、批处理测量及原始证据，
> 不表示当前 OpenEnv 切换已部署或通过这些验收。文中的旧环境请求/脚本不是当前使用
> 示例；环境交互以 [OpenEnv 契约](openenv.md) 为准，仅使用官方会话入口，无旧 API 兼容。
> 本文关联的 JSON/截图也仅记录当时结果，不应改写为新协议证据。

正式服务已更新：[https://games.cree1p.com](https://games.cree1p.com)。
后端在 `leoric@kr.cree1p.com` 的 Docker 容器 `gameplatform-web` 中运行；浏览器
在本机 WSL 内运行。环境计算、游戏 worker 和数据存储都在韩国服务器。

## 部署状态

- 发布标识：`reliability-20260908-050059`。
- 发布镜像：`gameplatform:reliability-20260908-050059`，正式标签同步为 `gameplatform:latest`。
- 当前镜像 ID：`sha256:f88e6126ad31db1950ee95d5e885eb52f8736229f9acaa96a0dd2d6251feaf85`。
- 正式源码：`/home/leoric/gameplatform`；发布副本和备份：
  `/home/leoric/gameplatform-releases/reliability-20260908-050059/`。
- 保留原 Compose 项目、数据卷 `gameplatform_gameplatform-scores` 和 Cloudflare tunnel。
- 正式监听保持 `127.0.0.1:8081 → 容器 8080`；容器状态 `running / healthy`。
- 容器继续使用 `appuser`、只读 rootfs、`no-new-privileges:true`，没有关闭默认 seccomp。
- 宿主 Linux `6.8.0-117-generic`，容器内 Landlock ABI 查询为 4。
- 三个官方游戏已升为 `1.0.1`；猜数字和石头剪刀布两个既有 UGC 保持可用。

先用相同镜像启动独立空库容器，再用正式数据备份启动升级候选容器。验证通过后，
检查正式服务没有活跃 Session，重新备份数据并替换正式容器。正式数据未被候选
数据覆盖；候选中的测试账号和模型没有迁入正式服务。

## 验证结果

| 验证 | 结果 |
| --- | --- |
| kr 上构建 Docker 多阶段镜像 | 通过，包含新前端产物和 libseccomp2 |
| 无管理员、空数据目录启动 | 三个官方游戏自动播种，`/api/ready` 200 |
| 容器内隔离、worker、官方包测试 | `23 passed, 1 warning in 14.79s` |
| WSL 训练客户端 → kr 后端 | 两个 DQN 脚本实际更新权重；ONNX 导出/上传/代打通过 |
| Gym 单环境/向量终局契约 | 真实远端 HTTP 请求通过 |
| 原有数据升级 | 既有用户、模型、对局行完整保留，SQLite integrity_check 通过 |
| 五个游戏的归档版本 | `1.0.0` reset/step 全部通过；三个官方游戏 `1.0.1` 也通过 |
| 候选容器完整浏览器流程 | 注册 → Tetris 键盘操作 → Snake 终局 → 战绩 → 回放 → 播放/定位通过 |
| 回放正确性 | 浏览器发出的请求均携带版本；重建终局与刚才实际游玩的终局完全一致 |
| 正式域名浏览器流程 | 大厅 5 个游戏可见，Tetris 棋盘和键盘操作通过；游客 Session 已释放 |
| 正式公网 API | HTTPS `/api/ready` 200，三个官方游戏批量 reset 通过 |

容器测试的一个弃用提示来自 Starlette/AnyIO。首次挂载测试代码时因源文件权限
导致读取失败，仅调整发布副本中测试源码的读取权限后完成测试；生产容器的
用户和安全选项保持不变。

迁移核对使用备份中的原始行与正式数据库逐行比较，只输出计数和比较结果：

| 数据 | 部署前 | 部署后 | 原始数据 |
| --- | ---: | ---: | --- |
| 用户 | 12 | 13 | 12 行全部保留；新增不可登录的官方系统作者 |
| 模型 | 3 | 3 | 全部保留 |
| 对局记录 | 18 | 18 | 全部保留 |

对照测试期间，旧服务的 MicroRTS step 和 Snake reset 出现 500；日志显示旧 worker
超过 200 ms 后被强杀。新候选的对应版本及当前版本 reset/step 均通过。这些旧服务
失败没有被当作新版本的通过证据，也没有通过放宽生产隔离来绕过。

## 本地浏览器与 WSL

实际自动化使用 WSL 中的 Playwright 1.62.0 / Chromium `151.0.7922.34`。
候选后端通过仅绑定本地回环的 SSH 转发访问；正式验证直接访问公网 HTTPS 域名。
Windows PowerShell 也实际访问过 WSL 的转发地址并返回 200。
没有修改 Windows 防火墙、Edge 全局设置或 GPU 参数。

- [正式大厅截图](evidence/kr-20260908/production-lobby.png)
- [正式 Tetris 操作截图](evidence/kr-20260908/production-tetris.png)
- [候选容器回放截图](evidence/kr-20260908/candidate-replay.png)
- [正式浏览器结果](evidence/kr-20260908/production-browser.json)
- [完整候选浏览器结果](evidence/kr-20260908/candidate-browser.json)

可重复执行的脚本为 `tests/browser_acceptance.py`。它会注册账号并保存一条对局，
因此完整流程应指向独立验收数据环境。浏览器异常会写入失败截图；不会保存
浏览器 storage state、密码或 token。

```bash
# 可选浏览器验收依赖，不安装进后端 Docker 镜像
.venv/bin/pip install playwright==1.62.0
.venv/bin/python -m playwright install chromium
.venv/bin/python tests/browser_acceptance.py \
  --base-url http://127.0.0.1:18089 --output /tmp/gameplatform-browser-acceptance
```

上面的 18089 是验收期间的临时地址，验收结束后已清理。日常访问使用正式域名。
API/游戏逻辑跑在 kr；浏览器渲染和训练客户端跑在本机。本次未做大规模并发压测，
WSL 中测得的 3.39–4.99 倍 IPC 提速不等于公网或生产吞吐提升倍数。

## 备份与回滚

以下文件保留在远端发布目录的 `backup/` 下，权限为 0600：

- `data-before.tar.gz`：候选验收使用的数据快照。
- `data-cutover.tar.gz`：正式替换前通过 SQLite backup API 导出的数据库及模型/包/密钥。
- `source-before.tar.gz`：原源码及部署配置。
- `compose-before.yml`、`image-before.txt`：原 Compose 配置及镜像 ID。

原镜像另保留为 `gameplatform:before-reliability-20260908-050059`。如确需回滚，
在 kr 上恢复该镜像标签及备份中的 Compose 文件，再只重建 `web` 服务；不要直接
覆盖正式数据库。旧镜像会恢复旧的 UGC 隔离实现，因此回滚仅作为故障恢复手段。
本次没有触发回滚。

临时候选容器、其数据卷和 SSH 转发在验收完成后清理，正式 `gameplatform-web`
及原有 `gameplatform-tunnel` 持续运行。

---

# 渲染 v2 部署（2026-09-08 18:33 server time）

发布标识：`render-v2-20260908-1830`。正式服务 [https://games.cree1p.com](https://games.cree1p.com)
从 `gameplatform:latest` 重建，容器 `gameplatform-web` healthy，tunnel 未动。

## 变更内容

- 渲染 v2（设计 16，D28-D30）：L1 声明式棋盘 + L2 资源包 + L3 沙箱渲染器；
  三个官方种子包升为 **1.1.0**（snake 精灵/朝向/HUD、tetris NEXT 小棋盘、microrts 归属色/血条）。
- 同镜像包含同期完成的 `expected_tick` 乐观并发改动（`sessions.py`/SDK/前端），
  发布前后端全量 `pytest -q` 为 `255 passed`。

## 部署步骤

1. kr 上 `deploy/backup.sh 14` → `/data/backups/scores-20260908-182849.db`；
   回滚信息写入 `/home/leoric/gameplatform-releases/render-v2-20260908-1830/backup/`
   （`source-before.tar.gz`、`compose-before.yml`、`image-before.txt`）。
2. 旧镜像保留标签 `gameplatform:before-render-v2-20260908-1830`（`sha256:f88e6126…`）。
3. rsync 源码 → kr `/home/leoric/gameplatform`（排除 `deploy/.env`、`deploy/.tunnel-token`、node_modules、dist）。
4. kr 上 `docker compose -f deploy/docker-compose.yml build web` →
   `sha256:5e4c9e97…`；`up -d --no-deps web` 重建 web（tunnel 保持运行）。

## 验证结果

| 验证 | 结果 |
| --- | --- |
| 容器健康 + `/api/ready` | healthy，200 |
| 种子播种 | `seed_loader: snake/tetris/microrts v1.1.0 已发布` |
| 公开目录版本 | snake/tetris/microrts = 1.1.0（board.schema=2），两个 UGC 仍 1.0.0 |
| 资源路由 | `/api/ugc/assets/snake/1.1.0/assets/head.png` → 200 `image/png` + `nosniff` |
| 渲染器门禁 | `/api/ugc/render/snake/1.1.0/frame` → 403（未声明渲染器） |
| 公网浏览器（Chromium） | snake/tetris/microrts 均 canvas + HUD 可见，`page_errors: []` |
| 截图 | `/tmp/gp-prod-verify/{snake,tetris,microrts}.png`（本地验收机） |

## 回滚

```bash
docker tag gameplatform:before-render-v2-20260908-1830 gameplatform:latest
cd /home/leoric/gameplatform && docker compose -f deploy/docker-compose.yml up -d --no-deps web
```

数据卷 `gameplatform_gameplatform-scores` 未替换；如需恢复数据用 `/data/backups/scores-20260908-182849.db`。

---

# 热修：登录态失效导致的空白棋盘（2026-09-08 18:5x server time）

用户反馈"登录了也都不行"。复现结论：**僵尸登录态**——浏览器 localStorage 里
`gp_user` 残留、但 `gp_token` 已失效/被清，页面头部仍显示用户名，看起来已登录；
`UgPlay` 用残留 user 去开局，后端返回 401（"请先登录（游玩会话需要账号）"），
而 `newGame()` 没有错误处理 → 页面空白、无任何提示（unhandled rejection）。

根因三处：

1. `AuthContext` 在 `/auth/me` 失败时只删 `gp_token`，**没删 `gp_user`** → 残留身份；
   且无 token 时初始化仍信任 `gp_user`。
2. `UgPlay.newGame()` 无 try/catch，开局失败静默。
3. 游客页面完全没有棋盘，与文案"游客可以看棋盘"不符。

修复（发布 `render-v2-fix1-20260908-1845`，镜像 `sha256:5f5d7cea…`）：

- `web/src/AuthContext.jsx`：无 token 时清除 `gp_user`；me 失败同时清两者并提示
  "登录已过期，请重新登录"；`refreshUser` 401 时同样清理。
- `web/src/pages/UgPlay.jsx`：`newGame()` 增加 try/catch + 可见报错（401 引导重新登录）；
  未登录时用无状态 `/env/new_batch` 拉初始 state 渲染**只读棋盘预览**（不建会话、不上榜）。
- `tests/browser_acceptance.py`：新增僵尸登录态回归断言。

线上验证（公网 HTTPS，Chromium）：

| 场景 | 结果 |
| --- | --- |
| 游客 | canvas 预览棋盘 + "棋盘预览（登录后可操作）" + 登录提示，无 page error |
| 僵尸态（残留 gp_user 无 token） | 残留被清除、头部不再显示用户名、显示登录入口 + 预览棋盘，无 page error |
| 新用户注册后 | 注册 200、棋盘正常、键盘推进正常，无 page error |

回滚：`docker tag gameplatform:before-render-v2-fix1-20260908-1845 gameplatform:latest`
+ `up -d --no-deps web`。


