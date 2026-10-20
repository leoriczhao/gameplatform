# CHANGE-20261016-ugplay-layout ship

- 制品版本 / 镜像 / commit:
  - **已发版** `games.cree1p.com`（2026-10-16 18:28 CST / Asia/Shanghai）
  - 镜像：`gameplatform:ugplay-layout-20261016-1827`（= `gameplatform:latest`）
  - Image ID：`08641349865a` / digest `sha256:08641349865a80110a8cd6c6df15e6b0195791649dd76e6531424f869b56f6b9`
  - 服务器标记：`~/gameplatform/deploy/CURRENT_RELEASE` = `ugplay-layout-20261016-1827`
  - FE bundle：`/assets/index-8WET_-7M.js` + `index-wSvVSxMK.css`
  - 上一发版（回滚用）：`ugplay-openenv-state-20261015-1720` / 亦标 `before-ugplay-layout-20261016-1827`（`sha256:88b307ef9d41…`，ID `88b307ef9d41`）
  - 仓库无 git commit（服务器 `~/gameplatform` 非 git 工作树）
- 范围: FE only — `UgPlay.jsx` + `index.css`（布局解耦、单一登录门、挑战链 `/models`）。无 BE / DB。
- 迁移 / 回滚: 无 DB；回滚 =
  `docker tag gameplatform:ugplay-openenv-state-20261015-1720 gameplatform:latest && cd ~/gameplatform && docker compose -f deploy/docker-compose.yml up -d --no-deps web`
- 健康检查（生产实测）:
  - `/api/ready` → 200 `{"status":"ready","games":["microrts","snake","tetris"]}`；容器 `healthy`
  - `/games/microrts` `/games/snake` → 200；SPA 引用新 bundle `index-8WET_-7M.js`
  - FE 含 `ug-play-grid` / `ug-board-frame` / 「去模型托管发起挑战」；无 `ModelChallenge` 内嵌、无「游客也可游玩与上榜」
- 发版后必叫 QA 现网复测 handoff 1–7 + G01
- gate: **shipped**（leoric human-ship 已确认于 KR 运维私聊「确认发版」；KR 运维已发）
