"""Pytest 会话级环境（13 G3）：先于一切测试模块导入。

- 统一临时 DB/MODELS_DIR；
- 预置管理员（ADMIN_USERNAME/PASSWORD）——main 导入时 bootstrap_admin()
  会创建/确保该账号，随后 seed_loader 自动播种 packaged-games/* 三个官方
  种子游戏并挂回注册表（与生产启动路径完全一致）。

各测试模块自身的 SCORES_DB/MODELS_DIR 设置在 conftest 之后运行，首个子进程
导入 main 的模块决定 ugc/models 等模块级常量，与旧行为兼容。
"""
import os
import tempfile
from pathlib import Path

_tmp = tempfile.TemporaryDirectory()
os.environ["SCORES_DB"] = str(Path(_tmp.name) / "scores.db")
os.environ["MODELS_DIR"] = str(Path(_tmp.name) / "models")
os.environ.setdefault("ADMIN_USERNAME", "seedadmin")
os.environ.setdefault("ADMIN_PASSWORD", "adminsecret1")
