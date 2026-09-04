"""基于 Gradio 的 Web 界面。"""

import logging
import tempfile
from pathlib import Path

import gradio as gr

from .cli import _safe_filename
from .config import (
    BACKGROUND_COLORS,
    DEFAULT_PAPER_SIZE_ID,
    DEFAULT_PHOTO_SIZE_ID,
    DPI,
    PAPER_SIZES,
    PHOTO_SIZES,
)
from .layout import layout_on_paper, save_pdf_with_cut_lines


logger = logging.getLogger(__name__)

# 无滚动 + flex 弹性布局：上传区与相纸排版区 flex=1 吸收剩余空间；
# 表单/按钮/单张/PDF 区固定合理高度；图片内容 contain 缩放。
NO_SCROLL_CSS = """
html, body { overflow: hidden; }
/* 解除 Gradio 默认 1024px 内容宽度限制，铺满页面 */
.gradio-container .main.fillable { max-width: 100% !important; }
.app-title { margin: 4px 0 !important; }
.app-title h1 { margin: 0; font-size: 1.4em; }
.app-title p { margin: 2px 0; }

.main-row { flex: 1 1 0; min-height: 0; }
.left-col, .right-col { display: flex; flex-direction: column;
                        height: 100%; min-height: 0; gap: 8px; }

/* ---- 左列：上传区 flex=1，下拉表单与开始生成按钮固定自然高 ---- */
/* Gradio 默认给 .form 与 Button 设置了 flex-grow，必须用 !important 压制 */
.left-col > .upload-area { flex: 1 1 0 !important; min-height: 0;
                           display: flex; flex-direction: column; }
.left-col > .form { flex: 0 0 auto !important; }
.left-col > .form > .block { flex: 0 0 auto !important; }
.left-col > button { flex: 0 0 auto !important; }

/* 上传区内部：图片容器撑满，来源选择条保持 slim */
.upload-area .image-container { flex: 1 1 0; min-height: 0; }
.upload-area .upload-container { flex: 1 1 0 !important; min-height: 0; }
.upload-area .source-selection { flex: 0 0 auto !important; }
.upload-area img { object-fit: contain; }

/* ---- 右列：单张/PDF 固定合理高度，相纸排版 flex=1，提示文字自然高 ---- */
.right-col > .single-area { flex: 0 0 auto !important; height: 220px; }
.right-col > .pdf-area { flex: 0 0 auto !important; }
.pdf-area .empty { min-height: 72px !important; height: 72px; }
.right-col > .layout-area { flex: 1 1 0 !important; min-height: 0; }
.right-col > .warnings-area { flex: 0 0 auto !important; }

/* 输出图片 contain 缩放 */
.single-area img, .layout-area img { object-fit: contain; }

/* 旋转按钮（仅预览，不改图片数据） */
.rotatable { position: relative; }
.rotate-btn { position: absolute; top: 6px; right: 6px; z-index: 10;
              padding: 2px 8px; border-radius: 6px; cursor: pointer;
              background: rgba(0,0,0,0.55); color: #fff; border: none; }
footer { display: none !important; }
"""

# 为带 .rotatable 的图片容器注入“⟳ 旋转”按钮，点击仅做前端 CSS transform 预览旋转，
# 不改变后端处理。MutationObserver 兼容输出图动态更新。
ROTATE_JS = """
function addRotateButtons() {
  document.querySelectorAll('.rotatable').forEach(function(container) {
    if (container.querySelector('.rotate-btn')) return;
    var btn = document.createElement('button');
    btn.className = 'rotate-btn';
    btn.textContent = '⟳ 旋转';
    btn.style.position = 'absolute';
    var wrapper = container;
    if (getComputedStyle(wrapper).position === 'static') {
      wrapper.style.position = 'relative';
    }
    btn.addEventListener('click', function(e) {
      e.preventDefault();
      var img = container.querySelector('img');
      if (!img) return;
      var cur = parseInt(img.dataset.rot || '0', 10);
      var next = (cur + 90) % 360;
      img.dataset.rot = String(next);
      img.style.transform = 'rotate(' + next + 'deg)';
      img.style.transition = 'transform 0.2s';
    });
    wrapper.appendChild(btn);
  });
}
addRotateButtons();
new MutationObserver(addRotateButtons).observe(document.body,
  { childList: true, subtree: true });
"""


def _photo_label(key: int, size) -> str:
    default = "（默认）" if key == DEFAULT_PHOTO_SIZE_ID else ""
    return f"{size.name}{default}（{size.width_mm}×{size.height_mm} mm）"


def _paper_label(key: int, size) -> str:
    default = "（默认）" if key == DEFAULT_PAPER_SIZE_ID else ""
    return f"{size.name}{default}（{size.width_mm}×{size.height_mm} mm）"


