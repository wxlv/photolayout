"""基于 MediaPipe Tasks API 的人脸/姿态检测适配层。

旧版 mediapipe 的 ``mp.solutions``（FaceMesh / FaceDetection / Pose）只在
``<=0.10.21`` 的编译版 wheel 中提供；新版（0.10.30+ 与 1.x 的纯 py3 wheel）
已移除该接口，只保留 ``mp.tasks``。本模块把 portrait 需要的三类检测
（人脸框 / 双眼连线 / 双肩关键点）收敛为若干纯函数：

- 模型文件首次使用时自动下载到缓存目录（默认 ``~/.photolayout/models``），
  可通过环境变量 :envvar:`PHOTOLAYOUT_MODELS_DIR` 覆盖；
- 模型缺失、下载失败或组件初始化失败时，将当前进程标记为“降级”并记录原因，
  后续检测调用直接返回空结果（不重复联网），由上层通过
  :func:`unavailable_reason` 向用户告警；
- 检测函数本身绝不抛异常影响成图流程。
"""

from __future__ import annotations

import logging
import os
import shutil
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

import numpy as np
from mediapipe import Image as MpImage
from mediapipe import ImageFormat
from mediapipe.tasks import python as mp_tasks
from mediapipe.tasks.python import vision

from ._quiet import silence_stderr


logger = logging.getLogger(__name__)

# 模型缓存目录（可用 PHOTOLAYOUT_MODELS_DIR 覆盖）
DEFAULT_MODELS_DIR = Path.home() / ".photolayout" / "models"
MODELS_DIR_ENV = "PHOTOLAYOUT_MODELS_DIR"
# 设为任意值可禁止自动联网下载（用于离线环境或测试模拟降级）
OFFLINE_ENV = "PHOTOLAYOUT_OFFLINE"

FACE_DETECTOR_MODEL = "blaze_face_full_range.tflite"
FACE_LANDMARKER_MODEL = "face_landmarker.task"
POSE_LANDMARKER_MODEL = "pose_landmarker_full.task"

_MODEL_BASE_URL = "https://storage.googleapis.com/mediapipe-models"
_MODEL_URLS = {
    FACE_DETECTOR_MODEL: (
        f"{_MODEL_BASE_URL}/face_detector/blaze_face_full_range/float16/latest/"
        f"{FACE_DETECTOR_MODEL}"
    ),
    FACE_LANDMARKER_MODEL: (
        f"{_MODEL_BASE_URL}/face_landmarker/face_landmarker/float16/latest/"
        f"{FACE_LANDMARKER_MODEL}"
    ),
    POSE_LANDMARKER_MODEL: (
        f"{_MODEL_BASE_URL}/pose_landmarker/pose_landmarker_full/float16/latest/"
        f"{POSE_LANDMARKER_MODEL}"
    ),
}

# 匹配旧版 mp.solutions 行为的关键点索引：
# - FaceLandmarker 前 468 点与旧 FaceMesh 拓扑一致，眼点取 133 / 362；
# - PoseLandmarker 33 点中左右肩为 11 / 12。
LEFT_EYE_INDEX = 133
RIGHT_EYE_INDEX = 362
LEFT_SHOULDER = vision.PoseLandmark.LEFT_SHOULDER
RIGHT_SHOULDER = vision.PoseLandmark.RIGHT_SHOULDER

# 下载超时（秒）。大模型约 10MB，局域网/移动网络需要留足余量。
_DOWNLOAD_TIMEOUT = 60

_ready: bool | None = None  # None=尚未检查；True=模型就绪；False=已降级
_reason: str | None = None  # 降级原因（供上层向用户告警）


class Point(NamedTuple):
    """图像平面内像素坐标点（可解包为 ``(x, y)``）。"""

    x: float
    y: float


@dataclass(frozen=True)
class FaceBox:
    """人脸检测框（像素坐标，左上角为原点）。"""

    x: int
    y: int
    width: int
    height: int
    score: float


def model_dir() -> Path:
    """返回模型缓存目录。"""
    override = os.environ.get(MODELS_DIR_ENV)
    return Path(override).expanduser() if override else DEFAULT_MODELS_DIR


def reset_state() -> None:
    """清空进程级检测状态（主要供测试使用）。"""
    global _ready, _reason
    _ready = None
    _reason = None


def unavailable_reason() -> str | None:
    """返回降级原因（仅查询，不触发模型检查/下载）。

    原因在首次检测尝试后才会产生；尚未触发检测或模型就绪时返回 None。
    """
    return _reason


def is_available() -> bool:
    """返回检测组件当前是否可用（会触发首次模型检查）。"""
    if _ready is None:
        _ensure_ready()
    return _ready is True


def _set_unavailable(reason: str) -> None:
    global _ready, _reason
    _ready = False
    _reason = reason
    logger.warning("人脸/姿态检测降级：%s", reason)


def _ensure_ready() -> bool:
    """确保所需模型文件就绪，首次调用触发下载；之后按进程记忆结果。"""
    global _ready
    if _ready is not None:
        return _ready
    models_dir = model_dir()
    missing = [name for name in _MODEL_URLS if not (models_dir / name).is_file()]
    if missing:
        if os.environ.get(OFFLINE_ENV):
            _set_unavailable("模型未缓存且环境变量 PHOTOLAYOUT_OFFLINE 禁止自动下载")
            return False
        try:
            models_dir.mkdir(parents=True, exist_ok=True)
            for name in missing:
                _download(_MODEL_URLS[name], models_dir / name)
        except Exception as exc:  # 网络、权限、磁盘等任何原因均降级而非崩溃
            _set_unavailable(f"AI 模型下载失败：{exc}")
            return False
    _ready = True
    logger.info("AI 模型就绪：%s", models_dir)
    return True


