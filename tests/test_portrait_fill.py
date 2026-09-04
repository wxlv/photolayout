"""构图自检与肩部补全相关纯函数的测试（无模型依赖）。"""

import unittest

import numpy as np
from PIL import Image

from photolayout.portrait import (
    check_headroom,
    measure_band_width_ratio,
    stretch_band,
)


def make_rgba_with_band(width: int, height: int, band_left: int,
                        band_right: int, split_y: int) -> Image.Image:
    """构造 RGBA 假图：全图不透明，split_y 以下仅 [band_left, band_right) 有内容。"""
    image = Image.new("RGBA", (width, height), (10, 20, 30, 255))
    alpha = np.full((height, width), 255, dtype=np.uint8)
    alpha[split_y:, :] = 0
    alpha[split_y:, band_left:band_right] = 255
    image.putalpha(Image.fromarray(alpha))
    return image


class HeadroomTests(unittest.TestCase):
    def test_headroom_sufficient(self) -> None:
        self.assertTrue(check_headroom(face_y=100, face_height=100, expand_top=0.7))

    def test_headroom_at_exact_boundary(self) -> None:
        self.assertTrue(check_headroom(face_y=70, face_height=100, expand_top=0.7))

    def test_headroom_insufficient(self) -> None:
        self.assertFalse(check_headroom(face_y=69, face_height=100, expand_top=0.7))

    def test_headroom_face_at_top_edge(self) -> None:
        self.assertFalse(check_headroom(face_y=0, face_height=100, expand_top=0.7))


class MeasureBandWidthRatioTests(unittest.TestCase):
    def test_full_width_band(self) -> None:
        alpha = np.full((100, 100), 255, dtype=np.uint8)
        self.assertAlmostEqual(measure_band_width_ratio(alpha, 50), 1.0)

    def test_narrow_band(self) -> None:
        alpha = np.zeros((100, 100), dtype=np.uint8)
        alpha[50:, 40:60] = 255
        self.assertAlmostEqual(measure_band_width_ratio(alpha, 50), 0.2)

    def test_empty_band_returns_zero(self) -> None:
        alpha = np.zeros((100, 100), dtype=np.uint8)
        self.assertEqual(measure_band_width_ratio(alpha, 50), 0.0)

    def test_split_beyond_image_returns_zero(self) -> None:
        alpha = np.full((100, 100), 255, dtype=np.uint8)
        self.assertEqual(measure_band_width_ratio(alpha, 100), 0.0)

    def test_band_above_split_ignored(self) -> None:
        alpha = np.full((100, 100), 255, dtype=np.uint8)
        alpha[50:, :] = 0
        alpha[50:, 45:55] = 255
        self.assertAlmostEqual(measure_band_width_ratio(alpha, 50), 0.1)


class StretchBandTests(unittest.TestCase):
    def test_factor_one_is_identity(self) -> None:
        image = make_rgba_with_band(100, 100, 40, 60, 50)
        result = stretch_band(image, 50, 1.0)
        np.testing.assert_array_equal(np.array(result), np.array(image))

    def test_head_region_unchanged(self) -> None:
        image = make_rgba_with_band(100, 100, 40, 60, 50)
        result = stretch_band(image, 50, 1.3)
        head_original = np.array(image.crop((0, 0, 100, 50)))
        head_result = np.array(result.crop((0, 0, 100, 50)))
        np.testing.assert_array_equal(head_original, head_result)

    def test_band_gets_wider_and_centered(self) -> None:
        image = make_rgba_with_band(100, 100, 40, 60, 50)
        result = stretch_band(image, 50, 1.5)
        ratio = measure_band_width_ratio(np.array(result.getchannel("A")), 50)
        self.assertGreater(ratio, 0.25)

    def test_output_size_and_split_unchanged(self) -> None:
        image = make_rgba_with_band(100, 100, 40, 60, 50)
        result = stretch_band(image, 50, 1.35)
        self.assertEqual(result.size, (100, 100))
        # split 行以上无内容变化，以下 alpha 仍存在
        self.assertGreater(np.array(result.getchannel("A"))[50:].max(), 0)

    def test_split_beyond_height_is_identity(self) -> None:
        image = make_rgba_with_band(100, 100, 40, 60, 50)
        result = stretch_band(image, 100, 1.3)
        np.testing.assert_array_equal(np.array(result), np.array(image))

    def test_oversized_factor_clipped_to_image_width(self) -> None:
        image = make_rgba_with_band(100, 100, 40, 60, 50)
        result = stretch_band(image, 50, 5.0)
        self.assertEqual(result.size, (100, 100))
        ratio = measure_band_width_ratio(np.array(result.getchannel("A")), 50)
        self.assertAlmostEqual(ratio, 1.0)


if __name__ == "__main__":
    unittest.main()
