# 证件照美颜与合规增强 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 PhotoLayout 新增一套证件照专用美颜处理（磨皮美白、瑕疵色彩柔化、可选五官微调），复用现有 MediaPipe `face_landmarker.task` 468 点模型，不引入新依赖，效果强度分档可调，五官微调默认关闭并在开启时附带合规告警。

**Architecture:** 新增 `photolayout/beauty.py` 领域模块，包含独立的纯函数（蒙版构建、磨皮美白、瑕疵柔化、牙齿美白、瘦脸、大眼、编排入口 `apply_beauty`）；`detection.py` 新增 `detect_face_mesh` 返回全部 468 点；`service.py` 的 `process_photo` 在裁剪之后、抠图之前插入 `apply_beauty` 调用；`cli.py`/`webui.py` 新增用户交互入口。所有关键点区域索引已通过项目实际安装的 MediaPipe 1.0.1（`mediapipe.tasks.python.vision.FaceLandmarksConnections`）提取验证，非记忆猜测。

**Tech Stack:** Python 3.11+、MediaPipe Tasks API（已有依赖）、OpenCV（`cv2.bilateralFilter`/`cv2.remap`/LAB & HSV 色彩空间转换）、Pillow、numpy、unittest（项目现有测试框架，非 pytest）。

**Spec:** `docs/superpowers/specs/2026-09-06-id-photo-beauty-design.md`

## Global Constraints

- 不引入新的第三方依赖（不用 dlib、不用人脸解析分割模型），只用项目已有的 MediaPipe `face_landmarker.task`。
- 五官微调（瘦脸/大眼/牙齿美白）默认关闭，需用户主动开启；开启时 `apply_beauty` 必须在返回的 warnings 中追加固定文案：
  "已启用五官微调（瘦脸/大眼/牙齿美白），此类照片可能不符合护照/身份证等官方证件照『真实反映本人相貌』的要求，仅建议用于简历照等非官方场景。"
- 不做基于 inpainting 的痘印/痣斑抹除式修复，只做色彩层面柔化。
- `apply_beauty` 及其内部所有函数不得抛异常影响成图流程；关键点检测失败时返回原图 + 告警 "未检测到清晰人脸关键点，已跳过美颜处理"。
- `BEAUTY_LEVELS` 强度档位：`{0: ("关闭", 0.0), 1: ("自然", 0.35), 2: ("标准", 0.65), 3: ("较强", 1.0)}`，默认档位 `DEFAULT_BEAUTY_LEVEL_ID = 1`。
- `apply_beauty` 在 `process_photo` 流水线中的位置：`detect_and_crop_face` 之后、`remove()`（rembg 抠图）之前。
- 测试使用项目现有的 `unittest` 风格（非 pytest），运行方式 `python -m unittest discover -s tests -v`。
- 实现完成后需手动启动 WebUI（`photolayout --web`）用真实照片验证三档强度 + 五官微调开关的实际效果。

---

## 已验证的关键点索引数据（供本计划所有任务直接使用，无需重新提取）

以下索引均从项目实际安装的 `mediapipe.tasks.python.vision.FaceLandmarksConnections`（`FACE_LANDMARKS_FACE_OVAL` / `_LEFT_EYE` / `_RIGHT_EYE` / `_LEFT_EYEBROW` / `_RIGHT_EYEBROW` / `_LIPS`）提取并转换为有序多边形环：

```python
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

# 下颌轮廓子集（从 FACE_OVAL 有序环中取以下巴 152 为中心的连续片段），用于 slim_face 位移场控制点
JAW_INDICES = [454, 323, 361, 288, 397, 365, 379, 378, 400, 377,
               152, 148, 176, 149, 150, 136, 172, 234]

# 鼻翼锚点（原始 NOSE 连接数据中验证存在的两个节点，用于两颊/鼻翼泛红 ROI 的几何锚点；
# 完整鼻部拓扑含分叉环，本设计不需要精确鼻孔多边形，故只取两个锚点）
NOSE_LEFT_WING = 64
NOSE_RIGHT_WING = 294
```

说明：
- `build_skin_mask` 使用 `FACE_OVAL` 外轮廓，减去 `LEFT_EYE`/`RIGHT_EYE`/`LEFT_EYEBROW`/`RIGHT_EYEBROW`/`LIPS_OUTER`（不减鼻孔——鼻部原始连接数据是带分叉的环状结构，精确抠出鼻孔多边形对磨皮安全性无实质收益，故简化省略）。
- `LEFT_EYEBROW`/`RIGHT_EYEBROW` 各自实际是两条独立弧线（上排+下排点）拼成的窄带，无需保持顺序即可用 `cv2.convexHull` 得到有效多边形。
- `LIPS_INNER` 是嘴唇内轮廓（牙齿/口腔可见区域边界），用于 `whiten_teeth`。
- 项目 `detection.py` 现有的 `LEFT_EYE_INDEX = 133` / `RIGHT_EYE_INDEX = 362` 是屏幕方向命名（与 MediaPipe 自身解剖学命名左右相反），本计划新代码一律使用 MediaPipe 自身的 `LEFT_EYE`/`RIGHT_EYE` 命名，两者不冲突（`detection.py` 现有代码不修改，只新增函数）。

