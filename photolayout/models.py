"""应用中共享的数据模型。"""

from dataclasses import dataclass


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
