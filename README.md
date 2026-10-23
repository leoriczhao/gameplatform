# 🎮 Stream — 多游戏 RL 平台（v1.0）

一个「游戏 + 训练 + 模型对战」三位一体的多游戏 RL 对战平台。目标域名 `games.cree1p.com`。

- **统一环境入口**：仅公开官方 OpenEnv 0.4.1（`/api/openenv/{game}`），WS 一连接一实例，使用 `GenericEnvClient.reset/step/state`；训练在客户端，环境计算在后端。新契约见 [OpenEnv 环境交互](docs/api/openenv.md)，旧环境 API 已删除，不保留兼容
- **对战闭环**：房间（公开/私有 · ranked/casual）、快速匹配（ELO band 撮合）、断线重连、再来一局、观战 + 回放 + 分享链接
- **平台能力（v1.0）**：账号/游客、资料/好友/房间聊天/通知（轮询落库）、XP/等级/战绩墙/总榜周榜、公告/举报/管理后台、SQLite 备份脚本
- **模型生态**：ONNX 托管（契约校验）、评估、模型 vs 模型 / vs 内置 AI
- **渲染 v2（2026-09）**：声明式棋盘（精灵/矢量/朝向/归属色/血条/图层/动效/HUD）→ 资源包（PNG/WebP + 音效）
  → 沙箱自定义渲染器（opaque-origin Worker + OffscreenCanvas，默认关闭）；设计见 `docs/design/16`
- **闭环**：SDK 训练（gym 接口，SB3/CleanRL 直接用）→ `export_onnx` → 上传托管 → 网页对局

> 历史 v1.0 五批次（a 对战 → b 身份社交 → c 成长排行 → d 运营 → e 基建）的设计与验收记录
> 见 `docs/design/`（00 蓝图 → 09 GDK），前端规范见 `web/DESIGN.md`。这些记录不是本次 OpenEnv 切换的部署或测试证明。

## 游戏

| id | 游戏 | 环境 | 内置 AI |
|---|---|---|---|
| `snake` | 贪吃蛇 20×20（从 snake.cree1p.com 迁入，**环境逐位一致**） | 相对动作 0=左转 1=直行 2=右转 | DQN（rotwin R=10，numpy 推理） |
| `tetris` | 俄罗斯方块 10×20（新） | 0=左移 1=右移 2=旋转 3=硬降，7-bag | 启发式基线（Dellacherie 一子搜索） |
| `microrts` | 微RTS 16×16（MicroRTS 规则移植） | **多单位复合动作** `[[unit_id, cmd, dir?, type?], …]`；单代理 vs 内置策略 / 双代理 external | WorkerRush / LightRush / RangedRush 确定性脚本 bot |

> PvP（房间/匹配/观战回放）按游戏包 `pvp.enabled` 能力声明开放（microrts、石头剪刀布等）；接入见 `docs/design/09-游戏接入指南.md`（v2 游戏包）。

## 目录

```
backend/            FastAPI 平台服务
  main.py           入口：注册表挂路由 + SPA 静态服务 + docs + 后台线程
  registry.py       游戏注册表（新游戏 import 即注册）
  game_routes.py    通用 AI 咨询 / scores 平台业务路由（按注册表生成）
  api_limits.py     平台 API 限流
  environment_contract.py   游戏环境描述与 JSON Schema
  openenv_native.py 唯一环境入口：官方 OpenEnv PlatformEnvironment + create_fastapi_app（/api/openenv/{game}/*）
  scores.py         通用排行榜（SQLite，game_id 列）
  auth.py / auth_routes.py           账号、JWT、游客
  sessions.py / play_routes.py       服务器权威会话（PvE/PvP）+ 房间 + 重连/rematch
  matchmaking.py / matchmaking_routes.py   快速匹配（内存队列 + ELO band）
  matches.py / matches_routes.py     PvP 落库 + ELO + 模型对战 worker + 回放端点
  models.py / model_routes.py / inference.py   ONNX 托管与推理
  social.py / social_routes.py       资料/好友/房间聊天/通知
  growth.py / stats_routes.py        XP/等级/战绩/总榜周榜/ELO 走势
  admin.py / admin_routes.py         公告/举报/管理后台（首 admin 环境变量 bootstrap）
  ugc*.py / registry.py            游戏库：包校验/静态扫描/沙箱 runner/代理注册（13 G3 起平台零游戏代码）
packaged-games/      官方种子游戏包（snake/tetris/microrts：game.yaml + __init__.py + 资源，
                    与用户上传走同一条沙箱管线，启动自动播种，作者显示「官方」）
web/                React 18 + Vite + Tailwind + lucide：Lab UI（深/亮双主题，src/lab/）
  src/lab/          tokens.css / LabShell（导航+命令面板+主题）/ 全部页面（总览、环境、模型、对局、试玩、PvP、观战回放、资料、好友、通知、管理、UGC）
  src/components/   UgBoard（通用棋盘门面）
  src/render/       渲染 v2：schema 归一化/动效/资源/Canvas/DOM/HUD/沙箱宿主（docs/design/16）
static-docs/       静态文档：api.html 接口文档 + vendor/（自托管 Swagger/ReDoc）
sdk/                Python SDK（训练 + 全量 API 客户端）
  gameplatform/remote.py   RemoteVecEnv(game, n, obs_mode)：每槽独立 OpenEnv 连接
  gameplatform/gym.py      gymnasium 封装，注册 platform-{game}-v0
  gameplatform/export.py   export_onnx（导出即过契约）
  gameplatform/client.py   PlatformClient / SessionClient（v1 API 全量封装）
  gameplatform/games/      客户端观测特征（snake features/rotwin/reach）
training/           训练脚本：snake_dqn.py / tetris_dqn.py（DQN 主循环，内置 DQN 权重的来源）
tests/              pytest（官方 OpenEnv、SDK 训练、回放升级、空库启动等）
deploy/             Dockerfile（node 构建前端 → python 运行时）+ compose + backup.sh + tunnel
docs/api/           当前 OpenEnv / runtime 契约、隔离说明及历史验收记录
docs/design/        历史设计/决策与当前 GDK 指南（00-README 是索引）
```