---

## Task 1: `detection.py` 新增 `detect_face_mesh`

**Files:**
- Modify: `photolayout/detection.py`
- Test: `tests/test_detection.py`

**Interfaces:**
- Produces: `detect_face_mesh(rgb: np.ndarray) -> list[Point] | None`（`Point` 复用 `detection.py` 已有的 `NamedTuple`，返回 468 个像素坐标点；未检测到人脸或模型降级时返回 `None`）

- [ ] **Step 1: 阅读现有降级测试模式**

打开 `tests/test_detection.py`，确认现有测试如何通过 `mock.patch.dict(os.environ, {detection.OFFLINE_ENV: "1"})` + `detection.reset_state()` 模拟模型不可用（无需展示代码，直接沿用同一模式）。

- [ ] **Step 2: 编写失败测试**

在 `tests/test_detection.py` 末尾新增：

```python
def test_detect_face_mesh_returns_none_when_offline(self):
    detection.reset_state()
    with mock.patch.dict(os.environ, {detection.OFFLINE_ENV: "1"}):
        rgb = np.zeros((10, 10, 3), dtype=np.uint8)
        result = detection.detect_face_mesh(rgb)
    self.assertIsNone(result)
```

（若文件顶部尚未导入 `mock`/`os`/`np`，确认已有导入，本项目测试文件通常已导入；若缺失则按现有 import 风格补充 `from unittest import mock`、`import os`、`import numpy as np`。）

- [ ] **Step 3: 运行测试确认失败**

Run: `python -m unittest tests.test_detection -v`
Expected: FAIL，报 `AttributeError: module 'photolayout.detection' has no attribute 'detect_face_mesh'`

- [ ] **Step 4: 实现 `detect_face_mesh`**

在 `photolayout/detection.py` 的 `detect_eye_line` 函数之后新增：

```python
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
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m unittest tests.test_detection -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add photolayout/detection.py tests/test_detection.py
git commit -m "feat: add detect_face_mesh for 468-point face landmarks"
```

---

## Task 2: `beauty.py` 骨架 + `build_skin_mask`

**Files:**
- Create: `photolayout/beauty.py`
- Test: `tests/test_beauty.py`

**Interfaces:**
- Consumes: `detection.Point`（`NamedTuple(x: float, y: float)`，来自 `photolayout/detection.py`）
- Produces:
  - 模块级常量 `FACE_OVAL`, `LEFT_EYE`, `RIGHT_EYE`, `LEFT_EYEBROW`, `RIGHT_EYEBROW`, `LIPS_OUTER`, `LIPS_INNER`, `JAW_INDICES`, `NOSE_LEFT_WING`, `NOSE_RIGHT_WING`（数值同本计划开头"已验证的关键点索引数据"章节）
  - `build_skin_mask(landmarks: list[Point], shape: tuple[int, int]) -> np.ndarray`（返回 `float32`，取值范围 `[0, 1]`，形状与 `shape` 一致的 `(height, width)` 蒙版）
  - 测试辅助函数 `_make_face_landmarks(width: int, height: int) -> list[Point]`（供本任务及后续所有 `beauty.py` 测试任务共用，构造 468 点合成假关键点）

- [ ] **Step 1: 编写测试辅助 fixture 与失败测试**

创建 `tests/test_beauty.py`：

```python
import unittest

import numpy as np
from PIL import Image

from photolayout import beauty
from photolayout.detection import Point


def _make_face_landmarks(width: int, height: int) -> list[Point]:
    """构造 468 点合成假关键点：脸部椭圆轮廓 + 双眼/双眉/双唇的简单几何布局。

    未显式赋值的索引一律填充图像中心点（对本模块所有函数均无影响，
    因为每个函数只读取自己关心的固定索引集合）。
    """
    center_x, center_y = width / 2.0, height / 2.0
    points = [Point(center_x, center_y) for _ in range(468)]

    face_rx, face_ry = width * 0.32, height * 0.42
    for i, idx in enumerate(beauty.FACE_OVAL):
        angle = 2 * np.pi * i / len(beauty.FACE_OVAL)
        points[idx] = Point(
            center_x + face_rx * np.sin(angle),
            center_y - face_ry * np.cos(angle),
        )

    def _ellipse_ring(indices, cx, cy, rx, ry):
        for i, idx in enumerate(indices):
            angle = 2 * np.pi * i / len(indices)
            points[idx] = Point(cx + rx * np.cos(angle), cy + ry * np.sin(angle))

    eye_y = center_y - height * 0.06
    _ellipse_ring(beauty.LEFT_EYE, center_x + width * 0.13, eye_y, width * 0.045, height * 0.02)
    _ellipse_ring(beauty.RIGHT_EYE, center_x - width * 0.13, eye_y, width * 0.045, height * 0.02)

    brow_y = eye_y - height * 0.05
    _ellipse_ring(beauty.LEFT_EYEBROW, center_x + width * 0.13, brow_y, width * 0.05, height * 0.012)
    _ellipse_ring(beauty.RIGHT_EYEBROW, center_x - width * 0.13, brow_y, width * 0.05, height * 0.012)

    mouth_y = center_y + height * 0.18
    _ellipse_ring(beauty.LIPS_OUTER, center_x, mouth_y, width * 0.09, height * 0.035)
    _ellipse_ring(beauty.LIPS_INNER, center_x, mouth_y, width * 0.06, height * 0.018)

    points[beauty.NOSE_LEFT_WING] = Point(center_x + width * 0.03, center_y + height * 0.05)
    points[beauty.NOSE_RIGHT_WING] = Point(center_x - width * 0.03, center_y + height * 0.05)
    return points


class BuildSkinMaskTests(unittest.TestCase):
    def test_forehead_is_included_eye_is_excluded(self):
        width, height = 200, 260
        landmarks = _make_face_landmarks(width, height)
        mask = beauty.build_skin_mask(landmarks, (height, width))

        self.assertEqual(mask.shape, (height, width))
        self.assertEqual(mask.dtype, np.float32)

        forehead_x, forehead_y = int(width / 2), int(height * 0.28)
        self.assertGreater(mask[forehead_y, forehead_x], 0.5)

        eye_x = int(width / 2 + width * 0.13)
        eye_y = int(height / 2 - height * 0.06)
        self.assertLess(mask[eye_y, eye_x], 0.5)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m unittest tests.test_beauty -v`
