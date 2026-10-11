"""Validate and rebuild the single reviewed FOT layout, entirely in memory."""
import binascii
import hashlib
import struct

from .format import crc16, crypt, decode_section, section, resource_entries
from .catalog import RELEASE
from . import feedback

CODE_KEY = 0xBA3E1ABE
LVMG = 0x474D564C
XAPP = 0x50504158
LENGTH = 0xEF400
DATA_START, DATA_END, TAIL_START = 0x200, 0xEE200, 0xEE400
VOLUME_OFFSET = 0xCEDA
USB_CALLBACK_OFFSET = 0xC830
# Hash of the expected 50-byte callback; original manufacturer code is not embedded.
STOCK_CALLBACK_SHA256 = "4e3e9fd34293891cae1e6a7edf57ba2256a8e85970bb1ebfb171eb61dc44720e"
# Independently written replacement, documented in docs/usb-volume-deferred.S.
DEFERRED_USB_CALLBACK = bytes.fromhex(
    "e16603c6d6e219c67d572386e6e2a38606e2828003c7c6e2630ca7002386a6e2"
    "37070500a308a7b81305207f6700428b8280")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def u16(data, offset):
    return struct.unpack_from("<H", data, offset)[0]


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def normalized_tail(tail):
    """Match 0x100430c2..0x100430e2; retain the original INFO checksum."""
    result = bytearray(tail)
    result[0x152:0x158] = bytes(6)
    result[0x227:0x24F] = bytes(0x28)
    return bytes(result)


def container_checksums(data):
    tail = normalized_tail(data[TAIL_START:])
    return (crc16(tail[:0x200]), crc16(tail[0x200:0x400]),
            crc16(data[DATA_START:DATA_END]), crc16(tail))


def decode_padded_section(data, sec, key, end):
    plain = bytearray(decode_section(data, sec, key))
    start = sec["offset"]
    # Even unused CRC slots have defined values. Their seed is the absolute
    # flash address of the slot, not its FOT offset (difference: 0x1e00).
    for offset in range(start + 16 + sec["blocks"] * 2,
                        start + sec["header_size"], 2):
        require(u16(data, offset) == crc16(data[start:offset], (offset + 0x1E00) & 0xFFFF),
                f"{sec['name']}: filler CRC mismatch at {offset:#x}")
    padded_blocks = (end - start - sec["header_size"]) // 512
    for index in range(sec["blocks"], padded_blocks):
        offset = start + sec["header_size"] + index * 512
        checksum = u16(data, start + 16 + index * 2)
        block = crypt(data[offset:offset+512], key ^ checksum)
        require(block == bytes(512), f"{sec['name']}: nonzero padding")
        plain.extend(block)
    return bytes(plain)


