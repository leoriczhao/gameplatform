# 可靠性补齐验收（2026-09-08）

> **历史验收记录（旧环境协议时期）**：保留当时的部署、测试、批处理测量及原始证据，
> 不表示当前 OpenEnv 切换已部署或通过这些验收。文中的旧环境请求/脚本不是当前使用
> 示例；环境交互以 [OpenEnv 契约](openenv.md) 为准，仅使用官方会话入口，无旧 API 兼容。
> 本文关联的 JSON/截图也仅记录当时结果，不应改写为新协议证据。

范围：UGC 隔离、真实 SDK 训练、版本回放、批处理和全新应用环境启动。
本文记录最初的 WSL 本地验收；后续已完成 [kr 部署与浏览器验收](kr-deployment-validation.md)。
安全修复结论为 `fixed`：原有间接读取平台文件的触发方式
在真实 worker 中被拒绝，包内读取、NumPy 和三个官方游戏仍能运行。

## 实现与证据

| 项目 | 修复后的行为 | 可重复验证 |
| --- | --- | --- |
| UGC 隔离 | 游戏导入前强制 Landlock + seccomp；最小环境、资源限制，安装失败拒绝执行 | `tests/test_ugc_isolation.py`、`tests/test_ugc_runner.py` |
| SDK 训练 | NumPy 动作递归转为 JSON；单环境保留终局，向量环境声明 SAME_STEP 并返回终局观测 | `tests/test_sdk_training.py` |
| 版本回放 | Session、SDK、模型对战绑定版本；回放携带原版本、seed、options 和实际对手动作 | `tests/test_versioned_replay.py`、`web/tests/replay.test.js` |
| 批处理 | 整批验证、step、obs 在一次 IPC 内完成；reset 和终局自动重置也批量提交 | `tests/test_env_batch.py`、`tests/benchmark_env_batch.py` |
| 首次启动 | 无管理员也会播种官方包；真实 worker 就绪检查；重启保留账号、包路径和已发布的高版本 | `tests/test_fresh_start.py`、`tests/test_seed_loader.py`、`tests/test_versioned_replay.py` |

### 隔离修复

根因是把 Python 函数替换和导入白名单当成了权限边界。允许导入的模块仍能间接
暴露底层文件接口，因此原实现可以读取包目录外的内容。
修复位于所有执行入口共用的 `GameWorker → ugc_worker → ugc_sandbox.install`，
包括上传冒烟、官方播种、正常游玩和归档版本；没有保留仅靠 Python 的回退路径。

回归使用临时标记文件，覆盖间接读取、截断写、chmod、底层 socket、进程创建和
文件描述符控制；文件内容及权限保持不变。正向用例验证包内资产读取和 NumPy。
额外验证缺少隔离时不会导入游戏、冒烟子进程退出、16 MiB 输出上限，以及 worker
不读 stdin 时父进程能按期限结束请求。隔离设计与运行条件见
[UGC 隔离说明](ugc-isolation.md)。

独立调查覆盖共同执行入口；复核指出文件描述符控制调用可能影响父进程后，
已从白名单删除整个 fcntl 调用并增加拒绝测试。独立复核未产出完整最终报告，
因此这里的结论限于已执行的修复验证，不代表完成全面安全审计。

### 真实训练和回放

两个自带 DQN 脚本分别使用 2 个环境、2 个 episode 和 batch size 4，通过真实
本地 HTTP API 完成训练；检查保存权重全部有限，且相对相同随机种子的初始网络
确有更新。这验证执行链路，不证明策略已经收敛。

另一个真实训练用例执行 8 次优化更新，导出 Tetris ONNX，实际上传模型并创建
模型控制的 PvE Session，提交空动作让服务端模型完成代打。
导出固定使用现有 opset 13 的 TorchScript exporter，当前 PyTorch 会报告弃用提示。