Expected: FAIL，报 `ModuleNotFoundError` 或 `AttributeError`（`photolayout.beauty` 尚不存在）

- [ ] **Step 3: 创建 `photolayout/beauty.py` 并实现常量 + `build_skin_mask`**

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m unittest tests.test_beauty -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add photolayout/beauty.py tests/test_beauty.py
git commit -m "feat: add beauty module skeleton with build_skin_mask"
```

---

## Task 3: `smooth_and_whiten_skin`

**Files:**
- Modify: `photolayout/beauty.py`
- Test: `tests/test_beauty.py`

**Interfaces:**
- Consumes: `build_skin_mask` 输出的 `np.ndarray` 蒙版（Task 2）
- Produces: `smooth_and_whiten_skin(image: Image.Image, mask: np.ndarray, intensity: float) -> Image.Image`

- [ ] **Step 1: 编写失败测试**

在 `tests/test_beauty.py` 新增：

```python
class SmoothAndWhitenSkinTests(unittest.TestCase):
    def test_zero_intensity_is_identity(self):
        width, height = 60, 80
        rgb = np.random.default_rng(0).integers(0, 255, (height, width, 3), dtype=np.uint8)
        image = Image.fromarray(rgb, "RGB")
        mask = np.ones((height, width), dtype=np.float32)

        result = beauty.smooth_and_whiten_skin(image, mask, 0.0)

        np.testing.assert_array_equal(np.array(result), rgb)

    def test_positive_intensity_brightens_masked_region(self):
        width, height = 60, 80
        rgb = np.full((height, width, 3), 120, dtype=np.uint8)
        image = Image.fromarray(rgb, "RGB")
        mask = np.ones((height, width), dtype=np.float32)

        result = np.array(beauty.smooth_and_whiten_skin(image, mask, 1.0))

        self.assertGreater(result.mean(), rgb.mean())
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m unittest tests.test_beauty -v`
Expected: FAIL，报 `AttributeError: module 'photolayout.beauty' has no attribute 'smooth_and_whiten_skin'`

- [ ] **Step 3: 实现 `smooth_and_whiten_skin`**

在 `photolayout/beauty.py` 追加：

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m unittest tests.test_beauty -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add photolayout/beauty.py tests/test_beauty.py
git commit -m "feat: add smooth_and_whiten_skin"
```

---

## Task 4: `reduce_blemishes`

**Files:**
- Modify: `photolayout/beauty.py`
- Test: `tests/test_beauty.py`

**Interfaces:**
- Consumes: `LEFT_EYE`, `RIGHT_EYE`, `LIPS_OUTER`, `FACE_OVAL`（Task 2 已定义常量）
- Produces: `reduce_blemishes(image: Image.Image, landmarks: list[Point], intensity: float) -> Image.Image`；内部辅助 `_ellipse_mask(shape, center, axes, blur_sigma) -> np.ndarray`

- [ ] **Step 1: 编写失败测试**

```python
class ReduceBlemishesTests(unittest.TestCase):
    def test_zero_intensity_is_identity(self):
        width, height = 200, 260
        rgb = np.random.default_rng(1).integers(0, 255, (height, width, 3), dtype=np.uint8)
        image = Image.fromarray(rgb, "RGB")
        landmarks = _make_face_landmarks(width, height)

        result = beauty.reduce_blemishes(image, landmarks, 0.0)

        np.testing.assert_array_equal(np.array(result), rgb)

    def test_positive_intensity_changes_image(self):
        width, height = 200, 260
        rgb = np.full((height, width, 3), 150, dtype=np.uint8)
        image = Image.fromarray(rgb, "RGB")
        landmarks = _make_face_landmarks(width, height)

        result = np.array(beauty.reduce_blemishes(image, landmarks, 1.0))

        self.assertFalse(np.array_equal(result, rgb))
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m unittest tests.test_beauty -v`
Expected: FAIL，报 `AttributeError: module 'photolayout.beauty' has no attribute 'reduce_blemishes'`

