"""FOT format primitives. No firmware or extracted application code is included."""
import binascii
import struct

POLYNOMIAL = 0xA3000000


def step(key):
    for _ in range(8):
        key = (key >> 1) ^ (POLYNOMIAL if key & 1 else 0)
    return key


TABLE = tuple(step(i) for i in range(256))


def crypt(data, key):
    result = bytearray(data)
    for i in range(len(result)):
        result[i] ^= key & 255
        key = (key >> 8) ^ TABLE[key & 255]
    return bytes(result)


def crc16(data, seed=0xFFFF):
    return binascii.crc_hqx(data, seed)


def section(data, offset, name):
    if offset < 0 or offset + 16 > len(data):
        raise ValueError(f"{name}: header out of bounds")
    magic, header_size, size, flags, checksum = struct.unpack_from("<4sIIHH", data, offset)
    if magic != bytes(c | 0x80 for c in name.encode()):
        raise ValueError(f"{name}: unexpected section magic")
    if crc16(data[offset:offset+14]) != checksum:
        raise ValueError(f"{name}: section header CRC mismatch")
    if not size or flags != 0x10:
        raise ValueError(f"{name}: unsupported empty section or encryption flags")
    blocks = (size + 511) // 512
    if header_size < 16 + blocks * 2 or offset + header_size + blocks * 512 > len(data):
        raise ValueError(f"{name}: invalid header size or payload bounds")
    return dict(name=name, offset=offset, header_size=header_size,
                size=size, flags=flags, blocks=blocks)


def get_block(data, sec, index):
    checksum = struct.unpack_from("<H", data, sec["offset"] + 16 + index * 2)[0]
    start = sec["offset"] + sec["header_size"] + index * 512
    return data[start:start+512], checksum


def decode_section(data, sec, key):
    decoded = bytearray()
    for block in range(sec["blocks"]):
        ciphertext, checksum = get_block(data, sec, block)
        plaintext = crypt(ciphertext, key ^ checksum)
        if crc16(plaintext, block + 1) != checksum:
            raise ValueError(f"{sec['name']}: block {block} CRC mismatch")
        decoded.extend(plaintext)
    return bytes(decoded[:sec["size"]])


def resource_entries(data):
    if data[:4] != bytes.fromhex("c5ced4d2") or len(data) < 32:
        raise ValueError("Missing resource ENTR directory")
    count = struct.unpack_from("<I", data, 28)[0]
    if 32 + count * 32 > len(data):
        raise ValueError("Resource directory out of bounds")
    entries = []
    names = set()
    for i in range(count):
        raw_name, address, size = struct.unpack_from("<24sII", data, 32 + i * 32)
        name = raw_name.split(b"\0", 1)[0].decode("ascii")
        offset = address - 0x11000000
        if not name or name in (".", "..") or "/" in name or "\\" in name or name in names:
            raise ValueError(f"Unsafe or duplicate resource name: {name!r}")
        if offset < 32 + count * 32 or offset + size > len(data):
            raise ValueError(f"Resource out of bounds: {name}")
        names.add(name)
        entries.append(dict(name=name, offset=offset, address=address, size=size))
    return entries
