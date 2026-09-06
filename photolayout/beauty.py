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
from .config import BEAUTY_LEVELS, DEFAULT_BEAUTY_LEVEL_ID


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


def smooth_and_whiten_skin(image: Image.Image, mask: np.ndarray, intensity: float) -> Image.Image:
    """双边滤波磨皮 + LAB 空间 L 提升/b 降低美白，按蒙版强度混合。"""
    rgb = np.array(image.convert("RGB"))
    if intensity <= 0:
        return Image.fromarray(rgb, "RGB")

    smoothed = cv2.bilateralFilter(rgb, d=9, sigmaColor=45, sigmaSpace=45)
    lab = cv2.cvtColor(smoothed, cv2.COLOR_RGB2LAB).astype(np.float32)
    lab[:, :, 0] = np.clip(lab[:, :, 0] + 18.0 * intensity, 0, 255)
    lab[:, :, 2] = np.clip(lab[:, :, 2] - 6.0 * intensity, 0, 255)
    whitened = cv2.cvtColor(lab.astype(np.uint8), cv2.COLOR_LAB2RGB)

    blend = np.clip(mask * intensity, 0.0, 1.0)[:, :, None]
    result = rgb.astype(np.float32) * (1 - blend) + whitened.astype(np.float32) * blend
    return Image.fromarray(result.astype(np.uint8), "RGB")


def _ellipse_mask(shape: tuple[int, int], center: tuple[float, float],
                  axes: tuple[float, float], blur_sigma: float) -> np.ndarray:
    mask = np.zeros(shape, dtype=np.uint8)
    cv2.ellipse(
        mask, (int(center[0]), int(center[1])),
        (max(1, int(axes[0])), max(1, int(axes[1]))),
        0, 0, 360, 255, -1,
    )
    mask = cv2.GaussianBlur(mask, (0, 0), max(1.0, blur_sigma))
    return mask.astype(np.float32) / 255.0


def reduce_blemishes(image: Image.Image, landmarks: list[Point], intensity: float) -> Image.Image:
    """眼下区域局部提亮（黑眼圈）、两颊/鼻翼局部降红（泛红），色彩校正，不做结构性修复。"""
    rgb = np.array(image.convert("RGB"))
    if intensity <= 0:
        return Image.fromarray(rgb, "RGB")
    height, width = rgb.shape[:2]
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)

    dark_circle_mask = np.zeros((height, width), dtype=np.float32)
    for eye_indices in (LEFT_EYE, RIGHT_EYE):
        xs = [landmarks[i].x for i in eye_indices]
        ys = [landmarks[i].y for i in eye_indices]
        eye_w = max(xs) - min(xs)
        eye_h = max(ys) - min(ys)
        center = ((min(xs) + max(xs)) / 2.0, max(ys) + eye_h * 0.5)
        dark_circle_mask = np.maximum(
            dark_circle_mask,
            _ellipse_mask((height, width), center, (eye_w * 0.55, eye_h * 0.85), max(2.0, eye_w * 0.15)),
        )

    face_pts = [landmarks[i] for i in FACE_OVAL]
    face_width = max(p.x for p in face_pts) - min(p.x for p in face_pts)
    redness_mask = np.zeros((height, width), dtype=np.float32)
    left_eye_outer = landmarks[LEFT_EYE[0]]
    right_eye_outer = landmarks[RIGHT_EYE[0]]
    mouth_a = landmarks[LIPS_OUTER[0]]
    mouth_b = landmarks[LIPS_OUTER[10]]
    for eye_pt, mouth_pt in ((right_eye_outer, mouth_a), (left_eye_outer, mouth_b)):
        center = ((eye_pt.x + mouth_pt.x) / 2.0, (eye_pt.y + mouth_pt.y) / 2.0)
        radius = max(4.0, face_width * 0.12)
        redness_mask = np.maximum(
            redness_mask,
            _ellipse_mask((height, width), center, (radius, radius), radius * 0.5),
        )

    blend_dark = np.clip(dark_circle_mask * intensity, 0.0, 1.0)
    lab[:, :, 0] = np.clip(lab[:, :, 0] + blend_dark * 14.0, 0, 255)

    blend_red = np.clip(redness_mask * intensity, 0.0, 1.0)
    lab[:, :, 1] = np.clip(lab[:, :, 1] * (1 - blend_red * 0.5) + 128.0 * (blend_red * 0.5), 0, 255)

    corrected = cv2.cvtColor(lab.astype(np.uint8), cv2.COLOR_LAB2RGB)
    return Image.fromarray(corrected, "RGB")