- [ ] **Step 3: 实现 `_ellipse_mask` 与 `reduce_blemishes`**

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m unittest tests.test_beauty -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add photolayout/beauty.py tests/test_beauty.py
git commit -m "feat: add reduce_blemishes"
```

---

## Task 5: `whiten_teeth`

**Files:**
- Modify: `photolayout/beauty.py`
- Test: `tests/test_beauty.py`

**Interfaces:**
- Consumes: `LIPS_INNER`, `LIPS_OUTER`（Task 2 常量）
- Produces: `whiten_teeth(image: Image.Image, landmarks: list[Point], intensity: float) -> Image.Image`

- [ ] **Step 1: 编写失败测试**

```python
class WhitenTeethTests(unittest.TestCase):
    def test_zero_intensity_is_identity(self):
        width, height = 200, 260
        rgb = np.random.default_rng(2).integers(0, 255, (height, width, 3), dtype=np.uint8)
        image = Image.fromarray(rgb, "RGB")
        landmarks = _make_face_landmarks(width, height)

        result = beauty.whiten_teeth(image, landmarks, 0.0)

        np.testing.assert_array_equal(np.array(result), rgb)

    def test_closed_mouth_is_skipped(self):
        width, height = 200, 260
        rgb = np.full((height, width, 3), 150, dtype=np.uint8)
        image = Image.fromarray(rgb, "RGB")
        landmarks = _make_face_landmarks(width, height)
        # 用 fixture 里嘴唇内外轮廓比例（inner 高度 0.018 << outer 高度 0.035）天然模拟"闭嘴"

        result = beauty.whiten_teeth(image, landmarks, 1.0)

        np.testing.assert_array_equal(np.array(result), rgb)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m unittest tests.test_beauty -v`
Expected: FAIL，报 `AttributeError: module 'photolayout.beauty' has no attribute 'whiten_teeth'`

- [ ] **Step 3: 实现 `whiten_teeth`**

```python
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
    if outer_h <= 0 or inner_h < outer_h * 0.18:
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m unittest tests.test_beauty -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add photolayout/beauty.py tests/test_beauty.py
git commit -m "feat: add whiten_teeth"
```

---

## Task 6: `slim_face`

**Files:**
- Modify: `photolayout/beauty.py`
- Test: `tests/test_beauty.py`

**Interfaces:**
- Consumes: `FACE_OVAL`, `JAW_INDICES`（Task 2 常量）
- Produces:
  - `_displacement_warp(rgb: np.ndarray, control_points: list[tuple[float, float]], displacements: list[tuple[float, float]], sigma: float) -> np.ndarray`（共享辅助，Task 6/7 均使用；本任务实现，Task 7 直接复用）
  - `slim_face(image: Image.Image, landmarks: list[Point], intensity: float) -> Image.Image`

- [ ] **Step 1: 编写失败测试**

```python
class SlimFaceTests(unittest.TestCase):
    def test_zero_intensity_is_identity(self):
        width, height = 200, 260
        rgb = np.random.default_rng(3).integers(0, 255, (height, width, 3), dtype=np.uint8)
        image = Image.fromarray(rgb, "RGB")
        landmarks = _make_face_landmarks(width, height)

        result = beauty.slim_face(image, landmarks, 0.0)

        np.testing.assert_array_equal(np.array(result), rgb)

    def test_positive_intensity_changes_image(self):
        width, height = 200, 260
        rng = np.random.default_rng(4)
        rgb = rng.integers(0, 255, (height, width, 3), dtype=np.uint8)
        image = Image.fromarray(rgb, "RGB")
        landmarks = _make_face_landmarks(width, height)

        result = np.array(beauty.slim_face(image, landmarks, 1.0))

        self.assertFalse(np.array_equal(result, rgb))
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m unittest tests.test_beauty -v`
Expected: FAIL，报 `AttributeError: module 'photolayout.beauty' has no attribute 'slim_face'`

- [ ] **Step 3: 实现 `_displacement_warp` 与 `slim_face`**

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m unittest tests.test_beauty -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add photolayout/beauty.py tests/test_beauty.py
git commit -m "feat: add slim_face"
```

---

## Task 7: `enlarge_eyes`

**Files:**
- Modify: `photolayout/beauty.py`
- Test: `tests/test_beauty.py`

**Interfaces:**
- Consumes: `LEFT_EYE`, `RIGHT_EYE`（Task 2 常量）
- Produces: `enlarge_eyes(image: Image.Image, landmarks: list[Point], intensity: float) -> Image.Image`

- [ ] **Step 1: 编写失败测试**

