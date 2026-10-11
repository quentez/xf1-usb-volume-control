"""XF1 USB mass-storage transport; no firmware writes during discovery/probe."""
import ctypes.util
import datetime
import errno
import json
from pathlib import Path
import struct
import sys
import time

import usb.backend.libusb1
import usb.core
import usb.util

FLASH_CDB = bytes.fromhex("f0210000000000000000")
INQUIRY_CDB = bytes.fromhex("120000002400")
VID, PID = 0x041E, 0x32B9


def library_path():
    if getattr(sys, "frozen", False):
        bundled = Path(sys._MEIPASS) / "libusb-1.0.dylib"
        if not bundled.is_file():
            raise RuntimeError("The bundled libusb is missing; download the release again")
        return str(bundled)
    for path in ("/opt/homebrew/lib/libusb-1.0.dylib", "/usr/local/lib/libusb-1.0.dylib"):
        if Path(path).is_file():
            return path
    return ctypes.util.find_library("usb-1.0")


def backend():
    result = usb.backend.libusb1.get_backend(find_library=lambda _: library_path())
    if result is None:
        raise RuntimeError("libusb unavailable. For source installs: brew install libusb")
    return result


def list_speakers():
    rows = []
    for device in usb.core.find(find_all=True, idVendor=VID, idProduct=PID, backend=backend()):
        try:
            rows.append({"serial": read_serial(device), "product": "Creative XF1"})
        finally:
            usb.util.dispose_resources(device)
    return rows


def read_serial(device):
    try:
        serial = device.serial_number
    except (usb.core.USBError, ValueError) as error:
        raise RuntimeError("Could not read the XF1 USB identity (language/serial descriptor). "
                           "No firmware was sent. Reconnect USB or restart the speaker and try again. "
                           f"Original error: {error}") from error
    if not serial:
        raise RuntimeError("The XF1 returned no serial number; no firmware was sent.")
    return serial


def find_speaker(serial):
    matching = []
    try:
        for device in usb.core.find(find_all=True, idVendor=VID, idProduct=PID, backend=backend()):
            try:
                if read_serial(device) == serial:
                    matching.append(device)
                else:
                    usb.util.dispose_resources(device)
            except BaseException:
                usb.util.dispose_resources(device)
                raise
        if len(matching) != 1:
            raise RuntimeError(f"Expected one XF1 matching serial {serial!r}; found {len(matching)}")
        return matching[0]
    except BaseException:
        for device in matching:
            usb.util.dispose_resources(device)
        raise


class BulkOnlyTransport:
    def __init__(self, device):
        self.device = device
        self.tag = 0

    def command(self, cdb, *, output=None, input_length=0, timeout=5000):
        if not 1 <= len(cdb) <= 16 or (output is not None and input_length):
            raise ValueError("Invalid BOT command")
        self.tag = self.tag % 0xFFFFFFFF + 1
        length = len(output) if output is not None else input_length
        cbw = struct.pack("<IIIBBB16s", 0x43425355, self.tag, length,
                          0x80 if input_length else 0, 0, len(cdb), cdb)
        if self.device.write(0x01, cbw, timeout=timeout) != 31:
            raise RuntimeError("Short CBW write; transport state uncertain")
        result = b""
        if output is not None:
            if self.device.write(0x01, output, timeout=timeout) != length:
                raise RuntimeError("Short data write; no retry attempted")
        elif input_length:
            result = bytes(self.device.read(0x81, input_length, timeout=timeout))
        csw = bytes(self.device.read(0x81, 13, timeout=timeout))
        if len(csw) != 13:
            raise RuntimeError("Short CSW")
        signature, tag, residue, status = struct.unpack("<IIIB", csw)
        if signature != 0x53425355 or tag != self.tag:
            raise RuntimeError("Invalid CSW signature/tag")
        if status != 0 or residue != 0 or (input_length and len(result) != input_length):
            raise RuntimeError(f"SCSI failure: status={status} residue={residue} received={len(result)}")
        return result


