"""命令行交互入口。"""

import logging
from pathlib import Path

from .config import BACKGROUND_COLORS, DPI, PHOTO_SIZES
from .layout import layout_on_paper, save_pdf_with_cut_lines
from .models import PhotoSize
from .service import process_photo


def choose_from_menu(title: str, options: dict[int, object]) -> int:
    """显示编号菜单并返回有效选项。"""
    print(f"\n{title}")
    for key, value in options.items():
        if isinstance(value, PhotoSize):
            print(f"  {key}. {value.name}  ({value.width_mm}×{value.height_mm} mm)")
        elif isinstance(value, tuple):
            print(f"  {key}. {value[0]}")
        else:
            print(f"  {key}. {value}")
    while True:
        try:
            choice = int(input("请输入编号：").strip())
            if choice in options:
                return choice
            print("编号无效，请重新输入。")
        except ValueError:
            print("请输入数字编号。")


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

    photo_size = PHOTO_SIZES[choose_from_menu("请选择证件照尺寸：", PHOTO_SIZES)]
    background_name, background_color = BACKGROUND_COLORS[
        choose_from_menu("请选择背景颜色：", BACKGROUND_COLORS)
    ]
    print("\n开始处理...")
    processed = process_photo(input_path, photo_size, background_color)
    single_path = Path(f"single_{photo_size.name}.jpg")
    processed.save(single_path, quality=95)
    print(f"单张证件照已保存：{single_path}")

    paper, _ = layout_on_paper(processed, photo_size.width_mm, photo_size.height_mm)
    layout_path = Path(f"layout_6inch_{photo_size.name}.jpg")
    paper.save(layout_path, quality=95, dpi=(DPI, DPI))
    print(f"排版JPG已保存：{layout_path}")
    pdf_path = Path(f"layout_6inch_{photo_size.name}_切割线.pdf")
    save_pdf_with_cut_lines(paper, pdf_path)
    print("\n全部完成！")
    print("推荐使用 PDF 文件打印，切割线会更清晰，裁剪更方便。")