```python
class EnlargeEyesTests(unittest.TestCase):
    def test_zero_intensity_is_identity(self):
        width, height = 200, 260
        rgb = np.random.default_rng(5).integers(0, 255, (height, width, 3), dtype=np.uint8)
        image = Image.fromarray(rgb, "RGB")
        landmarks = _make_face_landmarks(width, height)

        result = beauty.enlarge_eyes(image, landmarks, 0.0)

        np.testing.assert_array_equal(np.array(result), rgb)

    def test_positive_intensity_changes_image(self):
        width, height = 200, 260
        rng = np.random.default_rng(6)
        rgb = rng.integers(0, 255, (height, width, 3), dtype=np.uint8)
        image = Image.fromarray(rgb, "RGB")
        landmarks = _make_face_landmarks(width, height)

        result = np.array(beauty.enlarge_eyes(image, landmarks, 1.0))

        self.assertFalse(np.array_equal(result, rgb))
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m unittest tests.test_beauty -v`
Expected: FAIL，报 `AttributeError: module 'photolayout.beauty' has no attribute 'enlarge_eyes'`

- [ ] **Step 3: 实现 `enlarge_eyes`**

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m unittest tests.test_beauty -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add photolayout/beauty.py tests/test_beauty.py
git commit -m "feat: add enlarge_eyes"
```

---

## Task 8: `config.py` 强度档位 + `apply_beauty` 编排入口

**Files:**
- Modify: `photolayout/config.py`
- Modify: `photolayout/beauty.py`
- Test: `tests/test_beauty.py`

**Interfaces:**
- Consumes: `detection.detect_face_mesh`（Task 1）、`build_skin_mask`/`smooth_and_whiten_skin`/`reduce_blemishes`/`whiten_teeth`/`slim_face`/`enlarge_eyes`（Task 2–7）
- Produces:
  - `photolayout.config.BEAUTY_LEVELS: dict[int, tuple[str, float]]`
  - `photolayout.config.DEFAULT_BEAUTY_LEVEL_ID: int`
  - `apply_beauty(image: Image.Image, level: int, enable_reshape: bool) -> tuple[Image.Image, list[str]]`

- [ ] **Step 1: 在 `config.py` 新增强度档位常量**

打开 `photolayout/config.py`，在文件末尾追加：

```python
BEAUTY_LEVELS: dict[int, tuple[str, float]] = {
    0: ("关闭", 0.0),
    1: ("自然", 0.35),
    2: ("标准", 0.65),
    3: ("较强", 1.0),
}
DEFAULT_BEAUTY_LEVEL_ID = 1
```

- [ ] **Step 2: 编写失败测试**

在 `tests/test_beauty.py` 新增（需要 `from unittest import mock`）：

```python
class ApplyBeautyTests(unittest.TestCase):
    def test_level_zero_no_reshape_returns_original_without_detection(self):
        width, height = 200, 260
        rgb = np.random.default_rng(7).integers(0, 255, (height, width, 3), dtype=np.uint8)
        image = Image.fromarray(rgb, "RGB")

        with mock.patch.object(beauty.detection, "detect_face_mesh") as mocked:
            result, warnings = beauty.apply_beauty(image, 0, False)

        mocked.assert_not_called()
        np.testing.assert_array_equal(np.array(result), rgb)
        self.assertEqual(warnings, [])

    def test_mesh_none_returns_original_with_warning(self):
        width, height = 200, 260
        rgb = np.full((height, width, 3), 130, dtype=np.uint8)
        image = Image.fromarray(rgb, "RGB")

        with mock.patch.object(beauty.detection, "detect_face_mesh", return_value=None):
            result, warnings = beauty.apply_beauty(image, 1, False)

        np.testing.assert_array_equal(np.array(result.convert("RGB")), rgb)
        self.assertEqual(warnings, ["未检测到清晰人脸关键点，已跳过美颜处理"])

    def test_enable_reshape_appends_compliance_warning(self):
        width, height = 200, 260
        rgb = np.full((height, width, 3), 130, dtype=np.uint8)
        image = Image.fromarray(rgb, "RGB")
        landmarks = _make_face_landmarks(width, height)

        with mock.patch.object(beauty.detection, "detect_face_mesh", return_value=landmarks):
            _, warnings = beauty.apply_beauty(image, 1, True)

        self.assertIn(
            "已启用五官微调（瘦脸/大眼/牙齿美白），此类照片可能不符合护照/身份证等官方证件照"
            "『真实反映本人相貌』的要求，仅建议用于简历照等非官方场景。",
            warnings,
        )

    def test_rgba_input_preserves_alpha(self):
        width, height = 200, 260
        rgb = np.full((height, width, 3), 130, dtype=np.uint8)
        alpha = np.full((height, width, 1), 200, dtype=np.uint8)
        rgba = np.concatenate([rgb, alpha], axis=2)
        image = Image.fromarray(rgba, "RGBA")
        landmarks = _make_face_landmarks(width, height)

        with mock.patch.object(beauty.detection, "detect_face_mesh", return_value=landmarks):
            result, _ = beauty.apply_beauty(image, 1, False)

        self.assertEqual(result.mode, "RGBA")
        np.testing.assert_array_equal(np.array(result.getchannel("A")), alpha[:, :, 0])
