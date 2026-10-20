# CHANGE-20261015-api-docs-light ship

- 制品版本 / 镜像 / commit:
  - **已发版** `games.cree1p.com`（2026-10-15 15:55 CST / Asia/Shanghai）
  - 镜像：`gameplatform:api-docs-light-20261015-1555`（= `gameplatform:latest`）
  - Image ID：`f1ea76b825b5` / digest `sha256:f1ea76b825b5629006e8e7edc8de7ff040a82cda21f5628fab323b4e534e3b7c`
  - 服务器标记：`~/gameplatform/deploy/CURRENT_RELEASE` = `api-docs-light-20261015-1555`
  - `static-docs/api.html` fingerprint（服务器 / 容器一致）：`f3c98fd43a546552e4034cad013ba786c126cc7d1b32f2123f5f604c0769d319`
  - 上一发版（回滚用）：`rl-lab-ux-20261015-1502` / 旧镜像 `sha256:a830d480f1e8bf8f817c2fd2e6bd7757476a635cccd4509929de1a49ae32a14f`
  - 仓库无 git commit（服务器 `~/gameplatform` 非 git 工作树）
- 范围: 静态 API 文档页亮色壳 + 粘性 TOC + `#quickstart`/`#overview`；无 backend / OpenAPI / DB 迁移
- 迁移 / 回滚: 无 DB；回滚 = `docker tag gameplatform:rl-lab-ux-20261015-1502 gameplatform:latest && cd ~/gameplatform/deploy && docker compose up -d web --no-deps`（或还原 `static-docs/api.html` 后重建）
- 健康检查（生产实测）:
  - `/api.html` → 200；亮色壳 `--bg: #fafafa` 可见；title「Stream API 文档」
  - TOC（JS 自 `h2[id]` + `#quickstart` 生成）含 `#auth` / `#openenv` / `#models`（页面内对应 section id 均在）
  - `#quickstart` / `#overview` 可见；全文无 `/arena` / arena 叙事
  - `/api/ready` → 200；容器 `healthy`
- 已知非阻断（QA）: scroll-spy 高亮偶偏下一节；窄视口 ~800px 横向滚动
- gate: **shipped**（leoric human-ship 已确认于 KR 运维私聊；KR 运维已发）
