"""Interactive setup by default, with explicit commands for advanced use."""
import argparse
from datetime import datetime, timezone
from http.client import HTTPException
import json
import os
from pathlib import Path
import sys
import subprocess
import uuid

from . import __version__
from .catalog import RELEASE
from .firmware import identify
from .storage import download, prepare, latest_official_release
from . import transport


def parser():
    result = argparse.ArgumentParser(
        prog="xf1-usb-volume",
        description="Enable native USB volume on Creative XF1 speakers. Unofficial; use at your own risk.")
    result.add_argument("--version", action="version", version=f"xf1-usb-volume {__version__}")
    result.epilog = "Run without a command to install the patch or restore official firmware interactively."
    commands = result.add_subparsers(dest="command")
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
    expected = "official" if official else "usb-volume-v2"
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


def choose(prompt, choices):
    while True:
        answer = input(prompt).strip().lower() or "q"
        if answer == "q" or answer in choices:
            return answer
        print("Choose one of the listed options, or q to cancel.")


def interactive():
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise RuntimeError("Interactive setup needs a terminal. Run xf1-usb-volume in Terminal, "
                           "or use --help for explicit commands.")
    require_macos()
    print(f"\nXF1 USB volume control {__version__}\n")
    print("  1. Enable USB volume and knob sync")
    print("  2. Restore official firmware")
    print("  q. Quit\n")
    action = choose("Choose an option [q]: ", {"1", "2"})
    if action == "q":
        print("Cancelled. No firmware was sent.")
        return 0
    official = action == "2"
    print("\nLooking for connected XF1 speakers…", flush=True)
    devices = transport.list_speakers()
    if not devices:
        raise RuntimeError("No XF1 found. Connect power and a USB data cable, turn it on, and run this tool again.")
    if any(not row["serial"] for row in devices):
        raise RuntimeError("Could not identify every XF1 by serial. Reconnect USB and try again; no firmware was sent.")
    if len(devices) == 1:
        device = devices[0]
    else:
        for index, row in enumerate(devices, 1):
            print(f"  {index}. {row['product']} — {row['serial']}")
        selection = choose("Select a speaker [q]: ", {str(i) for i in range(1, len(devices) + 1)})
        if selection == "q":
            print("Cancelled. No firmware was sent.")
            return 0
        device = devices[int(selection) - 1]
    print(f"Speaker: {device['product']} ({device['serial']})", flush=True)
    if official:
        print("Checking Creative's latest official release…", flush=True)
        release = latest_official_release()
        print(f"Downloading and verifying official firmware {release.version}…", flush=True)
        image = download(version=release.version).resolve()
    else:
        print(f"Downloading, verifying and patching firmware {RELEASE.version}…", flush=True)
        original, image = prepare()
        image = image.resolve()
        print(f"Official restore copy: {original.resolve()}")
    report = identify(image.read_bytes())
    expected = "official" if official else "usb-volume-v2"
    if report["kind"] != expected:
        raise ValueError("Prepared firmware does not match the selected operation")
    verb = "RESTORE" if official else "FLASH"
    print(f"\nReady to {'restore official firmware' if official else 'install USB volume and knob sync'}.\n"
          f"Firmware: {report['firmware_version']}\nFile: {image}\n"
          f"Speaker serial: {device['serial']}")
    print("\nUnofficial tool; use at your own risk. A failed update can disable the speaker.\n"
          "Stop playback and keep power and USB connected during the update and reboot.")
    if input(f"Type {verb} to continue, or press Enter to cancel: ").strip() != verb:
        print("Cancelled. Downloaded files are preserved; no firmware was sent.")
        return 0
    if os.geteuid() == 0:
        flash_image(image, device["serial"], official=official)
        return 0
    print("\nmacOS needs administrator access to release the USB driver.\n"
          "Enter your Mac login password when sudo asks (typing is hidden).", flush=True)
    # Revalidate the exact image and serial in the elevated process. Never pass
    # shell text or use a different interpreter for an installed source package.
    command = ([sys.executable] if getattr(sys, "frozen", False) else
               [sys.executable, "-m", "xf1_usb_volume"])
    command += ["restore" if official else "flash", str(image), "--serial", device["serial"]]
    environment = os.environ.copy()
    if getattr(sys, "frozen", False):
        # The privileged child must unpack its own PyInstaller runtime.
        # Pass through sudo explicitly; sudo normally filters environment vars.
        command = ["/usr/bin/env", "PYINSTALLER_RESET_ENVIRONMENT=1", *command]
    return subprocess.run(["/usr/bin/sudo", "--", *command], env=environment).returncode


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command is None:
            return interactive()
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
    except EOFError:
        print("\nCancelled. No firmware was sent.")
        return 0