```

- [ ] **Step 2b: 运行测试确认失败**

Run: `python -m unittest tests.test_beauty -v`
Expected: FAIL，报 `AttributeError: module 'photolayout.beauty' has no attribute 'apply_beauty'`

- [ ] **Step 3: 实现 `apply_beauty`**

在 `photolayout/beauty.py` 顶部导入区确认已有 `from .config import BEAUTY_LEVELS, DEFAULT_BEAUTY_LEVEL_ID`（新增此行），文件末尾追加：

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m unittest tests.test_beauty -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add photolayout/config.py photolayout/beauty.py tests/test_beauty.py
git commit -m "feat: add BEAUTY_LEVELS config and apply_beauty orchestrator"
```

---

## Task 9: `service.py` 接入 `apply_beauty`

**Files:**
- Modify: `photolayout/service.py`
- Test: `tests/test_service.py`（新增文件——项目当前没有 `test_service.py`，本任务创建）

**Interfaces:**
- Consumes: `beauty.apply_beauty(image, level, enable_reshape) -> tuple[Image.Image, list[str]]`（Task 8）
- Produces: 修改后的 `process_photo(input_path, photo_size, background_color=(255,255,255), brightness=1.05, contrast=1.08, beauty_level: int = DEFAULT_BEAUTY_LEVEL_ID, enable_facial_reshape: bool = False) -> PhotoResult`

- [ ] **Step 1: 编写失败测试**

创建 `tests/test_service.py`：

```python
import unittest
from unittest import mock

from PIL import Image

from photolayout import service
from photolayout.config import DEFAULT_BEAUTY_LEVEL_ID


class ProcessPhotoBeautyWiringTests(unittest.TestCase):
    def test_apply_beauty_called_between_crop_and_remove(self):
        call_order = []

        def fake_detect_and_crop_face(image, *args, **kwargs):
            call_order.append("crop")
            return image

        def fake_apply_beauty(image, level, enable_reshape):
            call_order.append("beauty")
            self.assertEqual(level, DEFAULT_BEAUTY_LEVEL_ID)
            self.assertFalse(enable_reshape)
            return image, []

        def fake_remove(image, **kwargs):
            call_order.append("remove")
            return image

        image = Image.new("RGBA", (10, 10), (255, 255, 255, 255))
        photo_size = mock.Mock(aspect_ratio=0.75, expand_top=0.7, expand_bottom=0.5, expand_side=0.32)

        with mock.patch.object(service, "straighten_portrait", side_effect=lambda img: img), \
             mock.patch.object(service, "detect_and_crop_face", side_effect=fake_detect_and_crop_face), \
             mock.patch.object(service.beauty, "apply_beauty", side_effect=fake_apply_beauty), \
             mock.patch.object(service, "remove", side_effect=fake_remove), \
             mock.patch.object(service, "trim_body_below_shoulders", side_effect=lambda subj, ref: subj), \
             mock.patch.object(service, "widen_shoulder_band", side_effect=lambda subj, ref, *a, **k: (subj, None)), \
             mock.patch.object(service, "enhance_portrait", side_effect=lambda img: img), \
             mock.patch.object(service.Image, "open", return_value=image):
            service.process_photo("fake.jpg", photo_size)

        self.assertEqual(call_order, ["crop", "beauty", "remove"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m unittest tests.test_service -v`
Expected: FAIL（`service` 模块尚无 `beauty` 属性，或调用顺序不含 `"beauty"`）

- [ ] **Step 3: 修改 `photolayout/service.py`**

在文件顶部 import 区（`from . import detection` 之后）新增：

```python
from . import beauty
```

修改 `from .config import MAX_SHOULDER_STRETCH, MIN_SHOULDER_WIDTH_RATIO` 为：

```python
from .config import DEFAULT_BEAUTY_LEVEL_ID, MAX_SHOULDER_STRETCH, MIN_SHOULDER_WIDTH_RATIO
```

修改 `process_photo` 函数签名与函数体：

```python
def process_photo(input_path: str | Path, photo_size: PhotoSize,
                  background_color: tuple[int, int, int] = (255, 255, 255),
                  brightness: float = 1.05, contrast: float = 1.08,
                  beauty_level: int = DEFAULT_BEAUTY_LEVEL_ID,
                  enable_facial_reshape: bool = False) -> PhotoResult:
    """生成指定尺寸和背景色的单张证件照，返回照片与提示信息。"""
    warnings: list[str] = []
    image = Image.open(input_path).convert("RGBA")
    image = straighten_portrait(image)
    reason = detection.unavailable_reason()
    if reason:
        warnings.append(
            "AI 构图功能不可用：" + reason + "。将按整图处理输出，头部占比可能不合规；"
            "请联网后重试，或参照 README「常见问题」手动放置模型后再次运行。"
        )
    logger.info("正在进行人脸识别与智能裁剪（根据尺寸微调头部占比）...")
    image = detect_and_crop_face(
        image, photo_size.aspect_ratio, photo_size.expand_top,
        photo_size.expand_bottom, photo_size.expand_side,
        warnings=warnings,
    )
    logger.info("正在进行美颜处理...")
    image, beauty_warnings = beauty.apply_beauty(image, beauty_level, enable_facial_reshape)
    warnings.extend(beauty_warnings)
    logger.info("正在去除背景...")
    foreground = remove(
        image, session=get_session(), alpha_matting=True,
        alpha_matting_foreground_threshold=240,
        alpha_matting_background_threshold=10, alpha_matting_erode_size=3,
        decontaminate=True,
    )
    foreground = trim_body_below_shoulders(foreground, image)
    foreground, widen_warning = widen_shoulder_band(
        foreground, image, MIN_SHOULDER_WIDTH_RATIO, MAX_SHOULDER_STRETCH
    )
    if widen_warning:
        warnings.append(widen_warning)
    background = Image.new("RGBA", foreground.size, background_color + (255,))
    result = Image.alpha_composite(background, foreground).convert("RGB")
    result = enhance_portrait(result)
    result = ImageEnhance.Brightness(result).enhance(brightness)
    result = ImageEnhance.Contrast(result).enhance(contrast)
    return PhotoResult(result, warnings)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m unittest tests.test_service -v`