_PHOTO_CHOICES = {_photo_label(k, v): k for k, v in PHOTO_SIZES.items()}
_PAPER_CHOICES = {_paper_label(k, v): k for k, v in PAPER_SIZES.items()}
_BG_CHOICES = {name: key for key, (name, _) in BACKGROUND_COLORS.items()}

_DEFAULT_PHOTO_LABEL = _photo_label(DEFAULT_PHOTO_SIZE_ID, PHOTO_SIZES[DEFAULT_PHOTO_SIZE_ID])
_DEFAULT_PAPER_LABEL = _paper_label(DEFAULT_PAPER_SIZE_ID, PAPER_SIZES[DEFAULT_PAPER_SIZE_ID])
_DEFAULT_BG_LABEL = BACKGROUND_COLORS[1][0]  # 白色


def generate(image_path, photo_label, bg_label, paper_label):
    """处理上传照片，返回单张预览、排版预览、PDF 路径与告警文本。"""
    if image_path is None:
        return None, None, None, "⚠️ 请先上传一张照片。"

    photo_size = PHOTO_SIZES[_PHOTO_CHOICES[photo_label]]
    background_color = BACKGROUND_COLORS[_BG_CHOICES[bg_label]][1]
    paper_size = PAPER_SIZES[_PAPER_CHOICES[paper_label]]

    from .service import process_photo  # 延迟导入，加快界面启动

    tmp_dir = Path(tempfile.mkdtemp(prefix="photolayout_"))
    photo_name = _safe_filename(photo_size.name)
    paper_name = _safe_filename(paper_size.name)

    photo_result = process_photo(image_path, photo_size, background_color)
    processed = photo_result.image

    single_path = tmp_dir / f"single_{photo_name}.jpg"
    processed.save(single_path, quality=95)

    paper_size_mm = (paper_size.width_mm, paper_size.height_mm)
    paper, _ = layout_on_paper(
        processed, photo_size.width_mm, photo_size.height_mm, paper_size_mm
    )
    layout_path = tmp_dir / f"layout_{paper_name}_{photo_name}.jpg"
    paper.save(layout_path, quality=95, dpi=(DPI, DPI))
    pdf_path = tmp_dir / f"layout_{paper_name}_{photo_name}_切割线.pdf"
    save_pdf_with_cut_lines(paper, pdf_path, paper_size_mm)

    warnings_text = (
        "\n".join(f"⚠️ {w}" for w in photo_result.warnings)
        if photo_result.warnings
        else "✅ 处理完成，无构图问题。"
    )
    return str(single_path), str(layout_path), str(pdf_path), warnings_text


def build_ui() -> gr.Blocks:
    """构建 Gradio 界面。"""
    with gr.Blocks(title="PhotoLayout 证件照自动排版", fill_height=True) as demo:
        gr.Markdown(
            "# 📸 PhotoLayout 证件照自动排版\n上传一张生活照，自动生成标准证件照、相纸排版与切割线 PDF。",
            elem_classes=["app-title"],
        )
        with gr.Row(equal_height=True, elem_classes=["main-row"]):
            with gr.Column(scale=2, min_width=360, elem_classes=["left-col"]):
                input_image = gr.Image(
                    label="上传照片",
                    type="filepath",
                    sources=["upload", "clipboard"],
                    elem_classes=["upload-area", "rotatable"],
                )
                photo_dd = gr.Dropdown(
                    label="证件照尺寸",
                    choices=list(_PHOTO_CHOICES.keys()),
                    value=_DEFAULT_PHOTO_LABEL,
                )
                bg_dd = gr.Dropdown(
                    label="背景颜色",
                    choices=list(_BG_CHOICES.keys()),
                    value=_DEFAULT_BG_LABEL,
                )
                paper_dd = gr.Dropdown(
                    label="相纸尺寸",
                    choices=list(_PAPER_CHOICES.keys()),
                    value=_DEFAULT_PAPER_LABEL,
                )
                run_btn = gr.Button("开始生成", variant="primary")
            with gr.Column(scale=3, min_width=520, elem_classes=["right-col"]):
                single_out = gr.Image(
                    label="单张证件照",
                    type="filepath",
                    elem_classes=["single-area", "rotatable"],
                )
                layout_out = gr.Image(
                    label="相纸排版",
                    type="filepath",
                    elem_classes=["layout-area", "rotatable"],
                )
                pdf_out = gr.File(
                    label="切割线 PDF（推荐打印使用）",
                    elem_classes=["pdf-area"],
                )
                warnings_out = gr.Markdown(label="提示", elem_classes=["warnings-area"])

        run_btn.click(
            fn=generate,
            inputs=[input_image, photo_dd, bg_dd, paper_dd],
            outputs=[single_out, layout_out, pdf_out, warnings_out],
            show_progress=True,
        )
    return demo


def launch_webui() -> None:
    """启动 WebUI 并自动打开浏览器。"""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logger.info("正在启动 Web 界面，浏览器将自动打开...")
    build_ui().launch(inbrowser=True, css=NO_SCROLL_CSS, js=ROTATE_JS)
