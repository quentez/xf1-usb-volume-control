"""Public CLI: prepare offline, then explicitly flash or restore one device."""
import argparse
from datetime import datetime, timezone
from http.client import HTTPException
import json
import os
from pathlib import Path
import sys
import uuid

from . import __version__
from .catalog import RELEASE
from .firmware import identify
from .storage import download, prepare
from . import transport


def parser():
    result = argparse.ArgumentParser(
        prog="xf1-usb-volume",
        description="Enable native USB volume on Creative XF1 speakers. Unofficial; use at your own risk.")
    result.add_argument("--version", action="version", version=f"xf1-usb-volume {__version__}")
    commands = result.add_subparsers(dest="command", required=True)
    commands.add_parser("versions", help="List the explicitly supported firmware")
    commands.add_parser("doctor", help="Check macOS and libusb; no device changes")
    commands.add_parser("devices", help="List connected XF1 serial numbers; no writes")
    for name, help_text in (("download", "Download and preserve official firmware"),
                            ("prepare", "Download official firmware and build the reviewed volume patch")):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--firmware", default=RELEASE.version, choices=[RELEASE.version])
        command.add_argument("--directory", type=Path,
                             help="Folder for official/patched files; defaults to ~/Library/Application Support/xf1-usb-volume/firmware/<version>")
        if name == "prepare":
            command.add_argument("--input", type=Path, help="Use a local official file instead of downloading")
    check = commands.add_parser("verify", help="Validate an exact known official or patched file")
    check.add_argument("image", type=Path)
    probe = commands.add_parser("probe", help="Test USB update transport with INQUIRY only; requires sudo")
    probe.add_argument("--serial", required=True)
    for name, text in (("flash", "WRITE the reviewed volume patch; requires sudo"),
                       ("restore", "WRITE the supported official firmware; requires sudo")):
        command = commands.add_parser(name, help=text)
        command.add_argument("image", type=Path, help="Patched file for flash; official file for restore")
        command.add_argument("--serial", required=True, help="Exact serial from the devices command")
        command.add_argument("--log", type=Path, help="New log file; defaults to a unique file beside the image in logs/")
    return result


def require_macos(root=False):
    if sys.platform != "darwin":
        raise RuntimeError("USB operations are supported only on macOS")
    if root and os.geteuid() != 0:
        raise RuntimeError("Run this command with sudo to temporarily release the macOS USB driver")


def flash_image(image, serial, *, official=False, log_path=None):
    # Read and validate the whole file before discovering/claiming any USB device.
    payload = image.read_bytes()
    report = identify(payload)
    expected = "official" if official else "usb-volume-v1"
    if report["kind"] != expected:
        raise ValueError(f"This command requires {expected} firmware; got {report['kind']}")
    require_macos(root=True)
    if log_path is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        log_path = image.resolve().parent / "logs" / f"{'restore' if official else 'flash'}-{stamp}-{uuid.uuid4().hex[:8]}.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Image: {report['kind']} / {report['firmware_version']}\nSHA-256: {report['sha256']}\nDevice serial: {serial}")
    print(f"Transfer log: {log_path.resolve()}", flush=True)
    with log_path.open("x", encoding="utf-8") as log:
        log.write(json.dumps(dict(event="start", serial=serial, image=str(image.resolve()), **report)) + "\n")
        log.flush()
        transport.run(transport.find_speaker(serial), detach=True, payload=payload, log=log)
    print("After reboot, check playback and the macOS volume controls. A completed transfer alone does not verify installation.")


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "versions":
            print(f"Creative XF1 / MF1730: {RELEASE.version} ({RELEASE.internal_version})")
            print(f"Official SHA-256: {RELEASE.stock_sha256}\nPatched SHA-256:  {RELEASE.patched_sha256}")
        elif args.command == "doctor":
            require_macos()
            transport.backend()
            print(f"macOS: OK\nlibusb: OK ({transport.library_path()})\nNo USB commands sent.")
        elif args.command == "devices":
            require_macos()
            rows = transport.list_speakers()
            if not rows:
                print("No XF1 found. Connect the speaker's USB data cable and turn it on.")
                return 1
            for row in rows:
                print(f"{row['serial']}  {row['product']}")
        elif args.command == "download":
            path = download(args.directory, args.firmware)
            print(f"Verified official firmware: {path.resolve()}")
        elif args.command == "prepare":
            official, patched = prepare(args.directory, args.firmware, args.input)
            print(f"Official restore copy: {official.resolve()}\nPatched firmware: {patched.resolve()}")
            print("Both files verified. No USB commands sent.")
        elif args.command == "verify":
            print(json.dumps(identify(args.image.read_bytes()), indent=2))
        elif args.command == "probe":
            require_macos(root=True)
            transport.run(transport.find_speaker(args.serial), detach=True)
        elif args.command in ("flash", "restore"):
            flash_image(args.image, args.serial, official=args.command == "restore", log_path=args.log)
        return 0
    except (OSError, ValueError, RuntimeError, HTTPException) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted. If a firmware transfer started, inspect the log and device before retrying.", file=sys.stderr)
        return 130
