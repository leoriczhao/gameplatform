# CHANGE-20261014-rl-lab-ux ship

- 制品版本 / 镜像 / commit:
  - **已发版** `games.cree1p.com`（2026-10-15 15:02 CST / Asia/Shanghai）
  - 镜像：`gameplatform:rl-lab-ux-20261015-1502`（= `gameplatform:latest`）
  - Image ID：`a830d480f1e8` / digest `sha256:a830d480f1e8bf8f817c2fd2e6bd7757476a635cccd4509929de1a49ae32a14f`
  - 服务器标记：`~/gameplatform/deploy/CURRENT_RELEASE` = `rl-lab-ux-20261015-1502`
  - `web/src` fingerprint（服务器）：`b481142a20eb3074355ef2a851ada4457b183624a4b155d88303d197ae806dec`
  - 上一发版（回滚用）：`openenv-mcp-20260909-145601` / 旧镜像 `sha256:0f8dbc54428219df335f4748e9de2240e07ab85c9ca273948ccc2d5dce368352`
- 范围: AppShell / Lobby / Models / UgPvp / Watch·Profile D27 文案；无 backend / OpenAPI / DB 迁移
- 迁移 / 回滚: 无 DB 迁移；回滚 = `docker tag`/`compose` 切回上一镜像并 `docker compose up -d web --no-deps`（或还原 `web/` 至上一发版后重建）
- 健康检查（生产实测）:
  - `/` → 200；Hero 主 CTA 含 **模型托管** → `/models`、**API 文档** → `/api.html`（bundle 已验）
  - 顶栏 labels：大厅 · 模型托管 · API 文档 · 上传游戏 · 战绩 · 好友 · 资料；**无「对战中心」导航项**（「对战中心」仅出现在 NotFound 说明文案）
  - `/arena` → HTTP 404 `{"detail":"Not Found"}`（直链）；SPA 内 `*` 路由仍有客户端 NotFound 文案
  - `/models` → 200（SPA）；登录后列表+工作台需人工点验
  - `/games/snake/pvp` → 200；三 Tab：**找对手 / 对局 / 排行榜**
  - `/api/ready` → 200 `{"status":"ready","games":["microrts","snake","tetris"]}`；容器 `healthy`
- 已知非阻断: eval 指标会话 cache；跨刷新保留需另开 BE「写回 meta」小变更
- gate: **shipped**（leoric human-ship 已确认；KR 运维已发）
