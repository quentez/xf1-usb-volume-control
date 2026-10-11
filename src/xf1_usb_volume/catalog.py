"""Explicit allowlist. Never follow a 'latest firmware' feed automatically."""
from dataclasses import dataclass


@dataclass(frozen=True)
class FirmwareRelease:
    version: str
    internal_version: str
    filename: str
    patched_filename: str
    url: str
    size: int
    stock_sha256: str
    patched_sha256: str
    stock_crc32: str
    patched_crc32: str


RELEASE = FirmwareRelease(
    version="1.1.260703.1630",
    internal_version="20D38E18",
    filename="MF1730_20D38E18.fot",
    patched_filename="MF1730_20D38E18_usb-volume-v2.fot",
    url="https://files.creative.com/creative/bin/firmware/fwureleases/MF1730/zifs/fc00/MF1730_20D38E18.fot",
    size=979968,
    stock_sha256="dc4c1e5fae2667eb08bf80713f55b9180b3f9dad40ec03e571e19bd1b0b111f0",
    patched_sha256="87e4a54b687b4e25136b7abcad590fdac09ff2f34caf9d7dcd69270e1364f16e",
    stock_crc32="CF4D0F18",
    patched_crc32="8DE1D8C4",
)


def get_release(version=RELEASE.version):
    if version != RELEASE.version:
        raise ValueError(f"Unsupported firmware version {version!r}. Supported: {RELEASE.version}")
    return RELEASE
