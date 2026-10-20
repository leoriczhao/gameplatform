# OpenEnv-only 迁移验收（2026-09-15，本地）

本记录对应破坏式迁移，不是线上部署证明。新契约见 [openenv.md](openenv.md)。

## 已验证

| 检查 | 结果 |
|---|---|
| 全套后端与 SDK pytest（含 Gym / DQN / ONNX） | 326 passed；2 条既有 Torch ONNX 弃用警告；92.24s |
| SDK 0.2.0 editable wheel 构建与安装 | 通过（--no-deps --no-build-isolation，非干净环境全依赖安装） |
| 前端 Node 单元测试 | 52 passed |
| Vite 生产构建 | 通过，产物已更新 |
| 真实 Chromium 151.0.7922.34 浏览器 | 注册、键盘游玩、对局落库、回放播放/跳转、游客预览通过 |
| 回放一致性 | 历史版本 + seed + 动作重放的最终完整 state 与原对局一致 |
| 旧接口移除 | 旧环境三路由返回 404，OpenAPI 不再列出；浏览器全过程旧环境请求为 0 |
| 浏览器错误 | page_errors 为 [] |

全套 Python 测试在同一次 pytest 中通过 326 项；此前也分组通过后端 297 项、SDK 29 项。
协议测试覆盖观测模式/奖励配置、版本冻结、
非法配置不替换原局面、会话隔离、关闭释放容量、无状态注入移除，以及 HTTP/WS 的状态序列化。

[浏览器证据 JSON](evidence/openenv-only-20260915.json) 记录真实 WS 帧方向/类型、reset 版本与 seed。
其中 loopback URL 是已关闭的临时 fixture，不是现有开发或生产服务。截图在本次会话
`/tmp/gameplatform-openenv-browser/`；回放截图已人工查看。没有保存浏览器登录令牌。

## 可复现命令

当前主机装有 ROS pytest 自动插件，且原 NO_PROXY 含第三方 httpx 不接受的 IPv6 排除项；
以下仅为测试进程设置合法环境，不改系统或生产配置：

~~~bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost \
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 CUDA_VISIBLE_DEVICES="" \
.venv/bin/python -m pytest -q
(cd web && npm test && npm run build)
~~~

浏览器验收使用 `tests/live_server.py` 的隔离数据库与 loopback 服务，执行
`tests/browser_acceptance.py` 的 `run(base, output)`，完成后 fixture 关闭服务。
本次为 Chromium 安装了缺失的 Playwright headless-shell；由于此 Harness 的 Node
预加载钩子使 Playwright 驱动启动挂起，浏览器测试进程临时移除了 NODE_OPTIONS /
NODE_USE_ENV_PROXY。最初挂起的任务已取消，相关驱动、服务与游戏 worker 均确认退出；
之后完整浏览器验收通过。

## 范围与限制

- 环境交互仅 OpenEnv；平台登录、游玩、模型、榜单、UGC 等业务 API 保留。
- SDK 0.2.0 的向量环境顺序推进多个 WS 会话，并非原来的单 HTTP 批量请求。
- 未测公网高延迟吞吐或 64 槽满负载；容量测试使用受控单槽验证关闭后可重新申请。
- 没有接入新的 Unity/Unreal 等外部游戏引擎；当前仍复用已存在的包与 EnvAdapter。
- 尚未部署线上，也未通过启动新服务器替换任何现有服务。
