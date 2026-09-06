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


if __name__ == "__main__":
    unittest.main()
