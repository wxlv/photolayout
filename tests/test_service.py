import unittest
from unittest import mock

from PIL import Image

from photolayout import service
from photolayout.config import DEFAULT_BEAUTY_LEVEL_ID


class ProcessPhotoBeautyWiringTests(unittest.TestCase):
    def test_apply_beauty_called_between_crop_and_remove(self):
        call_order = []

        def fake_detect_and_crop_face(image, *args, **kwargs):
            call_order.append("crop")
            return image

        def fake_apply_beauty(image, level, enable_reshape):
            call_order.append("beauty")
            self.assertEqual(level, DEFAULT_BEAUTY_LEVEL_ID)
            self.assertFalse(enable_reshape)
            return image, []

        def fake_remove(image, **kwargs):
            call_order.append("remove")
            return image

        image = Image.new("RGBA", (10, 10), (255, 255, 255, 255))
        photo_size = mock.Mock(aspect_ratio=0.75, expand_top=0.7, expand_bottom=0.5, expand_side=0.32)

        with mock.patch.object(service, "straighten_portrait", side_effect=lambda img: img), \
             mock.patch.object(service, "detect_and_crop_face", side_effect=fake_detect_and_crop_face), \
             mock.patch.object(service.beauty, "apply_beauty", side_effect=fake_apply_beauty), \
             mock.patch.object(service, "remove", side_effect=fake_remove), \
             mock.patch.object(service, "trim_body_below_shoulders", side_effect=lambda subj, ref: subj), \
             mock.patch.object(service, "widen_shoulder_band", side_effect=lambda subj, ref, *a, **k: (subj, None)), \
             mock.patch.object(service, "enhance_portrait", side_effect=lambda img: img), \
             mock.patch.object(service.Image, "open", return_value=image):
            service.process_photo("fake.jpg", photo_size)

        self.assertEqual(call_order, ["crop", "beauty", "remove"])


if __name__ == "__main__":
    unittest.main()
