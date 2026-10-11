import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from xf1_usb_volume import storage
from xf1_usb_volume.catalog import RELEASE


class StorageTests(unittest.TestCase):
    def test_only_official_https_host_is_allowed(self):
        storage.check_url(RELEASE.url)
        for url in ("http://files.creative.com/file", "https://evil.example/file",
                    "https://files.creative.com.evil.example/file", "https://user@files.creative.com/file"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                storage.check_url(url)

    def test_redirect_to_another_host_rejected_before_request(self):
        with self.assertRaises(ValueError):
            storage.OfficialRedirects().redirect_request(None, None, 302, "", {}, "https://evil.example/a")

    def test_save_is_readonly_and_refuses_changed_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "image.fot"
            storage.save_copy(path, b"synthetic")
            self.assertEqual(path.stat().st_mode & 0o222, 0)
            self.assertEqual(storage.save_copy(path, b"synthetic"), path)
            with self.assertRaises(ValueError):
                storage.save_copy(path, b"different")
            self.assertEqual(path.read_bytes(), b"synthetic")
            self.assertEqual([p.name for p in path.parent.iterdir()], ["image.fot"])

    def test_symlink_outputs_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "image.fot"
            path.symlink_to(Path(directory) / "missing")
            with self.assertRaises(ValueError):
                storage.save_copy(path, b"synthetic")

    def test_corrupt_download_is_not_saved(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.status = 200
        response.geturl.return_value = RELEASE.url
        response.headers = {"Content-Length": str(RELEASE.size)}
        response.read.return_value = bytes(RELEASE.size)
        opener = Mock()
        opener.open.return_value = response
        with tempfile.TemporaryDirectory() as directory, patch.object(storage, "build_opener", return_value=opener):
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                storage.download(Path(directory))
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_prepare_requires_official_input(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.fot"
            source.write_bytes(b"not firmware")
            output = Path(directory) / "output"
            with self.assertRaises(ValueError):
                storage.prepare(output, source=source)
            self.assertFalse(output.exists())
