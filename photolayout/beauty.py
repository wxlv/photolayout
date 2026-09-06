"""证件照专用美颜处理：肤色磨皮美白、瑕疵色彩柔化、可选五官微调。

所有关键点区域索引来自 MediaPipe ``face_landmarker.task``（468 点全脸网格），
索引取值经 ``mediapipe.tasks.python.vision.FaceLandmarksConnections`` 校验。
"""

from __future__ import annotations

import logging

import cv2
import numpy as np
from PIL import Image

from . import detection
from .detection import Point


logger = logging.getLogger(__name__)

FACE_OVAL = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365,
             379, 378, 400, 377, 152, 148, 176, 149, 150, 136, 172, 58, 132, 93,
             234, 127, 162, 21, 54, 103, 67, 109]

LEFT_EYE = [263, 249, 390, 373, 374, 380, 381, 382, 362, 398, 384, 385, 386, 387, 388, 466]
RIGHT_EYE = [33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246]

LEFT_EYEBROW = [276, 283, 282, 295, 285, 300, 293, 334, 296, 336]
RIGHT_EYEBROW = [46, 53, 52, 65, 55, 70, 63, 105, 66, 107]

LIPS_OUTER = [61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291, 409, 270, 269,
              267, 0, 37, 39, 40, 185]
LIPS_INNER = [78, 95, 88, 178, 87, 14, 317, 402, 318, 324, 308, 415, 310, 311,
              312, 13, 82, 81, 80, 191]

JAW_INDICES = [454, 323, 361, 288, 397, 365, 379, 378, 400, 377,
               152, 148, 176, 149, 150, 136, 172, 234]

NOSE_LEFT_WING = 64
NOSE_RIGHT_WING = 294


def _hull_from_indices(landmarks: list[Point], indices: list[int]) -> np.ndarray:
    pts = np.array([[landmarks[i].x, landmarks[i].y] for i in indices], dtype=np.int32)
    return cv2.convexHull(pts)


def build_skin_mask(landmarks: list[Point], shape: tuple[int, int]) -> np.ndarray:
    """人脸轮廓减去眼/眉/唇区域，得到纯肤色区域的浮点权重蒙版（0..1）。"""
    height, width = shape
    face_mask = np.zeros((height, width), dtype=np.uint8)
    cv2.fillConvexPoly(face_mask, _hull_from_indices(landmarks, FACE_OVAL), 255)

    exclude_mask = np.zeros((height, width), dtype=np.uint8)
    for indices in (LEFT_EYE, RIGHT_EYE, LEFT_EYEBROW, RIGHT_EYEBROW, LIPS_OUTER):
        cv2.fillConvexPoly(exclude_mask, _hull_from_indices(landmarks, indices), 255)

    skin_mask = cv2.bitwise_and(face_mask, cv2.bitwise_not(exclude_mask))
    skin_mask = cv2.GaussianBlur(skin_mask, (0, 0), max(2.0, width * 0.01))
    return skin_mask.astype(np.float32) / 255.0
