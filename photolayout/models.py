"""应用中共享的数据模型。"""

from dataclasses import dataclass, field

from PIL import Image


@dataclass(frozen=True)
class PhotoSize:
    """证件照成品尺寸与以人脸框为基准的裁剪参数。"""

    name: str
    width_mm: int
    height_mm: int
    expand_top: float
    expand_bottom: float
    expand_side: float

    @property
    def aspect_ratio(self) -> float:
        """返回成品的宽高比。"""
        return self.width_mm / self.height_mm


@dataclass(frozen=True)
class PaperSize:
    """相纸物理尺寸。"""

    name: str
    width_mm: int
    height_mm: int


@dataclass(frozen=True)
class PhotoResult:
    """证件照处理结果及过程中产生的提示信息。"""

    image: Image.Image
    warnings: list[str] = field(default_factory=list)
