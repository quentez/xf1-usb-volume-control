#!/usr/bin/env python3
"""Build a macOS release archive containing the CLI, licenses, and libusb source."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import ssl
import subprocess
import sys
import sysconfig
import tarfile
import tomllib
import urllib.request

import certifi
from xf1_usb_volume import __version__

ROOT = Path(__file__).resolve().parents[1]


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def download(url):
    with urllib.request.urlopen(url, timeout=60,
                                context=ssl.create_default_context(cafile=certifi.where())) as response:
        if not response.geturl().startswith("https://"):
            raise RuntimeError("Source archive redirected outside HTTPS")
        data = response.read(20_000_001)
    if len(data) > 20_000_000:
        raise RuntimeError("Unexpectedly large source archive")
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default=f"v{__version__}")
    parser.add_argument("--libusb-prefix", type=Path)
    parser.add_argument("--libusb-source", type=Path,
                        help="Corresponding source archive for a custom libusb build")
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("Build macOS executables on macOS")
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    if args.tag != f"v{version}" or version != __version__:
        parser.error("Tag, pyproject.toml, and package version must match")
    arch = platform.machine()
    if arch not in ("arm64", "x86_64"):
        parser.error(f"Unsupported architecture: {arch}")
    prefix = args.libusb_prefix
    if prefix is None:
        prefix = Path(subprocess.check_output(["brew", "--prefix", "libusb"], text=True).strip())
    native = prefix / "lib/libusb-1.0.dylib"
    if not native.exists():
        parser.error(f"Missing libusb: {native}")
    work = ROOT / "build" / f"bundle-{arch}"
    work.mkdir(parents=True, exist_ok=True)
    # A stable basename lets the frozen program locate the bundled library.
    bundled = work / "libusb-1.0.dylib"
    shutil.copyfile(native, bundled)
    run(sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile",
        "--name", "xf1-usb-volume", "--target-architecture", arch,
        "--paths", str(ROOT / "src"), "--add-binary", f"{bundled}:.",
        "--collect-data", "certifi", "--hidden-import", "usb.backend.libusb1",
        "--distpath", str(work / "dist"), "--workpath", str(work / "pyinstaller"),
        "--specpath", str(work), str(ROOT / "scripts/entrypoint.py"), cwd=ROOT)
    executable = work / "dist/xf1-usb-volume"
    run("codesign", "--verify", "--strict", str(executable))
    run(str(executable), "--version")
    # Frozen backend resolution refuses to fall back to Homebrew/system libusb.
    run(str(executable), "doctor")
    label = f"xf1-usb-volume-{args.tag}-macos-{arch}"
    release = ROOT / "release"
    staging = work / label
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()
    shutil.copy2(executable, staging / "xf1-usb-volume")
    for name in ("README.md", "LICENSE", "THIRD_PARTY.md"):
        shutil.copy2(ROOT / name, staging / name)
    shutil.copytree(ROOT / "docs", staging / "docs")
    licenses = staging / "licenses"
    licenses.mkdir()
    shutil.copy2(prefix / "COPYING", licenses / "libusb-LICENSE.txt")
    python_license = Path(sysconfig.get_path("stdlib")) / "LICENSE.txt"
    if python_license.is_file():
        shutil.copy2(python_license, licenses / "Python-LICENSE.txt")
    else:
        url = f"https://raw.githubusercontent.com/python/cpython/v{platform.python_version()}/LICENSE"
        (licenses / "Python-LICENSE.txt").write_bytes(download(url))
    dependencies = {}
    for name in ("pyusb", "certifi", "pyinstaller", "altgraph", "macholib", "packaging"):
        distribution = importlib.metadata.distribution(name)
        dependencies[name] = distribution.version
        count = 0
        for item in distribution.files or ():
            if Path(item).name.lower().startswith(("license", "copying")):
                source = distribution.locate_file(item)
                if source.is_file():
                    count += 1
                    shutil.copy2(source, licenses / f"{name}-{count}-{source.name}")
        if name in ("pyusb", "certifi", "pyinstaller") and not count:
            raise RuntimeError(f"No license found for bundled component {name}")
    libusb_version = re.search(r"^Version:\s*(.+)$",
                              (prefix / "lib/pkgconfig/libusb-1.0.pc").read_text(), re.M).group(1)
    if args.libusb_source:
        source_data = args.libusb_source.read_bytes()
        source_name = args.libusb_source.name
        source_url = "custom source supplied by builder"
    else:
        formula = (prefix / ".brew/libusb.rb").read_text()
        source_url = re.search(r'^\s*url "(https://[^"\n]+)"', formula, re.M).group(1)
        expected = re.search(r'^\s*sha256 "([a-f0-9]{64})"', formula, re.M).group(1)
        if f"libusb-{libusb_version}." not in source_url:
            raise RuntimeError("libusb source version does not match installed library")
        source_name = source_url.rsplit("/", 1)[1]
        source_data = download(source_url)
        if hashlib.sha256(source_data).hexdigest() != expected:
            raise RuntimeError("libusb source archive checksum mismatch")
    (licenses / source_name).write_bytes(source_data)
    info = {"version": version, "architecture": arch, "built_on_macos": platform.mac_ver()[0],
            "python": platform.python_version(), "dependencies": dependencies,
            "libusb": libusb_version, "libusb_source_url": source_url,
            "libusb_source_sha256": hashlib.sha256(source_data).hexdigest(),
            "code_signing": "ad-hoc; not notarized", "contains_creative_firmware": False}
    (staging / "build-info.json").write_text(json.dumps(info, indent=2) + "\n")
    release.mkdir(exist_ok=True)
    archive = release / f"{label}.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(staging, arcname=label)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(archive.suffix + ".sha256").write_text(f"{digest}  {archive.name}\n")
    print(f"Release archive: {archive}")


if __name__ == "__main__":
    main()