def whiten_teeth(image: Image.Image, landmarks: list[Point], intensity: float) -> Image.Image:
    """嘴唇内轮廓关键点抠出牙齿区域，HSV 降饱和 + 提亮；嘴部闭合时跳过。"""
    rgb = np.array(image.convert("RGB"))
    if intensity <= 0:
        return Image.fromarray(rgb, "RGB")
    height, width = rgb.shape[:2]

    inner_pts = np.array([[landmarks[i].x, landmarks[i].y] for i in LIPS_INNER], dtype=np.int32)
    _, _, inner_w, inner_h = cv2.boundingRect(inner_pts)
    outer_pts = np.array([[landmarks[i].x, landmarks[i].y] for i in LIPS_OUTER], dtype=np.int32)
    _, _, _, outer_h = cv2.boundingRect(outer_pts)
    if outer_h <= 0 or inner_h < outer_h * 0.6:
        return Image.fromarray(rgb, "RGB")

    mouth_mask = np.zeros((height, width), dtype=np.uint8)
    cv2.fillConvexPoly(mouth_mask, cv2.convexHull(inner_pts), 255)
    mouth_mask = cv2.GaussianBlur(mouth_mask, (0, 0), max(1.0, inner_w * 0.05))
    blend = np.clip(mouth_mask.astype(np.float32) / 255.0 * intensity, 0.0, 1.0)

    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV).astype(np.float32)
    hsv[:, :, 1] = np.clip(hsv[:, :, 1] * (1 - blend * 0.5), 0, 255)
    hsv[:, :, 2] = np.clip(hsv[:, :, 2] + blend * 25.0, 0, 255)
    whitened = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2RGB)

    blend3 = blend[:, :, None]
    result = rgb.astype(np.float32) * (1 - blend3) + whitened.astype(np.float32) * blend3
    return Image.fromarray(result.astype(np.uint8), "RGB")