def check_interface(device):
    interface = device.get_active_configuration()[(0, 0)]
    if (interface.bInterfaceClass, interface.bInterfaceSubClass, interface.bInterfaceProtocol) != (8, 6, 80):
        raise RuntimeError("Unexpected mass-storage interface")
    if {(ep.bEndpointAddress, ep.bmAttributes, ep.wMaxPacketSize) for ep in interface} != {(1, 2, 64), (0x81, 2, 64)}:
        raise RuntimeError("Unexpected mass-storage endpoints")


def cleanup_usb(device, *, claimed, detached, transfer_complete):
    disconnected = False

    def report_error(action, error):
        nonlocal disconnected
        # libusb's NO_DEVICE is -4; PyUSB normally also maps it to ENODEV.
        if error.errno == errno.ENODEV or error.backend_error_code == -4:
            disconnected = True
            if transfer_complete:
                return
        print(f"{action}: {error}", file=sys.stderr)

    if claimed:
        try:
            usb.util.release_interface(device, 0)
        except usb.core.USBError as error:
            report_error("Interface release", error)
    # A reboot invalidates the old handle. Waiting longer cannot make a driver
    # reattach on that handle succeed; the OS handles the newly enumerated device.
    if detached and not disconnected:
        try:
            device.attach_kernel_driver(0)
        except usb.core.USBError as error:
            report_error("Driver reattach", error)
    try:
        usb.util.dispose_resources(device)
    except usb.core.USBError as error:
        report_error("USB cleanup", error)
    if disconnected and transfer_complete:
        print("USB disconnected after transfer, as expected during reboot. "
              "Allow a few seconds for the speaker to reappear.", flush=True)


def run(device, *, detach=False, payload=None, log=None):
    detached = False
    claimed = False
    transfer_complete = False
    try:
        if payload is not None and (not payload or len(payload) % 512):
            raise ValueError("Firmware length must be a positive multiple of 512")
        check_interface(device)
        if detach and device.is_kernel_driver_active(0):
            print("Releasing the OS USB driver temporarily; audio may disconnect.", flush=True)
            device.detach_kernel_driver(0)
            detached = True
        usb.util.claim_interface(device, 0)
        claimed = True
        check_interface(device)
        transport = BulkOnlyTransport(device)
        inquiry = transport.command(INQUIRY_CDB, input_length=36)
        if inquiry[8:16].rstrip() != b"Generic" or inquiry[16:32].rstrip() != b"Masstorage":
            raise RuntimeError(f"Unexpected INQUIRY response: {inquiry.hex()}")
        print("INQUIRY passed: Generic / Masstorage. USB transport accessible.", flush=True)
        if payload is None:
            print("Read-only probe complete; no firmware commands sent.", flush=True)
            return
        if log is None:
            raise ValueError("Flash requires a log")
        last_progress = -1
        for offset in range(0, len(payload), 512):
            record = dict(time=datetime.datetime.now(datetime.timezone.utc).isoformat(), offset=offset,
                          length=512, state="sending")
            log.write(json.dumps(record) + "\n")
            log.flush()
            try:
                transport.command(FLASH_CDB, output=payload[offset:offset+512])
            except (Exception, KeyboardInterrupt) as error:
                record.update(state="uncertain", error=str(error))
                log.write(json.dumps(record) + "\n")
                log.flush()
                raise RuntimeError(f"Transfer stopped at {offset:#x}; no retry. Inspect device state before restarting.") from error
            record["state"] = "transport_acknowledged"
            log.write(json.dumps(record) + "\n")
            log.flush()
            progress = (offset+512)*100//len(payload)
            if progress//5 != last_progress:
                print(f"Transferred {offset+512}/{len(payload)} bytes ({progress}%)", flush=True)
                last_progress = progress//5
        transfer_complete = True
        print("All chunks acknowledged. Firmware acceptance/boot still requires verification.", flush=True)
        # Firmware normally reboots just after its final CSW. Allow that path
        # to finish before releasing the host handle; do not send reset/reboot.
        time.sleep(3)
    finally:
        cleanup_usb(device, claimed=claimed, detached=detached,
                    transfer_complete=transfer_complete)
