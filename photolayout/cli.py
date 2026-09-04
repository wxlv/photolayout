"""命令行交互入口。"""

import logging
import re
from datetime import datetime
from pathlib import Path

from .config import (
    BACKGROUND_COLORS,
    DEFAULT_PAPER_SIZE_ID,
    DEFAULT_PHOTO_SIZE_ID,
    DPI,
    OUTPUT_ROOT_DIR,
    PAPER_SIZES,
    PHOTO_SIZES,
    TIMESTAMP_FORMAT,
)
from .layout import layout_on_paper, save_pdf_with_cut_lines
from .models import PaperSize, PhotoSize
from .service import process_photo


def choose_from_menu(title: str, options: dict[int, object], default: int | None = None) -> int:
    """显示编号菜单并返回有效选项，提供默认值时直接回车即选中。"""
    print(f"\n{title}")
    for key, value in options.items():
        default_mark = "（默认）" if key == default else ""
        if isinstance(value, (PhotoSize, PaperSize)):
            print(f"  {key}. {value.name}{default_mark}  ({value.width_mm}×{value.height_mm} mm)")
        elif isinstance(value, tuple):
            print(f"  {key}. {value[0]}{default_mark}")
        else:
            print(f"  {key}. {value}{default_mark}")
    prompt = f"请输入编号（回车默认 {default}）：" if default is not None else "请输入编号："
    while True:
        raw = input(prompt).strip()
        if not raw and default is not None:
            return default
        try:
            choice = int(raw)
            if choice in options:
                return choice
            print("编号无效，请重新输入。")
        except ValueError:
            print("请输入数字编号。")


def _safe_filename(name: str) -> str:
    """将 Windows 文件名非法字符及空白替换为连字符。"""
    return re.sub(r'[<>:"/\\|?*\s]+', "-", name).strip("-")


def main() -> None:
    """运行交互式证件照生成流程。"""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print("=" * 58)
    print("   证件照自动排版工具（人脸识别 + 头部占比微调 + PDF切割线）")
    print("=" * 58)
    input_path = Path(input("\n请输入大头照路径（可直接拖拽）：").strip().strip('"'))
    if not input_path.is_file():
        print("文件不存在")
        return

    photo_size = PHOTO_SIZES[
        choose_from_menu("请选择证件照尺寸：", PHOTO_SIZES, default=DEFAULT_PHOTO_SIZE_ID)
    ]
    background_name, background_color = BACKGROUND_COLORS[
        choose_from_menu("请选择背景颜色：", BACKGROUND_COLORS)
    ]
    paper_size = PAPER_SIZES[
        choose_from_menu("请选择相纸尺寸：", PAPER_SIZES, default=DEFAULT_PAPER_SIZE_ID)
    ]
    print("\n开始处理...")
    photo_result = process_photo(input_path, photo_size, background_color)
    processed = photo_result.image

    photo_name = _safe_filename(photo_size.name)
    paper_name = _safe_filename(paper_size.name)
    output_dir = Path(OUTPUT_ROOT_DIR) / (
        f"{datetime.now().strftime(TIMESTAMP_FORMAT)}_{photo_name}_{paper_name}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    single_path = output_dir / f"single_{photo_name}.jpg"
    processed.save(single_path, quality=95)
    print(f"单张证件照已保存：{single_path}")

    paper_size_mm = (paper_size.width_mm, paper_size.height_mm)
    paper, _ = layout_on_paper(
        processed, photo_size.width_mm, photo_size.height_mm, paper_size_mm
    )
    layout_path = output_dir / f"layout_{paper_name}_{photo_name}.jpg"
    paper.save(layout_path, quality=95, dpi=(DPI, DPI))
    print(f"排版JPG已保存：{layout_path}")
    pdf_path = output_dir / f"layout_{paper_name}_{photo_name}_切割线.pdf"
    save_pdf_with_cut_lines(paper, pdf_path, paper_size_mm)
    if photo_result.warnings:
        print()
        for warning in photo_result.warnings:
            print(f"⚠️  {warning}")
    print(f"\n全部完成！输出目录：{output_dir}")
    print("推荐使用 PDF 文件打印，切割线会更清晰，裁剪更方便。")