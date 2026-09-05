"""rembg 抠图会话：进程内复用 + GPU/CPU 自动选择。

rembg 每次 ``remove()`` 都会重新加载模型（bria-rmbg 约 1GB，加载耗时数秒），
且其默认 provider 逻辑会把「装了 onnxruntime-gpu 但系统缺 CUDA/cuDNN 运行库」
的环境当成可用 GPU，导致每次运行都向 stderr 打印一串 provider 加载错误，
再回落 CPU 并追加 RuntimeWarning。

本模块把会话缓存为单例，并在真正构建会话时探测 provider 的实际可用性：
- 优先请求 CUDA（其次 ROCM / OpenVINO，沿用 rembg 的加速器优先级）；
- 构建后读取 ``session.get_providers()`` 判断加速器是否真的启用；
- 若未启用（运行库缺失等），静默回落到 CPU，只记一行 INFO，不再刷屏报错。
"""

from __future__ import annotations

import logging
import threading
import warnings

import onnxruntime as ort
from rembg import new_session
from rembg.sessions.base import BaseSession

from ._quiet import silence_stderr


logger = logging.getLogger(__name__)

# rembg 默认抠图模型（与 rembg.remove() 默认一致）
_MODEL_NAME = "bria-rmbg"

_session: BaseSession | None = None
_lock = threading.Lock()


def _preferred_providers() -> list[str]:
    """按 rembg 的加速器优先级返回候选 providers（加速器 + CPU 兜底）。"""
    available = ort.get_available_providers()
    providers: list[str] = []
    for name in (
        "CUDAExecutionProvider",
        "ROCMExecutionProvider",
        "OpenVINOExecutionProvider",
    ):
        if name in available:
            providers.append(name)
            break
    providers.append("CPUExecutionProvider")
    return providers


def _build_session() -> BaseSession:
    """构建并探测 rembg 会话；加速器不可用时由 onnxruntime 静默回落到 CPU。"""
    providers = _preferred_providers()
    # onnxruntime 加载 provider 失败时的 C++ 日志、rembg 的 RuntimeWarning
    # 都属于「预期内降级」噪音，静默掉，由下方的一行 INFO 统一说明。
    with silence_stderr():
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            session = new_session(
                _MODEL_NAME, sess_opts=ort.SessionOptions(), providers=providers
            )
    active = session.inner_session.get_providers()
    if active and active[0] != "CPUExecutionProvider":
        logger.info("rembg 抠图使用 GPU 加速（%s）", active[0])
    else:
        logger.info("未检测到可用的 GPU 运行库，rembg 抠图使用 CPU 推理")
    return session


def get_session() -> BaseSession:
    """返回进程级复用的 rembg 会话（首次调用时惰性构建）。"""
    global _session
    if _session is None:
        with _lock:
            if _session is None:
                _session = _build_session()
    return _session
