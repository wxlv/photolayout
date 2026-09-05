"""detection 适配层的无网络测试。

默认测试不依赖真实 AI 模型：通过 PHOTOLAYOUT_OFFLINE 模拟模型缺失场景，
验证检测接口优雅降级（返回空结果）且把原因交给上层告警。
真实模型集成测试需显式开启（见 README「常见问题」）：

    set PHOTOLAYOUT_RUN_MODEL_TESTS=1
    set PHOTOLAYOUT_MODELS_DIR=<已下载模型的目录>
    python -m unittest tests.test_detection -v
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from photolayout import detection


# 与 detection._MODEL_URLS 的键保持一致，仅用于“已缓存”场景占位
_MODEL_NAMES = (
    detection.FACE_DETECTOR_MODEL,
    detection.FACE_LANDMARKER_MODEL,
    detection.POSE_LANDMARKER_MODEL,
)


class ModelDirTests(unittest.TestCase):
    def test_model_dir_prefers_env_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {detection.MODELS_DIR_ENV: tmp}):
                self.assertEqual(detection.model_dir(), Path(tmp))

    def test_model_dir_defaults_to_home(self) -> None:
        with mock.patch.dict(os.environ):
            os.environ.pop(detection.MODELS_DIR_ENV, None)
            self.assertEqual(
                detection.model_dir(),
                Path.home() / ".photolayout" / "models",
            )


class DegradeTests(unittest.TestCase):
    def setUp(self) -> None:
        detection.reset_state()
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.env = {
            detection.MODELS_DIR_ENV: self.tmp_dir.name,
            detection.OFFLINE_ENV: "1",
        }

    def _blank_rgb(self) -> np.ndarray:
        return np.zeros((64, 64, 3), dtype=np.uint8)

    def test_offline_without_models_degrades(self) -> None:
        with mock.patch.dict(os.environ, self.env):
            faces = detection.detect_faces(self._blank_rgb())
            self.assertEqual(faces, [])
            self.assertFalse(detection.is_available())
            self.assertIsNotNone(detection.unavailable_reason())

    def test_degrade_reason_mentions_offline(self) -> None:
        with mock.patch.dict(os.environ, self.env):
            detection.detect_faces(self._blank_rgb())
            self.assertIn("OFFLINE", detection.unavailable_reason())

    def test_eye_line_and_shoulders_empty_when_degraded(self) -> None:
        with mock.patch.dict(os.environ, self.env):
            self.assertIsNone(detection.detect_eye_line(self._blank_rgb()))
            self.assertIsNone(detection.detect_shoulders(self._blank_rgb()))

    def test_no_retry_after_first_failure(self) -> None:
        with mock.patch.dict(os.environ, self.env):
            detection.detect_faces(self._blank_rgb())
            first_reason = detection.unavailable_reason()
            detection.detect_faces(self._blank_rgb())
            self.assertEqual(detection.unavailable_reason(), first_reason)


class ReadyTests(unittest.TestCase):
    def setUp(self) -> None:
        detection.reset_state()
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.env = {detection.MODELS_DIR_ENV: self.tmp_dir.name}

    def test_ready_when_all_model_files_exist(self) -> None:
        for name in _MODEL_NAMES:
            Path(self.tmp_dir.name, name).write_bytes(b"placeholder")
        with mock.patch.dict(os.environ, self.env):
            self.assertTrue(detection.is_available())
            self.assertIsNone(detection.unavailable_reason())

    def test_reason_none_before_any_detection(self) -> None:
        with mock.patch.dict(os.environ, self.env):
            self.assertIsNone(detection.unavailable_reason())


@unittest.skipUnless(
    os.environ.get("PHOTOLAYOUT_RUN_MODEL_TESTS") and os.environ.get("PHOTOLAYOUT_MODELS_DIR"),
    "设置 PHOTOLAYOUT_RUN_MODEL_TESTS=1 且 PHOTOLAYOUT_MODELS_DIR 指向真实模型目录"
    "才运行真实模型集成测试",
)
class RealModelTests(unittest.TestCase):
    """真实模型冒烟测试：需联网/已有模型缓存 + 演示图片。"""

    def setUp(self) -> None:
        detection.reset_state()
        self.demo = Path(__file__).resolve().parents[1] / "docs" / "images" / "demo_input.jpg"
        if not self.demo.is_file():
            self.skipTest("缺少 docs/images/demo_input.jpg")

    def test_real_detection_on_demo_photo(self) -> None:
        from PIL import Image

        image = np.array(Image.open(self.demo).convert("RGB"))
        self.assertGreaterEqual(len(detection.detect_faces(image)), 0)
        self.assertIsNone(detection.unavailable_reason())


if __name__ == "__main__":
    unittest.main()
