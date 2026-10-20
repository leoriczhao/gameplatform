# 我的游戏（GDK-UG 模板）

1. 复制本目录到新名字，按 `game.yaml` 注释填元数据与渲染声明；
2. 实现契约（见 `__init__.py` 的 docstring），`state` 顶层必须含
   `board: [[cell_id, …]×h]`（cell_id 都在 palette 里），可选 `units`；同时在
   `info().schemas` 声明 state、action 和各 observation 模式的 JSON Schema；
3. 本地自测：`python gdk-ug/test_runner.py <你的目录>`；
4. 上传：打包 `zip -r mygame.zip game.yaml __init__.py …`（≤20MB，仅文本文件），
   到平台「上传游戏」页提交，等待管理员审核后公开发布。

发布后的环境交互只使用官方 OpenEnv：基址 `/api/openenv/{slug}`，
`GenericEnvClient.reset/step/state` 在同一 WS 连接上操作一个实例，关闭连接释放环境。
旧环境 API 不保留兼容；平台 SDK 的 Gym 向量包装使用多条独立连接，不是单 HTTP 批量推进。
游戏包仍实现现有 `EnvAdapter`，无需在沙箱内引入 OpenEnv。回放使用原 version、seed、
options reset，再逐条 step；完整规范见 [OpenEnv 契约](../../docs/api/openenv.md)。
