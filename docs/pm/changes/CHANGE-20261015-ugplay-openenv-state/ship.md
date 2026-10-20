# CHANGE-20261015-ugplay-openenv-state ship

- 制品版本 / 镜像 / commit:
  - **已发版** `games.cree1p.com`（2026-10-15 17:20 CST / Asia/Shanghai）
  - 镜像：`gameplatform:ugplay-openenv-state-20261015-1720`（= `gameplatform:latest`）
  - Image ID：`88b307ef9d41` / digest `sha256:88b307ef9d410b814dee5396fc169ae473cd6734f4ade8fb446522d070cc8299`
  - 服务器标记：`~/gameplatform/deploy/CURRENT_RELEASE` = `ugplay-openenv-state-20261015-1720`
  - FE bundle：`/assets/index-bmyGLbrs.js`
  - 上一发版（回滚用）：`api-docs-light-20261015-1555` / 旧镜像 `sha256:f1ea76b825b5629006e8e7edc8de7ff040a82cda21f5628fab323b4e534e3b7c`（ID `f1ea76b825b5`）
  - 仓库无 git commit（服务器 `~/gameplatform` 非 git 工作树）
- 范围: BE `openenv_native` 重挂 `/state`→`PlatformState`；FE `UgPlay`/`UgPvp`/`replay` 空安全 + 目录 meta 兜底。无 DB 迁移。
- 迁移 / 回滚: 无 DB；回滚 = `docker tag gameplatform:api-docs-light-20261015-1555 gameplatform:latest && cd ~/gameplatform/deploy && docker compose up -d web --no-deps`
- 健康检查（生产实测）:
  - `/api/ready` → 200 `{"status":"ready","games":["microrts","snake","tetris"]}`；容器 `healthy`
  - `GET /api/openenv/microrts/state` → 含 `environment`（含 `meta`/`name`/`version`/`schemas`）；不再只有 `episode_id`/`step_count`
  - snake / tetris `/api/openenv/*/state` 同样含 `environment`
  - `/games/microrts` → 200；SPA 引用新 bundle `index-bmyGLbrs.js`
- 发版后必叫 QA 复跑现网 SMK-G01
- gate: **shipped**（leoric human-ship 已确认于 KR 运维私聊「确认发版」；KR 运维已发）