版本测试把计数器 v1 的每步 +1 升级成 v2 的每步 +10：进行中的旧 Session 仍然
每步 +1；删除内存中的 worker/注册项后，从 SQLite 找回旧包，重放终局与原局
一致。seed=0、原始 options 和旧版 observation 模式均保留。不存在的版本返回
409，下架游戏返回 404；缺少版本或 seed 的旧回放明确拒绝重建。

## 批处理测量

Linux 本机单进程测量，先检查逐条和批量路径的 state/obs 完全一致，再取 5 轮
耗时中位数。两条路径使用相同隔离执行器；逐条基线为每个环境 4 次 IPC
（验证 state、验证 action、step、obs），批量为整批 1 次。
不包含 HTTP、TLS、隧道、训练或多用户负载，不能作为线上容量承诺。

| 游戏 | 环境数 | 逐条 IPC / ms | 批量 IPC / ms | 提速 |
| --- | ---: | ---: | ---: | ---: |
| MicroRTS | 16 | 17.126 | 4.910 | 3.49× |
| MicroRTS | 256 | 297.274 | 87.665 | 3.39× |
| Snake | 16 | 14.339 | 3.844 | 3.73× |
| Snake | 256 | 248.939 | 68.232 | 3.65× |
| Tetris | 16 | 13.133 | 2.632 | 4.99× |
| Tetris | 256 | 222.035 | 45.417 | 4.89× |

[原始测量 JSON](reliability-benchmark.json)。版本元数据首次读取可能另有 info IPC；
批量游戏计算本身仍顺序执行。每请求最多 256 个环境，批量执行预算最高 5 秒。

## 全新环境验收

在同一宿主内核上新建独立源码目录、全新 Python venv、全新 node_modules 和空数据
目录。源码副本包含 GDK 示例夹具，不携带原来的 venv、构建目录或游戏数据库。

环境：Python 3.12.3；Linux x86_64 / WSL2 6.6.87.2；Landlock ABI 3；libseccomp2；
Node 22.22.0 / npm 11.18.0。新 venv 安装 backend requirements、dev requirements
和 editable SDK；CPU PyTorch 2.14.0、NumPy 2.3.2、Gymnasium 1.3.0、ONNX 1.17.0、
ONNX Runtime 1.20.1。

验收结果：

- 完整 pytest：`231 passed, 3 warnings in 71.73s`。三个提示来自 Starlette/AnyIO
  弃用别名及 TorchScript ONNX 导出，未隐藏或跳过测试。
- 前端 `npm ci` 安装 140 个包，`npm test` 2 项通过；Vite 生产构建通过。
- 未设置管理员，`/api/ready` 返回三个官方游戏；普通用户可注册和登录。
- 实际提供新构建的 SPA、JS、CSS 和 `/watch/match/1` 页面路由。
- 同一空库首次启动后重启，用户及游戏版本 ID/包路径不变；就绪检查继续通过。
- 测试服务通过 lifespan 关闭 worker 并退出，测试仅访问临时本地 HTTP 服务。

复现命令及本地启动方式见 [README](../../README.md#本地开发与验收)。核心检查：

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q
(cd web && npm ci && npm test && npm run build)
.venv/bin/python tests/benchmark_env_batch.py --output /tmp/batch-benchmark.json
```

## 验证边界与迁移

- 这是全新应用依赖/数据环境验收，仍使用现有宿主内核；未验证其他内核或 aarch64。
- 这轮 WSL 初验时没有可用 Docker engine；后续镜像构建、容器启动、线上部署和
  真实浏览器交互已在 [kr 验收记录](kr-deployment-validation.md) 中补齐。
- 未验证所有第三方 RL 框架，训练证据限定为上面的实际脚本和用例。
- Landlock 不隐藏所有文件元数据；运行库属于允许读取的可信范围。资源上限作用于
  单个 worker，未做整机多租户容量压测。
- 历史回放依赖原游戏包。备份/迁移应保留数据库及整个 `models/ugc/`；缺少历史包
  时返回错误，不切换成最新版本。缺少内核隔离支持时启动失败，不允许不安全回退。