def _displacement_warp(rgb: np.ndarray, control_points: list[tuple[float, float]],
                       displacements: list[tuple[float, float]], sigma: float) -> np.ndarray:
    """按控制点位移量，使用高斯加权插值生成局部形变的图像。"""
    height, width = rgb.shape[:2]
    grid_x, grid_y = np.meshgrid(
        np.arange(width, dtype=np.float32), np.arange(height, dtype=np.float32)
    )
    total_dx = np.zeros((height, width), dtype=np.float32)
    total_dy = np.zeros((height, width), dtype=np.float32)
    for (cx, cy), (dx, dy) in zip(control_points, displacements):
        weight = np.exp(-((grid_x - cx) ** 2 + (grid_y - cy) ** 2) / (2 * sigma ** 2))
        total_dx += weight * dx
        total_dy += weight * dy

    map_x = (grid_x - total_dx).astype(np.float32)
    map_y = (grid_y - total_dy).astype(np.float32)
    return cv2.remap(rgb, map_x, map_y, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def slim_face(image: Image.Image, landmarks: list[Point], intensity: float) -> Image.Image:
    """基于下颌关键点位移场的局部 warp（cv2.remap），轻微像素级拉伸。"""
    rgb = np.array(image.convert("RGB"))
    if intensity <= 0:
        return Image.fromarray(rgb, "RGB")

    face_pts = [landmarks[i] for i in FACE_OVAL]
    face_width = max(p.x for p in face_pts) - min(p.x for p in face_pts)
    center_x = sum(p.x for p in face_pts) / len(face_pts)

    control_points = [(landmarks[i].x, landmarks[i].y) for i in JAW_INDICES]
    displacements = [((center_x - x) * 0.08 * intensity, 0.0) for x, _ in control_points]

    warped = _displacement_warp(rgb, control_points, displacements, sigma=max(4.0, face_width * 0.18))
    return Image.fromarray(warped, "RGB")


def enlarge_eyes(image: Image.Image, landmarks: list[Point], intensity: float) -> Image.Image:
    """基于眼周关键点的局部径向 warp（放大瞳孔周围区域）。"""
    rgb = np.array(image.convert("RGB"))
    if intensity <= 0:
        return Image.fromarray(rgb, "RGB")
    height, width = rgb.shape[:2]
    grid_x, grid_y = np.meshgrid(
        np.arange(width, dtype=np.float32), np.arange(height, dtype=np.float32)
    )
    map_x = grid_x.copy()
    map_y = grid_y.copy()

    for eye_indices in (LEFT_EYE, RIGHT_EYE):
        xs = [landmarks[i].x for i in eye_indices]
        ys = [landmarks[i].y for i in eye_indices]
        center_x = (min(xs) + max(xs)) / 2.0
        center_y = (min(ys) + max(ys)) / 2.0
        eye_radius = max(max(xs) - min(xs), max(ys) - min(ys)) / 2.0
        influence_radius = max(1.0, eye_radius * 2.2)

        dx = grid_x - center_x
        dy = grid_y - center_y
        dist = np.sqrt(dx ** 2 + dy ** 2)
        within = dist < influence_radius
        falloff = np.clip(1.0 - dist / influence_radius, 0.0, 1.0) ** 2
        strength = 0.35 * intensity * falloff
        scale = np.where(within, 1.0 / (1.0 + strength), 1.0)
        map_x = np.where(within, center_x + dx * scale, map_x)
        map_y = np.where(within, center_y + dy * scale, map_y)

    warped = cv2.remap(
        rgb, map_x.astype(np.float32), map_y.astype(np.float32),
        interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE,
    )
    return Image.fromarray(warped, "RGB")


def apply_beauty(image: Image.Image, level: int, enable_reshape: bool) -> tuple[Image.Image, list[str]]:
    """编排入口：检测一次关键点；失败则原样返回 + 告警。

    按顺序执行磨皮/美白/瑕疵柔化（intensity<=0 时整体跳过）；
    enable_reshape=True 时追加牙齿美白 + 瘦脸 + 大眼（复用同一强度值），
    并固定附带合规告警。
    """
    warnings: list[str] = []
    _, intensity = BEAUTY_LEVELS.get(level, BEAUTY_LEVELS[DEFAULT_BEAUTY_LEVEL_ID])
    if intensity <= 0 and not enable_reshape:
        return image, warnings

    original_mode = image.mode
    rgb_image = image.convert("RGB")
    rgb_array = np.array(rgb_image)
    height, width = rgb_array.shape[:2]

    mesh = detection.detect_face_mesh(rgb_array)
    if mesh is None:
        warnings.append("未检测到清晰人脸关键点，已跳过美颜处理")
        return image, warnings

    result = rgb_image
    if intensity > 0:
        mask = build_skin_mask(mesh, (height, width))
        result = smooth_and_whiten_skin(result, mask, intensity)
        result = reduce_blemishes(result, mesh, intensity)

    if enable_reshape:
        result = whiten_teeth(result, mesh, intensity)
        result = slim_face(result, mesh, intensity)
        result = enlarge_eyes(result, mesh, intensity)
        warnings.append(
            "已启用五官微调（瘦脸/大眼/牙齿美白），此类照片可能不符合护照/身份证等官方证件照"
            "『真实反映本人相貌』的要求，仅建议用于简历照等非官方场景。"
        )

    if original_mode == "RGBA":
        result = result.convert("RGBA")
        result.putalpha(image.getchannel("A"))
    return result, warnings