def _download(url: str, dest: Path) -> None:
    """下载 url 到 dest，先写 .part 再原子改名，避免留下半截文件。"""
    part = dest.with_name(dest.name + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "photolayout"})
    try:
        with urllib.request.urlopen(request, timeout=_DOWNLOAD_TIMEOUT) as response:
            with part.open("wb") as handle:
                shutil.copyfileobj(response, handle)
        os.replace(part, dest)
    except Exception:
        part.unlink(missing_ok=True)
        raise


def _to_image(rgb: np.ndarray) -> MpImage:
    return MpImage(image_format=ImageFormat.SRGB, data=np.ascontiguousarray(rgb))


def _open_detector(name: str, build) -> object | None:
    """按模型名创建检测器；模型缺失或初始化失败时降级并返回 None。"""
    if not _ensure_ready():
        return None
    model_path = model_dir() / name
    try:
        with silence_stderr():
            return build(str(model_path))
    except Exception as exc:  # 模型损坏 / API 不兼容等
        _set_unavailable(f"AI 组件初始化失败（{name}）：{exc}")
        return None


def detect_faces(rgb: np.ndarray) -> list[FaceBox]:
    """检测所有人脸，返回像素坐标人脸框（含置信度），按置信度降序。"""
    detector = _open_detector(
        FACE_DETECTOR_MODEL,
        lambda path: vision.FaceDetector.create_from_options(
            vision.FaceDetectorOptions(
                base_options=mp_tasks.BaseOptions(model_asset_path=path),
                min_detection_confidence=0.5,
            )
        ),
    )
    if detector is None:
        return []
    try:
        with silence_stderr():
            result = detector.detect(_to_image(rgb))
    except Exception as exc:
        logger.warning("人脸检测失败：%s", exc)
        return []
    finally:
        with silence_stderr():
            detector.close()

    faces = []
    for detection in result.detections:
        box = detection.bounding_box
        score = float(detection.categories[0].score) if detection.categories else 0.0
        faces.append(FaceBox(box.origin_x, box.origin_y, box.width, box.height, score))
    faces.sort(key=lambda face: face.score, reverse=True)
    return faces


def detect_eye_line(rgb: np.ndarray) -> tuple[Point, Point] | None:
    """检测双眼外角像素坐标，用于人像扶正；未检测到清晰人脸时返回 None。"""
    landmarker = _open_detector(
        FACE_LANDMARKER_MODEL,
        lambda path: vision.FaceLandmarker.create_from_options(
            vision.FaceLandmarkerOptions(
                base_options=mp_tasks.BaseOptions(model_asset_path=path),
                num_faces=1,
                min_face_detection_confidence=0.5,
            )
        ),
    )
    if landmarker is None:
        return None
    try:
        with silence_stderr():
            result = landmarker.detect(_to_image(rgb))
            if not result.face_landmarks:
                return None
            points = result.face_landmarks[0]
            left = points[LEFT_EYE_INDEX]
            right = points[RIGHT_EYE_INDEX]
            height, width = rgb.shape[:2]
            return (
                Point(left.x * width, left.y * height),
                Point(right.x * width, right.y * height),
            )
    except Exception as exc:
        logger.warning("面部关键点检测失败：%s", exc)
        return None
    finally:
        with silence_stderr():
            landmarker.close()


def detect_face_mesh(rgb: np.ndarray) -> list[Point] | None:
    """返回 468 点全脸网格像素坐标；未检测到人脸或降级时返回 None。"""
    landmarker = _open_detector(
        FACE_LANDMARKER_MODEL,
        lambda path: vision.FaceLandmarker.create_from_options(
            vision.FaceLandmarkerOptions(
                base_options=mp_tasks.BaseOptions(model_asset_path=path),
                num_faces=1,
                min_face_detection_confidence=0.5,
            )
        ),
    )
    if landmarker is None:
        return None
    try:
        with silence_stderr():
            result = landmarker.detect(_to_image(rgb))
            if not result.face_landmarks:
                return None
            points = result.face_landmarks[0]
            height, width = rgb.shape[:2]
            return [Point(p.x * width, p.y * height) for p in points]
    except Exception as exc:
        logger.warning("面部关键点检测失败：%s", exc)
        return None
    finally:
        with silence_stderr():
            landmarker.close()


def detect_shoulders(rgb: np.ndarray) -> tuple[Point, Point] | None:
    """检测双肩像素坐标（左右肩可见度均达标）；否则返回 None。"""
    landmarker = _open_detector(
        POSE_LANDMARKER_MODEL,
        lambda path: vision.PoseLandmarker.create_from_options(
            vision.PoseLandmarkerOptions(
                base_options=mp_tasks.BaseOptions(model_asset_path=path),
                num_poses=1,
                min_pose_detection_confidence=0.5,
                min_pose_presence_confidence=0.5,
            )
        ),
    )
    if landmarker is None:
        return None
    try:
        with silence_stderr():
            result = landmarker.detect(_to_image(rgb))
            if not result.pose_landmarks:
                return None
            landmarks = result.pose_landmarks[0]
            left = landmarks[LEFT_SHOULDER]
            right = landmarks[RIGHT_SHOULDER]
            if left.visibility < 0.5 or right.visibility < 0.5:
                return None
            height, width = rgb.shape[:2]
            return (
                Point(left.x * width, left.y * height),
                Point(right.x * width, right.y * height),
            )
    except Exception as exc:
        logger.warning("姿态关键点检测失败：%s", exc)
        return None
    finally:
        with silence_stderr():
            landmarker.close()
