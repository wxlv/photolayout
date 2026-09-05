"""rembg 会话缓存与 provider 选择的单测。

不加载真实模型：provider 选择用 mock 校验；会话缓存校验 _build_session
只被调用一次。
"""

import unittest
from unittest import mock

from photolayout import rembg_session


class ProviderSelectionTests(unittest.TestCase):
    def test_cuda_preferred_when_available(self) -> None:
        with mock.patch.object(
            rembg_session.ort,
            "get_available_providers",
            return_value=["TensorrtExecutionProvider", "CUDAExecutionProvider", "CPUExecutionProvider"],
        ):
            self.assertEqual(
                rembg_session._preferred_providers(),
                ["CUDAExecutionProvider", "CPUExecutionProvider"],
            )

    def test_cpu_only_when_no_accelerator(self) -> None:
        with mock.patch.object(
            rembg_session.ort,
            "get_available_providers",
            return_value=["CPUExecutionProvider"],
        ):
            self.assertEqual(
                rembg_session._preferred_providers(),
                ["CPUExecutionProvider"],
            )

    def test_openvino_fallback_priority(self) -> None:
        with mock.patch.object(
            rembg_session.ort,
            "get_available_providers",
            return_value=["OpenVINOExecutionProvider", "CPUExecutionProvider"],
        ):
            self.assertEqual(
                rembg_session._preferred_providers(),
                ["OpenVINOExecutionProvider", "CPUExecutionProvider"],
            )


class SessionCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        rembg_session._session = None

    def tearDown(self) -> None:
        rembg_session._session = None

    def test_session_built_once_and_cached(self) -> None:
        fake_session = object()
        with mock.patch.object(
            rembg_session, "_build_session", return_value=fake_session
        ) as build:
            first = rembg_session.get_session()
            second = rembg_session.get_session()
            self.assertIs(first, second)
            self.assertIs(first, fake_session)
            build.assert_called_once_with()

    def test_session_rebuilt_after_reset(self) -> None:
        fake = object()
        with mock.patch.object(rembg_session, "_build_session", return_value=fake) as build:
            rembg_session.get_session()
            rembg_session._session = None
            rembg_session.get_session()
            self.assertEqual(build.call_count, 2)


if __name__ == "__main__":
    unittest.main()
