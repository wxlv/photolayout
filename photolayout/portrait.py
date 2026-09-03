"""人像检测、裁剪和增强。"""

import logging

import cv2
import mediapipe as mp
import numpy as np
from PIL import Image


logger = logging.getLogger(__name__)


def straighten_portrait(image: Image.Image, min_angle: float = 2.5,
                        max_angle: float = 12) -> Image.Image:
    """根据双眼连线校正轻微的平面内人像倾斜。"""
    image_array = np.array(image.convert("RGBA"))
    height, width = image_array.shape[:2]
    rgb_image = cv2.cvtColor(image_array, cv2.COLOR_RGBA2RGB)

    with mp.solutions.face_mesh.FaceMesh(
        static_image_mode=True, max_num_faces=1, min_detection_confidence=0.5
    ) as face_mesh:
        results = face_mesh.process(rgb_image)

    if not results.multi_face_landmarks:
        logger.info("未检测到清晰人脸，跳过人像扶正")
        return image

    landmarks = results.multi_face_landmarks[0].landmark
    left_eye = landmarks[133]
    right_eye = landmarks[362]
    eye_angle = np.degrees(np.arctan2(
        (right_eye.y - left_eye.y) * height,
        (right_eye.x - left_eye.x) * width,
    ))

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


def detect_and_crop_face(image: Image.Image, target_ratio: float,
                         expand_top: float = 0.70, expand_bottom: float = 0.50,
                         expand_side: float = 0.32) -> Image.Image:
    """按人脸和双肩关键点裁剪，未识别到双肩时回退到人脸框。"""
    rgb_image = np.array(image.convert("RGB"))
    height, width = rgb_image.shape[:2]

    with mp.solutions.face_detection.FaceDetection(
        model_selection=1, min_detection_confidence=0.5
    ) as detector:
        results = detector.process(rgb_image)

    if not results.detections:
        logger.info("未检测到人脸，将使用整张图片")
        return image

    face = max(results.detections, key=lambda detection: detection.score[0])
    bounding_box = face.location_data.relative_bounding_box
    x = int(bounding_box.xmin * width)
    y = int(bounding_box.ymin * height)
    face_width = int(bounding_box.width * width)
    face_height = int(bounding_box.height * height)

    with mp.solutions.pose.Pose(
        static_image_mode=True, model_complexity=1, min_detection_confidence=0.5
    ) as pose:
        pose_results = pose.process(rgb_image)

    if pose_results.pose_landmarks:
        landmarks = pose_results.pose_landmarks.landmark
        left_shoulder = landmarks[mp.solutions.pose.PoseLandmark.LEFT_SHOULDER]
        right_shoulder = landmarks[mp.solutions.pose.PoseLandmark.RIGHT_SHOULDER]
        if left_shoulder.visibility >= 0.5 and right_shoulder.visibility >= 0.5:
            return _crop_with_shoulders(
                image, target_ratio, x, y, face_width, face_height,
                left_shoulder.x * width, left_shoulder.y * height,
                right_shoulder.x * width, right_shoulder.y * height,
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


def trim_body_below_shoulders(subject: Image.Image, reference_image: Image.Image) -> Image.Image:
    """保留肩部下方少量区域，并将人像底边对齐到画面底部。"""
    rgb_image = np.array(reference_image.convert("RGB"))
    height, width = rgb_image.shape[:2]
    with mp.solutions.face_detection.FaceDetection(
        model_selection=1, min_detection_confidence=0.5
    ) as detector:
        face_results = detector.process(rgb_image)
    if not face_results.detections:
        return subject

    face = max(face_results.detections, key=lambda detection: detection.score[0])
    face_height = int(face.location_data.relative_bounding_box.height * height)
    with mp.solutions.pose.Pose(
        static_image_mode=True, model_complexity=1, min_detection_confidence=0.5
    ) as pose:
        pose_results = pose.process(rgb_image)
    if not pose_results.pose_landmarks:
        return subject

    landmarks = pose_results.pose_landmarks.landmark
    left_shoulder = landmarks[mp.solutions.pose.PoseLandmark.LEFT_SHOULDER]
    right_shoulder = landmarks[mp.solutions.pose.PoseLandmark.RIGHT_SHOULDER]
    if left_shoulder.visibility < 0.5 or right_shoulder.visibility < 0.5:
        return subject

    cutoff_y = min(height, int(max(left_shoulder.y, right_shoulder.y) * height + face_height * 0.13))
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
    with mp.solutions.face_detection.FaceDetection(
        model_selection=1, min_detection_confidence=0.5
    ) as detector:
        results = detector.process(rgb_image)
    if not results.detections:
        logger.info("未检测到人脸，跳过照片增强")
        return image

    face = max(results.detections, key=lambda detection: detection.score[0])
    bounding_box = face.location_data.relative_bounding_box
    center = (int((bounding_box.xmin + bounding_box.width / 2) * width),
              int((bounding_box.ymin + bounding_box.height / 2) * height))
    axes = (max(1, int(bounding_box.width * width * 0.70)),
            max(1, int(bounding_box.height * height * 0.78)))
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