> 部署：Docker 多阶段构建（node:22 跑 `npm run build` → 产物 COPY 进 python 镜像，FastAPI 直接服务 dist）。
> 本地联调前端：`cd web && npm run dev`（vite 把 `/api` 代理到 127.0.0.1:8080）。
> 数据：SQLite（`SCORES_DB`，生产在卷 `/data`）+ 内存态会话/房间/匹配队列（重启即失效，D12）。

## 本地开发与验收

后端需要 Linux x86_64/aarch64、启用 Landlock ABI ≥ 3 的内核及 `libseccomp2`。
不满足隔离条件时游戏加载失败，服务拒绝报告就绪；没有不安全回退。
Debian/Ubuntu 可通过 `sudo apt-get install libseccomp2` 安装运行库。

在项目根目录执行（Python 3.12）：

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt -e sdk
(cd web && npm ci && npm run build)

# 无需设置管理员。官方包使用不可登录的系统作者自动播种。
env -u PYTHONPATH SCORES_DB=/tmp/gameplatform-dev/scores.db \
  .venv/bin/uvicorn --app-dir backend main:app --host 127.0.0.1 --port 8080
# 大厅 http://127.0.0.1:8080/ · Swagger /docs · 就绪检查 /api/ready
```

未指定 `MODELS_DIR` 时，游戏包和模型放在数据库同级的 `models/` 目录。
管理员仅用于管理后台；需要时设置 `ADMIN_USERNAME`/`ADMIN_PASSWORD` 后启动。
`/api/health` 提供进程指标，`/api/ready` 检查数据库及官方游戏的真实 worker 调用。
Docker 健康检查使用 `/api/ready`，保持非 root、只读文件系统及 no-new-privileges。

安装测试依赖并执行完整验收（CPU 版 PyTorch 即可）：

```bash
.venv/bin/pip install 'torch>=2.6,<3' --index-url https://download.pytorch.org/whl/cpu
.venv/bin/pip install -r backend/requirements-dev.txt
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q
(cd web && npm test && npm run build)
```

`tests/test_sdk_training.py` 会启动临时本地服务，实际运行两个 DQN 脚本、
检查权重更新，并执行 ONNX 导出→上传→模型代打。`tests/test_fresh_start.py`
使用空数据目录、不配置管理员，验证启动、注册和重启后的持久化。
所有验收均使用临时数据，不访问线上服务。运行时边界见
[API 契约](docs/api/runtime-contracts.md) 与 [隔离说明](docs/api/ugc-isolation.md)。
旧协议时期的实测结果和适用边界见 [历史可靠性验收记录](docs/api/reliability-validation.md)。
历史 kr 部署、浏览器截图和回滚备份见 [远端验收记录](docs/api/kr-deployment-validation.md)；
它们不代表当前 OpenEnv 版本已部署或通过同一轮验收。

本机 ROS 的 pytest 插件可能污染测试，使用上面的 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`。
数据库备份见 `deploy/backup.sh`；历史回放还依赖对应游戏包，迁移时需保留整个数据目录。

## CI/CD（GitHub Actions）

