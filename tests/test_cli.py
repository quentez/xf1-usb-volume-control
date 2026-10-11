import io
from http.client import IncompleteRead
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from xf1_usb_volume import cli, transport


class CLITests(unittest.TestCase):
    def test_interrupted_download_has_a_clean_error(self):
        with patch.object(cli, "download", side_effect=IncompleteRead(b"partial", 100)), \
             patch("sys.stderr", io.StringIO()) as errors:
            self.assertEqual(cli.main(["download"]), 1)
            self.assertIn("Error:", errors.getvalue())

    def test_unknown_image_rejected_before_usb_discovery(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "image.fot"
            image.write_bytes(b"unknown")
            with patch.object(transport, "find_speaker") as find, patch("sys.stderr", io.StringIO()):
                self.assertEqual(cli.main(["flash", str(image), "--serial", "TEST"]), 1)
                find.assert_not_called()
                self.assertFalse((Path(directory) / "logs").exists())

    def test_restore_rejects_a_patched_image_before_usb_discovery(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "image.fot"
            image.write_bytes(b"synthetic")
            with patch.object(cli, "identify", return_value={"kind": "usb-volume-v2"}), \
                 patch.object(transport, "find_speaker") as find, patch("sys.stderr", io.StringIO()):
                self.assertEqual(cli.main(["restore", str(image), "--serial", "TEST"]), 1)
                find.assert_not_called()

    def test_flash_rejects_official_image_before_usb_discovery(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "image.fot"
            image.write_bytes(b"synthetic")
            with patch.object(cli, "identify", return_value={"kind": "official"}), \
                 patch.object(transport, "find_speaker") as find, patch("sys.stderr", io.StringIO()):
                self.assertEqual(cli.main(["flash", str(image), "--serial", "TEST"]), 1)
                find.assert_not_called()

    def test_frozen_backend_requires_bundled_library(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(transport.sys, "frozen", True, create=True), \
             patch.object(transport.sys, "_MEIPASS", directory, create=True), \
             patch.object(transport.ctypes.util, "find_library") as fallback:
            with self.assertRaisesRegex(RuntimeError, "bundled libusb"):
                transport.library_path()
            fallback.assert_not_called()
            native = Path(directory) / "libusb-1.0.dylib"
            native.write_bytes(b"synthetic")
            self.assertEqual(transport.library_path(), str(native))

    def test_versions_never_opens_usb(self):
        with patch.object(transport, "backend") as backend, patch("sys.stdout", io.StringIO()):
            self.assertEqual(cli.main(["versions"]), 0)
            backend.assert_not_called()
