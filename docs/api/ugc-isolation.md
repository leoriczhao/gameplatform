# UGC 执行隔离

所有官方包、用户上传、上传时冒烟、运行中会话和历史版本均通过 `GameWorker`。
worker 使用隔离的 Python 启动参数和新的最小环境变量集合，不继承管理员密码、
JWT 密钥位置、代理或 Python 搜索路径。父进程只保留 stdin/stdout 管道。

在加入游戏包导入路径前，`ugc_sandbox.install` 必须成功安装两层内核限制：

- Landlock ABI ≥ 3：处理 ABI 3 的全部文件操作权限，仅授予游戏包、Python 标准库、
  NumPy 和必要运行库的只读权限。平台数据库、密钥、其他游戏包不在允许范围内。
- libseccomp：默认拒绝系统调用，仅允许计算、受 Landlock 限制的读取、内存管理和
  管道通信所需调用。网络、创建/执行进程、跨进程信号和内存访问、文件权限修改、
  namespace/mount、io_uring 及文件描述符控制不在白名单内。

这保证的是禁止未经授权的内容访问和修改；Landlock 不隐藏路径是否存在等所有元数据。
Python open/socket 等替换保留以提供友好错误，不承担不可绕过的安全边界。
不会因缺少内核支持或动态库而回退到仅 Python 限制。

NumPy 在可信初始化阶段以单线程加载；安装限制前检查实际线程数。资源上限为
2 GiB 虚拟地址空间、累计 60 秒 CPU、64 个描述符；禁止文件写入和创建子进程。
单条 IPC 请求/响应最多 16 MiB；单请求 200 ms，内部批处理总预算最高 5 秒。
这是沙箱内部资源限制，不是公开环境 API 的批量能力；当前环境交互仅走
[OpenEnv 会话](openenv.md)，一条 WS 连接一个实例，不提供单 HTTP 批量推进。
写管道也计入请求超时，避免游戏不读 stdin 导致 API 一直阻塞。

冒烟结束直接停止创建的 worker。正式 worker 按 `(game_id, package_path)` 分池，
空闲 10 分钟由生命周期清理线程回收，服务退出时关闭全部池中 worker。

## 验证

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q \
  tests/test_ugc_isolation.py tests/test_ugc_runner.py tests/test_seed_packages.py
```

回归覆盖已复现的允许模块间接访问文件接口，以及写文件、chmod、底层 socket、
posix_spawn、描述符控制、环境凭据泄露和缺少隔离支持时的加载顺序。
正向用例覆盖包内资源、多文件官方游戏、NumPy、确定性、超时和进程回收。

部署需要 Linux x86_64/aarch64、启用 Landlock ABI ≥ 3 的内核、`libseccomp.so.2`。
Docker 镜像安装运行库，沿用容器原有安全选项；宿主内核及外层策略还必须允许
安装 Landlock/seccomp。部署前用 `/api/ready` 验证，禁止通过关闭隔离绕过启动失败。

实现依据：[Linux Landlock 文档](https://docs.kernel.org/userspace-api/landlock.html)、
[libseccomp 规则 API](https://github.com/seccomp/libseccomp/blob/main/doc/man/man3/seccomp_rule_add.3)。
