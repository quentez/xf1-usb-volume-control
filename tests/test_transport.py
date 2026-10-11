"""Exercise wire framing and stop behavior without touching a USB device."""
import io
import errno
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import Mock, patch

from xf1_usb_volume import transport as flash


class FakeDevice:
    def __init__(self, status=0, residue=0, tag_delta=0, short_data=False):
        self.writes = []
        self.status = status
        self.residue = residue
        self.tag_delta = tag_delta
        self.short_data = short_data
        self.tag = 0

    def write(self, endpoint, data, timeout):
        data = bytes(data)
        self.writes.append((endpoint, data))
        if len(data) == 31:
            self.tag = struct.unpack_from("<I", data, 4)[0]
        return len(data) - (1 if self.short_data and len(data) == 512 else 0)

    def read(self, endpoint, size, timeout):
        if size == 36:
            return bytes(8) + b"Generic " + b"Masstorage      " + b"1.00"
        return struct.pack("<IIIB", 0x53425355, self.tag+self.tag_delta, self.residue, self.status)


class TransportTests(unittest.TestCase):
    def test_inquiry_framing(self):
        device = FakeDevice()
        result = flash.BulkOnlyTransport(device).command(flash.INQUIRY_CDB, input_length=36)
        self.assertEqual(len(result), 36)
        self.assertEqual(device.writes, [(1, struct.pack("<IIIBBB16s", 0x43425355, 1, 36,
                                                     0x80, 0, 6, flash.INQUIRY_CDB))])

    def test_flash_framing(self):
        device = FakeDevice()
        payload = bytes(range(256))*2
        flash.BulkOnlyTransport(device).command(flash.FLASH_CDB, output=payload)
        self.assertEqual(device.writes, [(1, struct.pack("<IIIBBB16s", 0x43425355, 1, 512,
                                                      0, 0, 10, flash.FLASH_CDB)), (1, payload)])

    def test_no_retry_on_ambiguous_or_failed_write(self):
        for kwargs in (dict(status=1), dict(status=2), dict(residue=512),
                       dict(tag_delta=1), dict(short_data=True)):
            with self.subTest(kwargs=kwargs):
                device = FakeDevice(**kwargs)
                with self.assertRaises(RuntimeError):
                    flash.BulkOnlyTransport(device).command(flash.FLASH_CDB, output=bytes(512))
                self.assertEqual(len(device.writes), 2)

    def test_probe_sends_only_inquiry(self):
        device = FakeDevice()
        with patch.object(flash, "check_interface"), patch.object(flash.usb.util, "claim_interface"), \
             patch.object(flash.usb.util, "release_interface"), patch.object(flash.usb.util, "dispose_resources"), \
             patch("sys.stdout", new=io.StringIO()):
            flash.run(device)
        self.assertEqual(len(device.writes), 1)
        self.assertEqual(device.writes[0][1][15:21], flash.INQUIRY_CDB)

    def test_failed_transfer_does_not_classify_cleanup_disconnect_as_reboot(self):
        device = FakeDevice(short_data=True)
        output, errors, log = io.StringIO(), io.StringIO(), io.StringIO()
        gone = flash.usb.core.USBError("No such device", error_code=-4, errno=errno.ENODEV)
        with patch.object(flash, "check_interface"), patch.object(flash.usb.util, "claim_interface"), \
             patch.object(flash.usb.util, "release_interface", side_effect=gone), \
             patch.object(flash.usb.util, "dispose_resources"), \
             patch("sys.stdout", output), patch("sys.stderr", errors):
            with self.assertRaisesRegex(RuntimeError, "Transfer stopped"):
                flash.run(device, payload=bytes(512), log=log)
        self.assertIn('"state": "uncertain"', log.getvalue())
        self.assertIn("Interface release", errors.getvalue())
        self.assertNotIn("expected during reboot", output.getvalue())


class CleanupTests(unittest.TestCase):
    def cleanup(self, *, complete=True, release_error=None, attach_error=None, dispose_error=None):
        device = Mock()
        device.attach_kernel_driver.side_effect = attach_error
        output, errors = io.StringIO(), io.StringIO()
        with patch.object(flash.usb.util, "release_interface", side_effect=release_error), \
             patch.object(flash.usb.util, "dispose_resources", side_effect=dispose_error) as dispose, \
             patch("sys.stdout", output), patch("sys.stderr", errors):
            flash.cleanup_usb(device, claimed=True, detached=True, transfer_complete=complete)
            dispose.assert_called_once_with(device)
        return device, output.getvalue(), errors.getvalue()

    def test_expected_disconnect_skips_stale_driver_reattach(self):
        gone = flash.usb.core.USBError("No such device", errno=errno.ENODEV)
        device, output, errors = self.cleanup(release_error=gone, dispose_error=gone)
        device.attach_kernel_driver.assert_not_called()
        self.assertEqual(errors, "")
        self.assertEqual(output.count("expected during reboot"), 1)

    def test_disconnect_during_reattach_is_also_expected(self):
        gone = flash.usb.core.USBError("No such device", error_code=-4)
        device, output, errors = self.cleanup(attach_error=gone)
        device.attach_kernel_driver.assert_called_once_with(0)
        self.assertEqual(errors, "")
        self.assertIn("expected during reboot", output)

    def test_other_cleanup_errors_remain_visible(self):
        denied = flash.usb.core.USBError("Access denied", error_code=-3, errno=errno.EACCES)
        device, output, errors = self.cleanup(release_error=denied, attach_error=denied)
        device.attach_kernel_driver.assert_called_once_with(0)
        self.assertIn("Interface release", errors)
        self.assertIn("Driver reattach", errors)
        self.assertEqual(output, "")

    def test_probe_disconnect_is_not_treated_as_successful_flash(self):
        gone = flash.usb.core.USBError("No such device", errno=errno.ENODEV)
        device, output, errors = self.cleanup(complete=False, release_error=gone)
        self.assertIn("Interface release", errors)
        self.assertEqual(output, "")

    def test_connected_device_reattaches_normally(self):
        device, output, errors = self.cleanup()
        device.attach_kernel_driver.assert_called_once_with(0)
        self.assertEqual((output, errors), ("", ""))


if __name__ == "__main__":
    unittest.main()
