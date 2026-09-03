"""排版模块的行为测试。"""

import unittest

from PIL import Image

from photolayout.config import PAPER_SIZE_MM
from photolayout.layout import layout_on_paper, mm_to_px, resize_to_size


class LayoutTests(unittest.TestCase):
    def test_resize_to_size_uses_requested_pixel_dimensions(self) -> None:
        image = Image.new("RGB", (300, 200), "white")

        resized = resize_to_size(image, 25, 35)

        self.assertEqual(resized.size, (mm_to_px(25), mm_to_px(35)))

    def test_layout_returns_positions_within_paper(self) -> None:
        image = Image.new("RGB", (300, 420), "white")

        paper, positions = layout_on_paper(image, 25, 35)

        self.assertTrue(positions)
        self.assertEqual(paper.size, tuple(mm_to_px(value) for value in PAPER_SIZE_MM))
        for left, top, right, bottom in positions:
            self.assertGreaterEqual(left, 0)
            self.assertGreaterEqual(top, 0)
            self.assertLessEqual(right, paper.width)
            self.assertLessEqual(bottom, paper.height)


if __name__ == "__main__":
    unittest.main()