| 工作流 | 触发 | 做什么 |
|---|---|---|
| `ci.yml` | push `main`、PR | 后端 pytest（Python 3.12 + CPU torch，先检查 Landlock ABI ≥ 3）、前端 `npm test` + `npm run build`、Docker 镜像构建并以生产安全选项启动到 `/api/ready` |
| `release.yml` | 推送 `v*` 标签 | 复用 CI → 镜像推到 `ghcr.io/<owner>/gameplatform:<标签>` → 创建 GitHub Release → 调用 Deploy（带 `-` 的预发布标签不部署） |
| `deploy.yml` | Release 调用，或 Actions 页手动运行 | SSH 到服务器执行 `deploy/release.sh`：备份数据库 → 旧镜像存为 `gameplatform:before-<标签>` → 只重建 `web` → 等 healthy，失败自动切回旧镜像。手动运行填旧标签即为回滚 |

发版：`git tag v1.2.0 && git push origin v1.2.0`。

部署前在仓库 Settings → Environments 建 `production`（建议开启 Required reviewers），并配置：

- secrets：`DEPLOY_HOST`、`DEPLOY_USER`、`DEPLOY_SSH_KEY`（专用部署私钥）、`DEPLOY_KNOWN_HOSTS`（`ssh-keyscan <host>` 的输出）
- vars：`DEPLOY_PATH`（服务器上的项目目录，内含 `deploy/.env` 与 `.tunnel-token`）、`PUBLIC_URL`（如 `https://games.cree1p.com`）

`deploy/.env` 和 tunnel token 只留在服务器，CD 只同步 `docker-compose.yml`、`backup.sh`、`release.sh`。

## 加一个新游戏

完整步骤见 `docs/design/09-游戏接入指南.md`，要点：

1. 编写游戏包：`packaged-games/my_game/` 下放 `game.yaml`（v2 元数据：contract.protocol / obs_mode、pvp.options、opponents、controls 等）+ 实现鸭子类型契约（`info/new_state/step_state/obs/ai_action/opponent_action/sample_action/score_bounds`，纯函数、同 seed 同轨迹），可多文件（env.py / ai.py / baseline.py），资源用相对路径或 `__file__` 字符串读取（沙箱内禁止 import os 等）
2. 本地自测：`gdk-ug/test_runner.py`（与线上沙箱 worker 同一套加载与 v2 校验逻辑）；平台启动时自动 seed 并发布 `packaged-games/*`（官方作者）
3. 可选：模型托管——`game.yaml` 里声明 model protocol（`model_inputs/model_decode`，支持 composite），AI 演示对手声明在 `opponents/default_opponent`；PvP 能力由 `pvp.options` 声明
4. 无需写前端：通用页面 `/games/{slug}`（单机/看板）与 `/games/{slug}/pvp`（对战）由平台提供；
   渲染用 `game.yaml` 声明（渲染 v2：cell/background/layers/hud/events + sprite/vector/orient/anim，
   资源包与沙箱渲染器见 [16](./docs/design/16-前端渲染能力开放设计.md)）；也可通过 `POST /api/v1/ugc/games` 上传游戏包（UGC 作者，受沙箱限制）
5. 补测试：确定性（同 seed 同轨迹）、边界态、非法输入、会话/模型冒烟

## OpenEnv 与 SDK 速览

```python
from openenv.core import GenericEnvClient

with GenericEnvClient(base_url="http://127.0.0.1:8080/api/openenv/tetris").sync() as env:
    info = env.state()["environment"]
    env.reset(seed=42, version=info["version"], obs_mode="state")
    result = env.step({"value": 3})
    print(result.reward, result.done, result.observation["state"])
```

目录 `GET /api/games` 提供 `openenv_url`/`schema_url`。连续 reset/step 必须在同一
WS 连接内；HTTP reset/step/state 各使用临时实例，不支持跨请求续局或状态注入。
断线/超时不要盲目重发 step，重连后显式 reset。当前每游戏共享 64 个并发环境，
不是性能承诺。历史回放按原 version + seed + options reset，再逐条 step 动作。
游戏运行层仍为现有 `EnvAdapter`，不意味着任意复杂外部游戏已支持。

SDK 保留 Gymnasium 包装；向量环境每槽一连接，不再单 HTTP 批量推进，
不承诺旧批处理吞吐。关闭 wrapper 会释放连接，自动重开/终止观测由 SDK 管理。

```python
from gameplatform import RemoteVecEnv
envs = RemoteVecEnv(game="tetris", n=16, obs_mode="grid")   # 16 条独立 OpenEnv 连接
try:
    obs = envs.reset()
    obs, rewards, dones, infos = envs.step([3] * 16)
finally:
    envs.close()

import gameplatform.gym, gymnasium as gym                  # 注册 platform-*-v0
from stable_baselines3 import PPO
with gym.make("platform-tetris-v0", obs_mode="grid") as env:
    model = PPO("MlpPolicy", env).learn(100_000)

from gameplatform import PlatformClient                     # v1 API 全量封装
c = PlatformClient(base_url="https://games.cree1p.com"); c.login("alice", "secret")
s = c.create_room("microrts", mode="casual", visibility="public")   # 建房/快速匹配/聊天/统计…
```
