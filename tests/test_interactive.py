"""Exercise install/restore orchestration without downloading or flashing."""
from contextlib import ExitStack
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from xf1_usb_volume import cli
from xf1_usb_volume.catalog import RELEASE


class TerminalOutput(io.StringIO):
    def isatty(self):
        return True


class InteractiveTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        directory = self.stack.enter_context(tempfile.TemporaryDirectory(prefix="xf1 test "))
        self.official = Path(directory) / RELEASE.filename
        self.image = Path(directory) / RELEASE.patched_filename
        self.official.write_bytes(b"official")
        self.image.write_bytes(b"patched")
        self.output = self.stack.enter_context(patch("sys.stdout", TerminalOutput()))
        self.errors = self.stack.enter_context(patch("sys.stderr", io.StringIO()))
        self.stack.enter_context(patch.object(cli.sys, "stdin", Mock(isatty=lambda: True)))
        self.stack.enter_context(patch.object(cli.sys, "platform", "darwin"))
        self.stack.enter_context(patch.object(cli.os, "geteuid", return_value=0))
        self.input = self.stack.enter_context(patch("builtins.input"))
        self.devices = self.stack.enter_context(patch.object(cli.transport, "list_speakers", return_value=[
            {"serial": "TEST-ONE", "product": "Creative XF1"}]))
        self.prepare = self.stack.enter_context(patch.object(cli, "prepare", return_value=(self.official, self.image)))
        self.download = self.stack.enter_context(patch.object(cli, "download", return_value=self.official))
        self.latest = self.stack.enter_context(patch.object(cli, "latest_official_release", return_value=RELEASE))
        self.identify = self.stack.enter_context(patch.object(cli, "identify", side_effect=lambda data: {
            "kind": "official" if data == b"official" else "usb-volume-v2", "firmware_version": RELEASE.version}))
        self.flash = self.stack.enter_context(patch.object(cli, "flash_image"))
        self.sudo = self.stack.enter_context(patch.object(cli.subprocess, "run", return_value=Mock(returncode=0)))

    def run_menu(self, *answers):
        self.input.side_effect = answers
        return cli.main([])

    def test_quit_before_discovery_or_download(self):
        self.assertEqual(self.run_menu("q"), 0)
        self.devices.assert_not_called()
        self.prepare.assert_not_called()
        self.flash.assert_not_called()
        self.sudo.assert_not_called()

    def test_install_automates_prepare_and_exact_device_flash(self):
        def confirm(prompt):
            if "Choose" in prompt:
                return "1"
            self.prepare.assert_called_once_with()
            self.identify.assert_called_once_with(b"patched")
            self.flash.assert_not_called()
            return "FLASH"
        self.input.side_effect = confirm
        self.assertEqual(cli.main([]), 0)
        self.flash.assert_called_once_with(self.image.resolve(), "TEST-ONE", official=False)
        self.latest.assert_not_called()
        self.download.assert_not_called()

    def test_restore_checks_latest_and_downloads_without_patching(self):
        self.assertEqual(self.run_menu("2", "RESTORE"), 0)
        self.latest.assert_called_once_with()
        self.download.assert_called_once_with(version=RELEASE.version)
        self.prepare.assert_not_called()
        self.flash.assert_called_once_with(self.official.resolve(), "TEST-ONE", official=True)

    def test_confirmation_cancel_keeps_files_without_elevation(self):
        self.assertEqual(self.run_menu("1", ""), 0)
        self.prepare.assert_called_once_with()
        self.flash.assert_not_called()
        self.sudo.assert_not_called()
        self.assertEqual(self.image.read_bytes(), b"patched")

    def test_no_device_stops_before_download(self):
        self.devices.return_value = []
        self.assertEqual(self.run_menu("1"), 1)
        self.prepare.assert_not_called()
        self.sudo.assert_not_called()

    def test_multiple_devices_require_selection(self):
        self.devices.return_value.append({"serial": "TEST-TWO", "product": "Creative XF1"})
        self.assertEqual(self.run_menu("1", "2", "FLASH"), 0)
        self.flash.assert_called_once_with(self.image.resolve(), "TEST-TWO", official=False)

    def test_cancel_device_selection_does_not_prepare(self):
        self.devices.return_value *= 2
        self.assertEqual(self.run_menu("1", "q"), 0)
        self.prepare.assert_not_called()
        self.flash.assert_not_called()

    def test_bad_menu_choice_reprompts_without_side_effects(self):
        self.assertEqual(self.run_menu("bad", "q"), 0)
        self.devices.assert_not_called()

    def test_newer_unreviewed_release_stops_before_download(self):
        self.latest.side_effect = ValueError("Unreviewed firmware")
        self.assertEqual(self.run_menu("2"), 1)
        self.download.assert_not_called()
        self.flash.assert_not_called()

    def test_prepare_failure_never_reaches_flash(self):
        self.prepare.side_effect = ValueError("Checksum mismatch")
        self.assertEqual(self.run_menu("1"), 1)
        self.flash.assert_not_called()
        self.sudo.assert_not_called()

    def test_source_elevation_uses_exact_interpreter_image_and_serial(self):
        with patch.object(cli.os, "geteuid", return_value=501), \
             patch.object(cli.sys, "executable", "/example/virtual env/bin/python"), \
             patch.object(cli.sys, "frozen", False, create=True):
            self.assertEqual(self.run_menu("1", "FLASH"), 0)
        self.flash.assert_not_called()
        command = self.sudo.call_args.args[0]
        self.assertEqual(command, ["/usr/bin/sudo", "--", "/example/virtual env/bin/python", "-m", "xf1_usb_volume",
                                   "flash", str(self.image.resolve()), "--serial", "TEST-ONE"])
        self.assertNotIn("shell", self.sudo.call_args.kwargs)

    def test_frozen_elevation_relaunches_own_runtime_and_propagates_failure(self):
        self.sudo.return_value.returncode = 1
        with patch.object(cli.os, "geteuid", return_value=501), \
             patch.object(cli.sys, "executable", "/example/my downloads/xf1-usb-volume"), \
             patch.object(cli.sys, "frozen", True, create=True):
            self.assertEqual(self.run_menu("2", "RESTORE"), 1)
        command = self.sudo.call_args.args[0]
        self.assertEqual(command, ["/usr/bin/sudo", "--", "/usr/bin/env", "PYINSTALLER_RESET_ENVIRONMENT=1",
                                   "/example/my downloads/xf1-usb-volume", "restore", str(self.official.resolve()),
                                   "--serial", "TEST-ONE"])
        self.flash.assert_not_called()

    def test_noninteractive_input_does_not_discover_or_flash(self):
        with patch.object(cli.sys, "stdin", io.StringIO("1\nFLASH\n")):
            self.assertEqual(cli.main([]), 1)
        self.devices.assert_not_called()
        self.flash.assert_not_called()
        self.assertIn("needs a terminal", self.errors.getvalue())

    def test_eof_and_interrupt_before_confirmation_do_not_flash(self):
        for error, expected in ((EOFError(), 0), (KeyboardInterrupt(), 130)):
            self.input.side_effect = ["1", error]
            self.assertEqual(cli.main([]), expected)
            self.flash.assert_not_called()
            self.sudo.assert_not_called()
