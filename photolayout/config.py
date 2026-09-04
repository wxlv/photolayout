"""默认尺寸、背景色与排版配置。"""

from .models import PaperSize, PhotoSize


PHOTO_SIZES = {
    1: PhotoSize("标准一寸", 25, 35, 0.70, 0.50, 0.32),
    2: PhotoSize("小一寸", 22, 32, 0.65, 0.48, 0.30),
    3: PhotoSize("大一寸 / 护照", 33, 48, 0.75, 0.55, 0.35),
    4: PhotoSize("标准二寸", 35, 49, 0.72, 0.52, 0.33),
    5: PhotoSize("小二寸", 35, 45, 0.68, 0.50, 0.32),
    6: PhotoSize("大二寸", 35, 53, 0.75, 0.58, 0.35),
    7: PhotoSize("身份证", 26, 32, 0.68, 0.48, 0.30),
    8: PhotoSize("驾驶证", 22, 32, 0.65, 0.48, 0.30),
    9: PhotoSize("赴美签证", 51, 51, 0.55, 0.60, 0.38),
    10: PhotoSize("日本签证", 45, 45, 0.55, 0.60, 0.38),
    11: PhotoSize("港澳通行证", 33, 48, 0.75, 0.55, 0.35),
}

PAPER_SIZES = {
    1: PaperSize("5寸", 89, 127),
    2: PaperSize("6寸", 102, 152),
    3: PaperSize("7寸", 127, 178),
    4: PaperSize("8寸", 152, 203),
    5: PaperSize("A4", 210, 297),
}

BACKGROUND_COLORS = {
    1: ("白色", (255, 255, 255)),
    2: ("蓝色（推荐证件照）", (67, 142, 219)),
    3: ("红色", (255, 0, 0)),
    4: ("浅蓝色", (173, 216, 230)),
}

DEFAULT_PHOTO_SIZE_ID = 1
DEFAULT_PAPER_SIZE_ID = 2

OUTPUT_ROOT_DIR = "images-data"
TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"

DPI = 300
GAP_MM = 3.5
MARGIN_MM = 5

# 肩部带人像宽度占照片宽度的目标占比，低于此值触发拓宽/告警
MIN_SHOULDER_WIDTH_RATIO = 0.72
# 肩部带横向拉伸的最大倍率，防止衣服失真
MAX_SHOULDER_STRETCH = 1.35