"""排版模块的行为测试。"""

import unittest

from PIL import Image

from photolayout.config import (
    DEFAULT_PAPER_SIZE_ID,
    DEFAULT_PHOTO_SIZE_ID,
    PAPER_SIZES,
    PHOTO_SIZES,
)
from photolayout.layout import layout_on_paper, mm_to_px, resize_to_size


def paper_size_mm(paper_id: int) -> tuple[int, int]:
    paper = PAPER_SIZES[paper_id]
    return paper.width_mm, paper.height_mm


class LayoutTests(unittest.TestCase):
    def test_resize_to_size_uses_requested_pixel_dimensions(self) -> None:
        image = Image.new("RGB", (300, 200), "white")

        resized = resize_to_size(image, 25, 35)

        self.assertEqual(resized.size, (mm_to_px(25), mm_to_px(35)))

    def test_layout_returns_positions_within_paper(self) -> None:
        image = Image.new("RGB", (300, 420), "white")
        size_mm = paper_size_mm(DEFAULT_PAPER_SIZE_ID)

        paper, positions = layout_on_paper(image, 25, 35, size_mm)

        self.assertTrue(positions)
        self.assertEqual(paper.size, tuple(mm_to_px(value) for value in size_mm))
        for left, top, right, bottom in positions:
            self.assertGreaterEqual(left, 0)
            self.assertGreaterEqual(top, 0)
            self.assertLessEqual(right, paper.width)
            self.assertLessEqual(bottom, paper.height)

    def test_layout_positions_within_each_paper_size(self) -> None:
        image = Image.new("RGB", (300, 420), "white")

        for paper_id, paper_size in PAPER_SIZES.items():
            size_mm = (paper_size.width_mm, paper_size.height_mm)
            with self.subTest(paper=paper_size.name):
                paper, positions = layout_on_paper(image, 25, 35, size_mm)

                self.assertTrue(positions)
                self.assertEqual(paper.size, tuple(mm_to_px(value) for value in size_mm))
                for left, top, right, bottom in positions:
                    self.assertGreaterEqual(left, 0)
                    self.assertGreaterEqual(top, 0)
                    self.assertLessEqual(right, paper.width)
                    self.assertLessEqual(bottom, paper.height)

    def test_larger_paper_fits_more_photos(self) -> None:
        image = Image.new("RGB", (300, 420), "white")

        _, positions_5inch = layout_on_paper(image, 25, 35, paper_size_mm(1))
        a4_id = next(key for key, size in PAPER_SIZES.items() if size.name == "A4")
        _, positions_a4 = layout_on_paper(image, 25, 35, paper_size_mm(a4_id))

        self.assertGreater(len(positions_a4), len(positions_5inch))

    def test_default_ids_match_expected_presets(self) -> None:
        self.assertEqual(PHOTO_SIZES[DEFAULT_PHOTO_SIZE_ID].name, "标准一寸")
        self.assertEqual(PAPER_SIZES[DEFAULT_PAPER_SIZE_ID].name, "6寸")


if __name__ == "__main__":
    unittest.main()