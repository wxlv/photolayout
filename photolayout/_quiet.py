"""进程级 stderr 静默工具。

MediaPipe / ONNX Runtime 等第三方 C++ 组件会在初始化或推理时直接向 stderr
写 INFO/WARNING 日志（无法用 Python logging 或环境变量关闭），在终端刷屏。
本模块提供 fd 级重定向把这些调用静默掉；内部锁保证多线程下重定向不互相干扰。
"""

import contextlib
import os
import threading
from collections.abc import Iterator

_stderr_lock = threading.RLock()


@contextlib.contextmanager
def silence_stderr() -> Iterator[None]:
    """将进程 stderr 临时指向空设备，静默第三方 C++ 日志。"""
    with _stderr_lock:
        saved_fd = os.dup(2)
        devnull_fd = os.open(os.devnull, os.O_WRONLY)
        try:
            os.dup2(devnull_fd, 2)
            yield
        finally:
            os.dup2(saved_fd, 2)
            os.close(devnull_fd)
            os.close(saved_fd)