Expected: PASS

- [ ] **Step 5: 回归运行完整测试套件**

Run: `python -m unittest discover -s tests -v`
Expected: 全部 PASS（确认未破坏现有 `test_layout.py`/`test_portrait_fill.py`/`test_detection.py`/`test_rembg_session.py`）

- [ ] **Step 6: 提交**

```bash
git add photolayout/service.py tests/test_service.py
git commit -m "feat: wire apply_beauty into process_photo pipeline"
```

---

## Task 10: `cli.py` 新增美颜菜单

**Files:**
- Modify: `photolayout/cli.py`

**Interfaces:**
- Consumes: `config.BEAUTY_LEVELS`, `config.DEFAULT_BEAUTY_LEVEL_ID`（Task 8）；`service.process_photo(..., beauty_level, enable_facial_reshape)`（Task 9）
- Produces: CLI 交互流程新增两个菜单，最终把 `beauty_level`/`enable_facial_reshape` 传给 `process_photo`

- [ ] **Step 1: 阅读现有 `cli.py` 菜单实现**

```bash
grep -n "choose_from_menu\|background_color\|process_photo" photolayout/cli.py
```

确认 `choose_from_menu` 的函数签名（参数名、返回值类型）与背景色选择菜单调用处的确切代码，供下一步精确插入。

- [ ] **Step 2: 在背景色选择之后、相纸尺寸选择之前插入美颜菜单**

在 `photolayout/cli.py` 顶部 import 区，找到 `from .config import ...` 一行，将 `BEAUTY_LEVELS, DEFAULT_BEAUTY_LEVEL_ID` 加入导入列表。

在背景颜色选择菜单调用之后、相纸尺寸选择菜单调用之前，插入：

```python
beauty_choice = choose_from_menu(
    "请选择美颜强度：",
    {k: v[0] for k, v in BEAUTY_LEVELS.items()},
    default=DEFAULT_BEAUTY_LEVEL_ID,
)
reshape_choice = choose_from_menu(
    "是否开启五官微调（瘦脸/大眼/牙齿美白）？",
    {1: "否（默认，推荐用于官方证件照）", 2: "是（仅建议非官方场景，如简历照）"},
    default=1,
)
enable_reshape = reshape_choice == 2
```

（`choose_from_menu` 的确切参数名以 Step 1 读取到的现有函数签名为准，保持与背景色菜单调用完全一致的调用风格；若签名与本步骤示例不同，按实际签名调整参数顺序/名称，逻辑不变。）

找到调用 `service.process_photo(...)` 的位置，在参数列表中追加：

```python
beauty_level=beauty_choice,
enable_facial_reshape=enable_reshape,
```

- [ ] **Step 3: 静态检查确认无语法错误**

Run: `python -c "import photolayout.cli"`
Expected: 无异常（若原本 `cli.py` 顶层有阻塞式菜单代码导致 import 即触发交互，改为 `python -m py_compile photolayout/cli.py` 代替）

- [ ] **Step 4: 手动运行 CLI 确认菜单出现**

Run: `python main.py`，用任意一张测试图片走完整流程，确认新增的两个菜单在背景色之后、相纸尺寸之前出现，直接回车选择默认值也能正常生成照片。

- [ ] **Step 5: 提交**

```bash
git add photolayout/cli.py
git commit -m "feat: add beauty level and facial reshape menus to CLI"
```

---

## Task 11: `webui.py` 新增美颜控件

**Files:**
- Modify: `photolayout/webui.py`

**Interfaces:**
- Consumes: `config.BEAUTY_LEVELS`, `config.DEFAULT_BEAUTY_LEVEL_ID`（Task 8）；`service.process_photo(..., beauty_level, enable_facial_reshape)`（Task 9）
- Produces: WebUI 新增美颜强度下拉框 + 五官微调复选框，`generate()` 签名扩展并透传给 `process_photo`

- [ ] **Step 1: 阅读现有 `webui.py` 结构**

```bash
grep -n "bg_dd\|def generate\|run_btn.click\|gr.Dropdown\|gr.Checkbox" photolayout/webui.py
```

确认 `bg_dd`（背景色下拉框）组件定义处的确切代码风格、`generate()` 函数当前完整签名、`run_btn.click(...)` 的 `inputs=[...]` 列表当前内容，供下一步精确插入。

- [ ] **Step 2: 新增下拉框与复选框组件**

