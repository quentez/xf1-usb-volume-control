#!/usr/bin/env python3
"""Regenerate only our authored patch bytes; no manufacturer firmware needed.

Requires GNU RISC-V binutils. Original hook bytes are represented only by their
SHA-256 checksums. Users of the CLI do not need this assembler or script.
"""
import argparse
import hashlib
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
CAVES = {".feedback_core": (0xC608, 0xC800), ".feedback_setup": (0x23410, 0x23600)}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def elf_sections_and_symbols(data):
    require(data[:7] == b"\x7fELF\x01\x01\x01", "Expected ELF32 little endian")
    header = struct.unpack_from("<16sHHIIIIIHHHHHH", data)
    require(header[2] == 243, "Expected RISC-V ELF")
    shoff, shentsize, shnum, shstrndx = header[6], header[11], header[12], header[13]
    require(shentsize == 40, "Unexpected ELF section header size")
    headers = [struct.unpack_from("<10I", data, shoff + i * shentsize)
               for i in range(shnum)]
    strings = headers[shstrndx]
    names = data[strings[4]:strings[4] + strings[5]]

    def name(table, offset):
        return table[offset:table.index(b"\0", offset)].decode("ascii")

    sections, symbols = {}, {}
    for section in headers:
        section_name = name(names, section[0])
        payload = data[section[4]:section[4] + section[5]]
        if section_name in CAVES:
            sections[section_name] = (section[3], payload)
        if section[1] == 2:  # SHT_SYMTAB
            table = headers[section[6]]
            symbol_names = data[table[4]:table[4] + table[5]]
            for offset in range(0, len(payload), section[9]):
                n, value, size, info, other, index = struct.unpack_from("<IIIBBH", payload, offset)
                if n:
                    symbols[name(symbol_names, n)] = value
    require(set(sections) == set(CAVES), "Missing patch sections")
    return sections, symbols


def assemble():
    assembler = shutil.which("riscv64-elf-as")
    linker = shutil.which("riscv64-elf-ld")
    require(assembler and linker, "Install GNU RISC-V binutils (brew install riscv64-elf-binutils)")
    source = ROOT / "docs/usb-volume-feedback.S"
    script = source.with_suffix(".ld")
    with tempfile.TemporaryDirectory(prefix="xf1-feedback-") as temp:
        obj, elf = Path(temp) / "patch.o", Path(temp) / "patch.elf"
        subprocess.run([assembler, "-march=rv32imc", "-mabi=ilp32", str(source), "-o", str(obj)], check=True)
        subprocess.run([linker, "-m", "elf32lriscv", "--no-relax", "-T", str(script), str(obj), "-o", str(elf)], check=True)
        data = elf.read_bytes()
    sections, symbols = elf_sections_and_symbols(data)
    return data, sections, symbols


def jal(source, destination, link=True):
    delta = destination - source
    require(delta % 2 == 0 and -(1 << 20) <= delta < (1 << 20), "JAL out of range")
    bits = delta & 0x1FFFFF
    word = (((bits >> 20) & 1) << 31 | ((bits >> 1) & 0x3FF) << 21 |
            ((bits >> 11) & 1) << 20 | ((bits >> 12) & 0xFF) << 12 |
            (int(link) << 7) | 0x6F)
    return struct.pack("<I", word)


HOOKS = [
    (0xcd02, "b08fe105181275a30eacdcae4ecad1fc90e2c1b2080704642c036c8dbcad1bc9", "feedback_descriptor", "call"),
    (0xdffa, "7106ac410ff7cbc39bf29c69a057deaf1abd2935bae03f7cf5d08a9abad6e3d5", "feedback_reset", "call"),
    (0xe5de, "872a490f87d9d64c0ecc23e428c4d5f45e0cf1a2ce2cfd11dc595099bdd50ca8", "feedback_reset", "call"),
    (0x2b4d8, "2eea4bd95b244e42fcc3c3b8a0ed587cb5adf940c9fbeff939d54a448ddeb1e0", "feedback_poll", "call"),
    (0xe4d6, "5153b0b270300b416c4fe9dc118990e7c0ba2c9746328fc5dc3834b86ca8c4a9", "feedback_get_volume", "call"),
    (0xe470, "66bf185c5951282af71a2881c11531d6d92557af0a34c7030292902f5383ab66", "feedback_get_stat", "jump"),
    (0x6c58, "33900463fd877c7b88cc56cc0c7372330d14a535a59cac1a7d26a07e92b9d47b", "feedback_event", "pointer"),
 ]


def generate():
    _, sections, symbols = assemble()
    patches = []
    for section, (offset, end) in CAVES.items():
        address, code = sections[section]
        require(address == 0x10000000 + offset and len(code) <= end - offset, "Invalid patch bounds")
        patches.append((offset, hashlib.sha256(bytes(len(code))).hexdigest(), code))
    for offset, expected, symbol, kind in HOOKS:
        replacement = (struct.pack("<I", symbols[symbol]) if kind == "pointer" else
                       jal(0x10000000 + offset, symbols[symbol], kind == "call"))
        patches.append((offset, expected, replacement))
    lines = ['"""Generated authored RV32 patch; regenerate with scripts/generate_feedback.py."""',
             'import hashlib', '', f'CAVES = {tuple(CAVES.values())!r}', '', 'PATCHES = (']
    for offset, expected, payload in patches:
        lines.append(f'    (0x{offset:x}, "{expected}", bytes.fromhex(')
        encoded = payload.hex()
        for start in range(0, len(encoded), 80):
            lines.append(f'        "{encoded[start:start+80]}"')
        lines.append('    )),')
    lines.extend([')', '', '', 'def apply(app):',
                 '    """Require all reviewed padding and hook hashes before replacement."""',
                 '    result = bytearray(app)',
                 '    for start, end in CAVES:',
                 '        if result[start:end] != bytes(end - start):',
                 '            raise ValueError(f"Unexpected code padding at {start:#x}")',
                 '    for offset, expected, replacement in PATCHES:',
                 '        original = result[offset:offset + len(replacement)]',
                 '        if hashlib.sha256(original).hexdigest() != expected:',
                 '            raise ValueError(f"Unexpected patch site at {offset:#x}")',
                 '        result[offset:offset + len(replacement)] = replacement',
                 '    return result', ''])
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if checked-in bytes differ")
    args = parser.parse_args()
    path = ROOT / "src/xf1_usb_volume/feedback.py"
    text = generate()
    if args.check:
        require(path.read_text() == text, "Generated feedback patch differs; regenerate and review")
        print("Authored assembly exactly reproduces the packaged patch.")
    else:
        path.write_text(text)
