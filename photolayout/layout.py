"""证件照尺寸缩放、相纸排版和 PDF 导出。"""

import logging
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from .config import DPI, GAP_MM, MARGIN_MM


logger = logging.getLogger(__name__)


def mm_to_px(value_mm: float, dpi: int = DPI) -> int:
    """按 DPI 将毫米转换为像素。"""
    return int(value_mm / 25.4 * dpi)


def resize_to_size(image: Image.Image, width_mm: int, height_mm: int,
                   dpi: int = DPI) -> Image.Image:
    """按指定物理尺寸等比例缩放并居中裁切。"""
    target_width = mm_to_px(width_mm, dpi)
    target_height = mm_to_px(height_mm, dpi)
    image_ratio = image.width / image.height
    target_ratio = target_width / target_height
    if image_ratio > target_ratio:
        resized_height = target_height
        resized_width = int(resized_height * image_ratio)
    else:
        resized_width = target_width
        resized_height = int(resized_width / image_ratio)

    resized = image.resize((resized_width, resized_height), Image.LANCZOS)
    left = (resized_width - target_width) // 2
    top = (resized_height - target_height) // 2
    return resized.crop((left, top, left + target_width, top + target_height))


def layout_on_paper(image: Image.Image, width_mm: int, height_mm: int,
                    paper_size_mm: tuple[int, int],
                    draw_cut_lines: bool = True) -> tuple[Image.Image, list[tuple[int, int, int, int]]]:
    """将照片以最大张数排版到指定相纸，可选绘制切割线。"""
    photo = resize_to_size(image, width_mm, height_mm)
    paper_width = mm_to_px(paper_size_mm[0])
    paper_height = mm_to_px(paper_size_mm[1])
    gap = mm_to_px(GAP_MM)
    margin = mm_to_px(MARGIN_MM)
    usable_width = paper_width - 2 * margin
    usable_height = paper_height - 2 * margin

    candidates = []
    for orientation, candidate in (("纵向", photo), ("横向", photo.rotate(90, expand=True))):
        columns = (usable_width + gap) // (candidate.width + gap)
        rows = (usable_height + gap) // (candidate.height + gap)
        used_area = (columns * candidate.width + max(0, columns - 1) * gap) * (
            rows * candidate.height + max(0, rows - 1) * gap
        )
        candidates.append((columns * rows, used_area, orientation, candidate, columns, rows))

    copy_count, _, orientation, photo, columns, rows = max(
        candidates, key=lambda candidate: (candidate[0], candidate[1])
    )
    logger.info(
        "%s×%smm 相纸最佳排版（%s）：%s列 × %s行 = %s 张",
        paper_size_mm[0], paper_size_mm[1], orientation, columns, rows, copy_count,
    )
    paper = Image.new("RGB", (paper_width, paper_height), (255, 255, 255))
    total_width = columns * photo.width + (columns - 1) * gap
    total_height = rows * photo.height + (rows - 1) * gap
    start_x = margin + (usable_width - total_width) // 2
    start_y = margin + (usable_height - total_height) // 2
    positions = _paste_photos(paper, photo, columns, rows, start_x, start_y, gap)
    if draw_cut_lines:
        _draw_cut_lines(paper, positions, gap)
    return paper, positions


def _paste_photos(paper: Image.Image, photo: Image.Image, columns: int, rows: int,
                  start_x: int, start_y: int, gap: int) -> list[tuple[int, int, int, int]]:
    positions = []
    for row in range(rows):
        for column in range(columns):
            x = start_x + column * (photo.width + gap)
            y = start_y + row * (photo.height + gap)
            paper.paste(photo, (x, y))
            positions.append((x, y, x + photo.width, y + photo.height))
    return positions


def _draw_cut_lines(paper: Image.Image, positions: list[tuple[int, int, int, int]], gap: int) -> None:
    """在每张照片四周间隙中绘制灰色点状切割线。"""
    draw = ImageDraw.Draw(paper)
    offset = min(mm_to_px(1), gap // 3)
    dot_radius = 1
    dot_spacing = mm_to_px(2)

    def draw_dotted_line(start: tuple[int, int], end: tuple[int, int]) -> None:
        x1, y1 = start
        x2, y2 = end
        length = int(np.hypot(x2 - x1, y2 - y1))
        for distance in range(0, length + 1, dot_spacing):
            ratio = distance / length
            x = x1 + (x2 - x1) * ratio
            y = y1 + (y2 - y1) * ratio
            draw.ellipse((x - dot_radius, y - dot_radius, x + dot_radius, y + dot_radius), fill=(185, 185, 185))

    for x1, y1, x2, y2 in positions:
        left, top, right, bottom = x1 - offset, y1 - offset, x2 + offset, y2 + offset
        draw_dotted_line((left, top), (right, top))
        draw_dotted_line((right, top), (right, bottom))
        draw_dotted_line((right, bottom), (left, bottom))
        draw_dotted_line((left, bottom), (left, top))


def save_pdf_with_cut_lines(paper_image: Image.Image, output_path: str | Path,
                            paper_size_mm: tuple[int, int]) -> None:
    """将排版图导出为真实物理尺寸的 PDF。"""
    width_pt, height_pt = paper_size_mm[0] * mm, paper_size_mm[1] * mm
    pdf = canvas.Canvas(str(output_path), pagesize=(width_pt, height_pt))
    image_buffer = BytesIO()
    paper_image.save(image_buffer, format="PNG")
    image_buffer.seek(0)
    pdf.drawImage(ImageReader(image_buffer), 0, 0, width=width_pt, height=height_pt)
    pdf.save()
    logger.info("带切割线的PDF已保存：%s", output_path)