在 `bg_dd` 组件定义之后插入：

```python
beauty_dd = gr.Dropdown(
    label="美颜强度",
    choices=[v[0] for v in BEAUTY_LEVELS.values()],
    value=BEAUTY_LEVELS[DEFAULT_BEAUTY_LEVEL_ID][0],
)
reshape_cb = gr.Checkbox(
    label="五官微调（瘦脸/大眼/牙齿美白）",
    value=False,
    info="⚠️ 可能不符合官方证件照真实性要求，仅建议非官方场景使用",
)
```

在 `photolayout/webui.py` 顶部 import 区，找到 `from .config import ...` 一行，将 `BEAUTY_LEVELS, DEFAULT_BEAUTY_LEVEL_ID` 加入导入列表。

- [ ] **Step 3: 扩展 `generate()` 签名并透传参数**

修改 `generate()` 函数签名，新增 `beauty_label: str, enable_reshape: bool` 两个参数（追加在现有参数列表末尾）。在函数体内、调用 `service.process_photo(...)` 之前插入：

```python
beauty_level = next(
    (k for k, v in BEAUTY_LEVELS.items() if v[0] == beauty_label),
    DEFAULT_BEAUTY_LEVEL_ID,
)
```

在 `service.process_photo(...)` 调用的参数列表中追加：

```python
beauty_level=beauty_level,
enable_facial_reshape=enable_reshape,
```

- [ ] **Step 4: 更新 `run_btn.click` 的 `inputs` 列表**

找到 `run_btn.click(generate, inputs=[...], outputs=[...])`，在 `inputs` 列表中追加 `beauty_dd, reshape_cb`（顺序需与 `generate()` 新增的两个形参顺序一致）。

- [ ] **Step 5: 静态检查**

Run: `python -m py_compile photolayout/webui.py`
Expected: 无异常

- [ ] **Step 6: 启动 WebUI 手动验证**

Run: `photolayout --web`

在浏览器中：
1. 上传一张真实人像照片
2. 依次测试美颜强度「关闭」「自然」「标准」「较强」四档，观察磨皮/美白/瑕疵柔化效果是否自然、有无"塑料脸"
3. 分别在关闭和开启「五官微调」的情况下生成，确认开启后结果页出现合规告警文案
4. 检查瘦脸/大眼/牙齿美白效果有无明显 warp 边缘瑕疵或误伤嘴唇轮廓

记录发现的问题；若 `BEAUTY_LEVELS` 强度数值需要调整，回到 Task 8 的 `config.py` 修改并重新提交（不新增任务，直接修正）。

- [ ] **Step 7: 提交**

```bash
git add photolayout/webui.py
git commit -m "feat: add beauty level and facial reshape controls to WebUI"
```

---

## Task 12: 更新 README

**Files:**
- Modify: `README.md`

**Interfaces:**
- 无代码接口，仅文档同步

- [ ] **Step 1: 更新功能特性表格**

在 README「✨ 功能特性」表格中新增一行：

```markdown
| 💄 **证件照专用美颜** | 肤色磨皮美白 + 瑕疵色彩柔化（默认开启，三档强度可调）；可选五官微调（瘦脸/大眼/牙齿美白，默认关闭，开启时附合规提示） |
```

- [ ] **Step 2: 更新使用流程说明**

在「📖 使用流程」的步骤 4（背景颜色选择）之后插入新步骤，并将后续步骤编号顺延：

```markdown
5. 按菜单选择美颜强度（关闭 / 自然 / 标准 / 较强，默认自然）
6. 按菜单选择是否开启五官微调（默认否，开启仅建议非官方场景使用）
```

- [ ] **Step 3: 更新项目结构说明**

在「📁 项目结构」代码块的 `photolayout/` 部分，`portrait.py` 一行之后新增：

```text
  beauty.py             证件照专用美颜：磨皮美白、瑕疵色彩柔化、可选五官微调
```

在 `tests/` 部分新增：

```text
  test_beauty.py         美颜处理纯函数单测（无模型依赖）
  test_service.py        process_photo 流水线编排单测
```

- [ ] **Step 4: 更新路线图**

在「🗺️ 路线图」的「规划中 🚧」列表中，将 `- [ ] 正装换衣、美颜优化` 改为：

```markdown
- [x] 美颜优化（磨皮美白、瑕疵柔化、可选五官微调）
- [ ] 正装换衣
```

并移动到「已完成 ✅」列表末尾。

- [ ] **Step 5: 提交**

```bash
git add README.md
git commit -m "docs: document beauty feature in README"
```

---

## 自查清单（供实施者参考，非必须步骤）

- 每个 `beauty.py` 函数在 `intensity <= 0` 时必须原样返回（已在每个实现中通过提前 `return` 保证，避免色彩空间往返转换引入的量化误差破坏幂等性）。
- `apply_beauty` 是唯一调用 `detection.detect_face_mesh` 的地方；`level=0` 且 `enable_facial_reshape=False` 时完全跳过检测（性能优化，也避免无意义的告警噪音）。
- `service.process_photo` 新增的两个参数均有默认值，保持向后兼容——任何未修改的既有调用方（若存在）无需改动即可正常工作。
