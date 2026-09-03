"""证件照处理流程编排。"""

import logging
from pathlib import Path

from PIL import Image, ImageEnhance
from rembg import remove

from .models import PhotoSize
from .portrait import detect_and_crop_face, enhance_portrait, straighten_portrait, trim_body_below_shoulders


logger = logging.getLogger(__name__)


def process_photo(input_path: str | Path, photo_size: PhotoSize,
                  background_color: tuple[int, int, int] = (255, 255, 255),
                  brightness: float = 1.05, contrast: float = 1.08) -> Image.Image:
    """生成指定尺寸和背景色的单张证件照。"""
    image = Image.open(input_path).convert("RGBA")
    image = straighten_portrait(image)
    logger.info("正在进行人脸识别与智能裁剪（根据尺寸微调头部占比）...")
    image = detect_and_crop_face(
        image, photo_size.aspect_ratio, photo_size.expand_top,
        photo_size.expand_bottom, photo_size.expand_side,
    )
    logger.info("正在去除背景...")
    foreground = remove(
        image, alpha_matting=True, alpha_matting_foreground_threshold=240,
        alpha_matting_background_threshold=10, alpha_matting_erode_size=3,
        decontaminate=True,
    )
    foreground = trim_body_below_shoulders(foreground, image)
    background = Image.new("RGBA", foreground.size, background_color + (255,))
    result = Image.alpha_composite(background, foreground).convert("RGB")
    result = enhance_portrait(result)
    result = ImageEnhance.Brightness(result).enhance(brightness)
    return ImageEnhance.Contrast(result).enhance(contrast)