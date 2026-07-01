"""Pytest 配置：把 xhs 根目录加入 sys.path。

xhs 内部用的是 `from config.settings import ...` / `from core.cookies import ...`
这种“以 xhs 为根”的绝对导入，因此测试运行前需要把 xhs 目录放到 sys.path 上，
这样无论从仓库根目录还是 xhs 目录执行 pytest 都能正常 import。
"""
import os
import sys

XHS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if XHS_ROOT not in sys.path:
    sys.path.insert(0, XHS_ROOT)
