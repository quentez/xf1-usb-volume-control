"""No vendor fixtures: full-image tests use an explicit local official file."""
import os
from pathlib import Path
import struct
import unittest

from xf1_usb_volume import firmware as fot
from xf1_usb_volume import feedback
from xf1_usb_volume.catalog import RELEASE, get_release
from xf1_usb_volume.format import crc16, crypt

FIXTURE = os.environ.get("XF1_TEST_FIRMWARE")


class FormatTests(unittest.TestCase):
    def test_crc_known_vector(self):
        self.assertEqual(crc16(b"123456789"), 0x29B1)

    def test_scrambler_roundtrip(self):
        data = bytes(range(256)) * 2
        self.assertEqual(crypt(crypt(data, 0x12345678), 0x12345678), data)
        self.assertNotEqual(crypt(data, 0x12345678), data)

    def test_unknown_version_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported firmware"):
            get_release("latest")

    def test_unknown_images_never_pass_the_allowlist(self):
        for data in (b"", b"FOT\0", bytes(RELEASE.size)):
            with self.subTest(length=len(data)), self.assertRaises(ValueError):
                fot.identify(data)
            with self.assertRaises(ValueError):
                fot.patch_volume(data)


@unittest.skipUnless(FIXTURE, "set XF1_TEST_FIRMWARE for full-image integration tests")
class FirmwareIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stock = Path(FIXTURE).read_bytes()
        cls.original = fot.validate(cls.stock, RELEASE.stock_crc32)
        cls.patched = fot.patch_volume(cls.stock)

    def test_output_matches_physically_tested_image(self):
        self.assertEqual(fot.sha256(self.stock), RELEASE.stock_sha256)
        self.assertEqual(fot.sha256(self.patched), RELEASE.patched_sha256)
        self.assertEqual(fot.identify(self.stock)["kind"], "official")
        self.assertEqual(fot.identify(self.patched)["kind"], "usb-volume-v2")

    def test_unmodified_repack_is_identical(self):
        self.assertEqual(fot.rebuild(self.stock, self.original, self.original["app"]), self.stock)

    def test_only_reviewed_application_region_changes(self):
        decoded = fot.validate(self.patched)
        differences = [i for i, (a, b) in enumerate(zip(self.original["app"], decoded["app"])) if a != b]
        ranges = [(offset, offset + len(code)) for offset, expected, code in feedback.PATCHES]
        self.assertEqual(len(differences), 646)
        self.assertTrue(all(i == fot.VOLUME_OFFSET or 0xC830 <= i < 0xC862 or
                            any(start <= i < end for start, end in ranges) for i in differences))
        self.assertEqual(decoded["app"][fot.VOLUME_OFFSET], 3)
        self.assertEqual(decoded["resources"], self.original["resources"])
        self.assertEqual(decoded["boot"], self.original["boot"])

    def test_corruption_is_rejected(self):
        for offset in (0x20, 0xE00, 0xAF600, 0xEE210, 0xEE440, 0xEEA00, 0xEE50F, 0xEE4FF):
            with self.subTest(offset=hex(offset)):
                data = bytearray(self.patched)
                data[offset] ^= 1
                with self.assertRaises(ValueError):
                    fot.validate(data)
                with self.assertRaises(ValueError):
                    fot.identify(data)

    def test_inner_corruption_rejected_even_with_refreshed_outer_checksums(self):
        for offset in (0xE00, 0xCF8, 0xEE440, 0xEEA00, 0xEE000):
            with self.subTest(offset=hex(offset)):
                data = bytearray(self.patched)
                data[offset] ^= 1
                struct.pack_into("<4H", data, 0x38, *fot.container_checksums(data))
                struct.pack_into("<H", data, 0xFE, fot.crc16(data[:0xFE]))
                data[fot.DATA_END:fot.TAIL_START] = data[:512]
                with self.assertRaises(ValueError):
                    fot.validate(data)

    def test_repatching_is_rejected(self):
        with self.assertRaises(ValueError):
            fot.patch_volume(self.patched)

    def test_feedback_refuses_changed_caves_and_hooks(self):
        for offset in [*(start for start, end in feedback.CAVES),
                       *(end - 1 for start, end in feedback.CAVES),
                       *(offset for offset, expected, code in feedback.PATCHES)]:
            app = bytearray(self.original["app"])
            app[offset] ^= 1
            with self.subTest(offset=hex(offset)), self.assertRaises(ValueError):
                feedback.apply(app)
