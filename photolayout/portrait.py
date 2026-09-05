"""人像检测、裁剪和增强。"""

import logging

import cv2
import numpy as np
from PIL import Image

from .detection import detect_eye_line, detect_faces, detect_shoulders


logger = logging.getLogger(__name__)


def straighten_portrait(image: Image.Image, min_angle: float = 2.5,
                        max_angle: float = 12) -> Image.Image:
    """根据双眼连线校正轻微的平面内人像倾斜。"""
    image_array = np.array(image.convert("RGBA"))
    height, width = image_array.shape[:2]
    rgb_image = cv2.cvtColor(image_array, cv2.COLOR_RGBA2RGB)

    eye_line = detect_eye_line(rgb_image)
    if eye_line is None:
        logger.info("未检测到清晰人脸，跳过人像扶正")
        return image

    (left_x, left_y), (right_x, right_y) = eye_line
    eye_angle = np.degrees(np.arctan2(right_y - left_y, right_x - left_x))

    if abs(eye_angle) < min_angle:
        logger.info("人像倾斜角度较小，跳过扶正")
        return image
    if abs(eye_angle) > max_angle:
        logger.info("人像倾斜角度过大，跳过自动扶正")
        return image

    rotation_matrix = cv2.getRotationMatrix2D((width / 2, height / 2), eye_angle, 1.0)
    rotated = cv2.warpAffine(
        image_array,
        rotation_matrix,
        (width, height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )
    logger.info("已根据眼线倾斜角度 %.1f 度扶正人像", eye_angle)
    return Image.fromarray(rotated, "RGBA")


def check_headroom(face_y: int, face_height: int, expand_top: float) -> bool:
    """原图头顶留白是否满足目标规格的头顶扩展要求。"""
    return face_y - face_height * expand_top >= 0


def detect_and_crop_face(image: Image.Image, target_ratio: float,
                         expand_top: float = 0.70, expand_bottom: float = 0.50,
                         expand_side: float = 0.32,
                         warnings: list[str] | None = None) -> Image.Image:
    """按人脸和双肩关键点裁剪，未识别到双肩时回退到人脸框。"""
    rgb_image = np.array(image.convert("RGB"))

    faces = detect_faces(rgb_image)
    if not faces:
        logger.info("未检测到人脸，将使用整张图片")
        return image

    face = faces[0]
    x = face.x
    y = face.y
    face_width = face.width
    face_height = face.height

    if warnings is not None and not check_headroom(y, face_height, expand_top):
        warnings.append(
            "原图头顶空间不足，成片可能缺少完整头顶；建议换一张头顶留白更多的照片。"
        )

    shoulders = detect_shoulders(rgb_image)
    if shoulders is not None:
        (left_x, left_y), (right_x, right_y) = shoulders
        return _crop_with_shoulders(
            image, target_ratio, x, y, face_width, face_height,
            left_x, left_y, right_x, right_y,
            expand_top, expand_side,
        )

    return _crop_with_face_box(
        image, x, y, face_width, face_height, expand_top, expand_bottom, expand_side,
    )


def _crop_with_shoulders(image: Image.Image, target_ratio: float, face_x: int,
                         face_y: int, face_width: int, face_height: int,
                         left_x: float, left_y: float, right_x: float, right_y: float,
                         expand_top: float, expand_side: float) -> Image.Image:
    """使用肩宽计算裁剪区域。"""
    image_width, image_height = image.size
    shoulder_span = abs(right_x - left_x)
    shoulder_y = max(left_y, right_y)
    crop_width = max(shoulder_span * 1.08, face_width * (1 + 2 * expand_side))
    crop_height = crop_width / target_ratio
    crop_top = max(0, face_y - face_height * expand_top)
    min_bottom = shoulder_y + face_height * 0.03
    if crop_top + crop_height < min_bottom:
        crop_height = min_bottom - crop_top
        crop_width = crop_height * target_ratio

    crop_width = min(crop_width, image_width, image_height * target_ratio)
    crop_height = crop_width / target_ratio
    center_x = (left_x + right_x) / 2
    x1 = int(max(0, min(image_width - crop_width, center_x - crop_width / 2)))
    y1 = int(max(0, min(image_height - crop_height, crop_top)))
    logger.info("检测到双肩，已按目标比例保留头部和双肩裁剪")
    return image.crop((x1, y1, int(x1 + crop_width), int(y1 + crop_height)))


def _crop_with_face_box(image: Image.Image, x: int, y: int, face_width: int,
                        face_height: int, expand_top: float, expand_bottom: float,
                        expand_side: float) -> Image.Image:
    """按人脸框和配置的扩展比例裁剪。"""
    image_width, image_height = image.size
    x1 = max(0, x - int(face_width * expand_side))
    y1 = max(0, y - int(face_height * expand_top))
    x2 = min(image_width, x + face_width + int(face_width * expand_side))
    y2 = min(image_height, y + face_height + int(face_height * expand_bottom))
    logger.info("未可靠检测到双肩，已使用人脸框裁剪")
    return image.crop((x1, y1, x2, y2))


def measure_band_width_ratio(alpha: np.ndarray, split_y: int) -> float:
    """量测 split_y 以下区域人像横向覆盖宽度占整图宽度的比例。"""
    if split_y >= alpha.shape[0]:
        return 0.0
    band = alpha[split_y:]
    occupied = np.argwhere((band > 0).any(axis=0))
    if occupied.size == 0:
        return 0.0
    return (occupied.max() - occupied.min() + 1) / alpha.shape[1]


def stretch_band(image: Image.Image, split_y: int, factor: float) -> Image.Image:
    """对 split_y 以下区域的内容做横向拉伸（中心锚定），头部保持不变。"""
    if factor <= 1.0 or split_y >= image.height:
        return image
    head = image.crop((0, 0, image.width, split_y))
    body = image.crop((0, split_y, image.width, image.height))
    body_alpha = np.array(body.getchannel("A"))
    columns = np.argwhere((body_alpha > 0).any(axis=0))
    if columns.size == 0:
        return image
    content_left, content_right = int(columns.min()), int(columns.max()) + 1
    content = body.crop((content_left, 0, content_right, body.height))
    content_width = content_right - content_left
    target_width = min(
        max(int(round(content_width * factor)), content_width + 1),
        image.width,
    )
    content = content.resize((target_width, content.height), Image.LANCZOS)
    # LANCZOS 会在内容边缘产生 alpha 渐隐，阈值化保持干净的肩部边缘
    stretched_alpha = np.array(content.getchannel("A"))
    content.putalpha(Image.fromarray(np.where(stretched_alpha > 128, 255, 0).astype(np.uint8)))
    new_body = Image.new("RGBA", body.size, (0, 0, 0, 0))
    new_body.paste(content, ((image.width - target_width) // 2, 0))
    result = image.copy()
    result.paste(head, (0, 0))
    result.paste(new_body, (0, split_y))
    return result


def widen_shoulder_band(subject: Image.Image, reference_image: Image.Image,
                        min_ratio: float = 0.72,
                        max_stretch: float = 1.35) -> tuple[Image.Image, str | None]:
    """量测肩部带人像宽度占比，不足时对下巴以下区域受控横向拉伸。

    返回 (处理后的图像, 告警文案或 None)。
    """
    rgb_image = np.array(reference_image.convert("RGB"))
    height = rgb_image.shape[0]
    faces = detect_faces(rgb_image)

    alpha = np.array(subject.getchannel("A"))
    if faces:
        face = faces[0]
        face_height = face.height
        split_y = int(face.y + face.height + face_height * 0.1)
        split_y = min(split_y, height - 1)
        ratio = measure_band_width_ratio(alpha, split_y)
        if ratio >= min_ratio:
            return subject, None
        factor = min(min_ratio / max(ratio, 1e-6), max_stretch)
        if factor > 1.0:
            subject = stretch_band(subject, split_y, factor)
            ratio = measure_band_width_ratio(
                np.array(subject.getchannel("A")), split_y
            )
            logger.info("肩部占比 %.0f%%，已对肩部以下区域横向拉伸 %.2f 倍", ratio * 100, factor)
        if ratio < min_ratio:
            return subject, (
                "原图肩部占比过小，已尽力补全但仍未填满两侧；"
                "建议换一张包含完整肩部的照片。"
            )
        return subject, None

    if measure_band_width_ratio(alpha, height // 2) < min_ratio:
        return subject, (
            "原图肩部占比过小，可能无法填满照片两侧；建议换一张包含完整肩部的照片。"
        )
    return subject, None


def trim_body_below_shoulders(subject: Image.Image, reference_image: Image.Image) -> Image.Image:
    """保留肩部下方少量区域，并将人像底边对齐到画面底部。"""
    rgb_image = np.array(reference_image.convert("RGB"))
    height, width = rgb_image.shape[:2]
    faces = detect_faces(rgb_image)
    if not faces:
        return subject

    face_height = faces[0].height
    shoulders = detect_shoulders(rgb_image)
    if shoulders is None:
        return subject

    (_, left_y), (_, right_y) = shoulders
    cutoff_y = min(height, int(max(left_y, right_y) + face_height * 0.13))
    alpha = np.array(subject.getchannel("A"), copy=True)
    alpha[cutoff_y:] = 0
    trimmed = subject.copy()
    trimmed.putalpha(Image.fromarray(alpha))
    bounds = trimmed.getchannel("A").getbbox()
    if not bounds:
        return subject

    left, _, right, bottom = bounds
    aligned = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    aligned.alpha_composite(trimmed, (int((width - (right - left)) / 2 - left), height - bottom))
    logger.info("已保留肩部下方区域，并将人像居中后贴合底边")
    return aligned


def enhance_portrait(image: Image.Image) -> Image.Image:
    """对人脸区域自然降噪，并在低光照时提亮。"""
    rgb_image = np.array(image.convert("RGB"))
    height, width = rgb_image.shape[:2]
    faces = detect_faces(rgb_image)
    if not faces:
        logger.info("未检测到人脸，跳过照片增强")
        return image

    face = faces[0]
    center = (int(face.x + face.width / 2), int(face.y + face.height / 2))
    axes = (max(1, int(face.width * 0.70)),
            max(1, int(face.height * 0.78)))
    face_mask = np.zeros((height, width), dtype=np.uint8)
    cv2.ellipse(face_mask, center, axes, 0, 0, 360, 255, -1)
    face_mask = cv2.GaussianBlur(face_mask, (0, 0), max(2, axes[0] // 6))
    blend = (face_mask.astype(np.float32) / 255.0)[..., None]

    denoised = cv2.bilateralFilter(rgb_image, 5, 25, 25)
    enhanced = (rgb_image * (1 - blend * 0.35) + denoised * blend * 0.35).astype(np.uint8)
    lab_image = cv2.cvtColor(enhanced, cv2.COLOR_RGB2LAB)
    face_pixels = lab_image[:, :, 0][face_mask > 200]
    if face_pixels.size and float(face_pixels.mean()) < 105:
        clahe = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(8, 8))
        corrected_lab = lab_image.copy()
        corrected_lab[:, :, 0] = clahe.apply(lab_image[:, :, 0])
        corrected = cv2.cvtColor(corrected_lab, cv2.COLOR_LAB2RGB)
        enhanced = (enhanced * (1 - blend * 0.55) + corrected * blend * 0.55).astype(np.uint8)
        logger.info("已对偏暗面部进行自然提亮和降噪")
    else:
        logger.info("已对人脸进行轻度降噪")

    softened = cv2.GaussianBlur(enhanced, (0, 0), 1.0)
    sharpened = cv2.addWeighted(enhanced, 1.08, softened, -0.08, 0)
    enhanced = (enhanced * (1 - blend * 0.18) + sharpened * blend * 0.18).astype(np.uint8)
    return Image.fromarray(enhanced, "RGB")