def validate(data, expected_crc32=None):
    require(len(data) == LENGTH, "Unsupported FOT length")
    require(data[:8] == b"FOT\0" + struct.pack("<I", LENGTH - 8), "Invalid FOT magic/size")
    require(u16(data, 0xFE) == crc16(data[:0xFE]), "FOT header CRC mismatch")
    require(data[8:16] == bytes.fromhex("c9cec6cf30000000"), "Unsupported INFO layout")
    require(data[0x10:0x18] == b"QUEN\x01\0\0\0", "Unsupported chip")
    require(data[0x20:0x24] == bytes.fromhex("85166404"), "Unsupported hardware ID")
    require(data[0x64:0x6C] == bytes.fromhex("c4c1d4c118000000"), "Unsupported DATA layout")
    require(struct.unpack_from("<6I", data, 0x6C) ==
            (DATA_START, DATA_END-DATA_START, DATA_END, TAIL_START, 0x100, 0x100),
            "Unsupported DATA offsets")
    require(data[DATA_END:TAIL_START] == data[:512], "Repeated FOT header mismatch")
    require(data[0x100] == 1 and sum(data[0x100:0x152]) % 256 == 0,
            "Patch-table count/checksum mismatch")
    require(struct.unpack_from("<IBBH", data, 0x102) == (0x152, 6, 4, 0xE037),
            "Unsupported patch-table range")

    tail = data[TAIL_START:]
    require(tail[0x100:0x10A] == bytes.fromhex("494e464f01003f012800"),
            "Unsupported tail INFO layout")
    require(tail[0xC0:0xC4] == bytes.fromhex("c4cfd7ce") and sum(tail[0xC0:0x100]) % 256 == 0,
            "DOWN table checksum mismatch")
    # The download template's INFO checksum excludes personalized fields.
    require(sum(normalized_tail(tail)[0x100:0x24F]) % 256 == 0,
            "Normalized INFO additive checksum mismatch")
    require(struct.unpack_from("<4H", data, 0x38) == container_checksums(data),
            "FOT INFO CRC mismatch")
    code = section(data, DATA_START, "XCOD")
    res = section(data, 0xAF600, "XRES")
    require((code["header_size"], code["size"], res["header_size"], res["size"]) ==
            (0xC00, 0xAE800, 0x400, 0x3E400), "Unsupported section sizes")
    app = decode_padded_section(data, code, CODE_KEY, res["offset"])
    resources = decode_padded_section(data, res, 0, DATA_END)
    resource_entries(resources[:res["size"]])

    boot_header = crypt(tail[:0x40], LVMG)
    require(boot_header[:12] == bytes.fromhex("5a0100a55155454e01000000"),
            "Invalid boot header magic/chip/flags")
    require(u16(boot_header, 0x3E) == crc16(boot_header[:0x3E]), "Boot header CRC mismatch")
    require(struct.unpack_from("<4I", boot_header, 0xC) == (0x10800, 0x10800, 0x400, 0xC00),
            "Unsupported bootstrap layout")
    boot_crc = u16(boot_header, 0x1C)
    boot = b"".join(crypt(tail[offset:offset+512], LVMG ^ boot_crc * 0x10001 ^ (offset//512-1))
                    for offset in range(0x400, 0x1000, 512))
    require(crc16(boot) == boot_crc, "Bootstrap code CRC mismatch")
    table_crc = u16(tail, 0x80)
    table = crypt(tail[0x40:0x80], XAPP ^ table_crc * 0x10001)
    require(crc16(table) == table_crc, "Region table CRC mismatch")
    require(struct.unpack_from("<IIIHBB", table) == (0x2000, len(app), 0, crc16(app), 0, 1),
            "Code region entry/CRC mismatch")
    require(struct.unpack_from("<IIIHBB", table, 16) ==
            (0xB1400, res["size"], 0, crc16(resources), 1, 1), "Resource region entry/CRC mismatch")
    require(table[32:] == bytes(32), "Unexpected extra regions")
    crc32 = f"{binascii.crc32(data):08X}"
    if expected_crc32 is not None:
        require(crc32 == expected_crc32.upper(), "Download CRC32 mismatch")
    report = dict(bytes=len(data), sha256=sha256(data), crc32=crc32,
                  info_crc16=[f"{v:04X}" for v in container_checksums(data)],
                  header_crc16=f"{u16(data, 0xFE):04X}", region_table_crc16=f"{table_crc:04X}",
                  boot_crc16=f"{boot_crc:04X}", app_sha256=sha256(app),
                  resources_padded_sha256=sha256(resources), boot_sha256=sha256(boot),
                  verified_payload_blocks=code["blocks"]+res["blocks"],
                  verified_filler_slots=138, resource_padding_blocks=2,
                  validation_scope="Known package integrity checks; physical boot acceptance untested")
    return dict(app=app, resources=resources, boot=boot, table=table, code=code,
                res=res, boot_header=boot_header, report=report)


def encode_section(template, sec, key, plain):
    header = bytearray(template[sec["offset"]:sec["offset"]+sec["header_size"]])
    for index, offset in enumerate(range(16, len(header), 2)):
        if index < sec["blocks"]:
            checksum = crc16(plain[index*512:(index+1)*512], index+1)
        else:
            checksum = crc16(header[:offset], (sec["offset"]+offset+0x1E00) & 0xFFFF)
        struct.pack_into("<H", header, offset, checksum)
    payload = b"".join(crypt(plain[index:index+512], key ^ u16(header, 16+index//256))
                       for index in range(0, len(plain), 512))
    return bytes(header) + payload


def rebuild(template, decoded, app):
    require(len(app) == len(decoded["app"]), "App size must be unchanged")
    result = bytearray(template)
    result[DATA_START:decoded["res"]["offset"]] = encode_section(template, decoded["code"], CODE_KEY, app)
    result[decoded["res"]["offset"]:DATA_END] = encode_section(template, decoded["res"], 0, decoded["resources"])
    table = bytearray(decoded["table"])
    struct.pack_into("<H", table, 12, crc16(app))
    table_crc = crc16(table)
    result[TAIL_START+0x40:TAIL_START+0x80] = crypt(table, XAPP ^ table_crc * 0x10001)
    struct.pack_into("<H", result, TAIL_START+0x80, table_crc)
    struct.pack_into("<4H", result, 0x38, *container_checksums(result))
    struct.pack_into("<H", result, 0xFE, crc16(result[:0xFE]))
    result[DATA_END:TAIL_START] = result[:512]
    return bytes(result)


def identify(data):
    """Require an exact reviewed image before structural parsing or USB access."""
    require(len(data) == RELEASE.size, "Unsupported firmware size")
    digest = sha256(data)
    if digest == RELEASE.stock_sha256:
        kind, checksum = "official", RELEASE.stock_crc32
    elif digest == RELEASE.patched_sha256:
        kind, checksum = "usb-volume-v2", RELEASE.patched_crc32
    else:
        raise ValueError("Unknown firmware SHA-256; only the reviewed official and patched images are accepted")
    report = validate(data, checksum)["report"]
    return dict(report, kind=kind, firmware_version=RELEASE.version)


def patch_volume(stock):
    require(sha256(stock) == RELEASE.stock_sha256, "Patching requires the exact supported official firmware")
    original = validate(stock, RELEASE.stock_crc32)
    require(rebuild(stock, original, original["app"]) == stock,
            "Unmodified repack is not byte-identical")
    app = bytearray(original["app"])
    require(app[VOLUME_OFFSET] == 1, "Unexpected USB capability byte")
    old_callback = app[USB_CALLBACK_OFFSET:USB_CALLBACK_OFFSET+50]
    require(sha256(old_callback) == STOCK_CALLBACK_SHA256, "Unexpected USB callback")
    require(len(DEFERRED_USB_CALLBACK) == 50, "Replacement callback size changed")
    app[VOLUME_OFFSET] = 3
    app[USB_CALLBACK_OFFSET:USB_CALLBACK_OFFSET+50] = DEFERRED_USB_CALLBACK
    app = feedback.apply(app)
    patched = rebuild(stock, original, app)
    # Pin the complete result to the exact image physically tested on an XF1.
    require(sha256(patched) == RELEASE.patched_sha256, "Patched firmware does not match the reviewed output")
    result = validate(patched, RELEASE.patched_crc32)
    require(result["app"] == app, "Repacked application mismatch")
    require(result["resources"] == original["resources"] and result["boot"] == original["boot"],
            "Resources/bootstrap changed")
    return patched
