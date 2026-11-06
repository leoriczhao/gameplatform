# API 轻量压测（k6）

用途：给核心只读接口做低成本冒烟压测，不是容量规划工具。

覆盖端点：

- GET /api/ready
- GET /api/games
- GET /api/v1/microrts/play/rooms

默认阈值：错误率 < 1%、p95 < 500ms、checks > 99%。

## 本地运行

~~~bash
# 先确保后端在 127.0.0.1:8080
BASE_URL=http://127.0.0.1:8080 VUS=5 DURATION=20s k6 run loadtest/k6-smoke.js
~~~

安装 k6（Linux）：

~~~bash
curl -fsSL -o /tmp/k6.tar.gz \
  https://github.com/grafana/k6/releases/download/v0.57.0/k6-v0.57.0-linux-amd64.tar.gz
tar xzf /tmp/k6.tar.gz -C /tmp
/tmp/k6-v0.57.0-linux-amd64/k6 version
~~~

## 对生产环境

不要在未通知/未获批的情况下对 https://games.cree1p.com 加压。需要时与运维确认窗口，
从低 VU 起（如 VUS=2 DURATION=10s），并观察 /api/ready、Cloudflare 与服务器负载。
本仓库不在 CI 自动运行此脚本。
