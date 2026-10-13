"""Pinned HTTPS downloads and durable local copies; no USB access."""
import json
import os
from pathlib import Path
import ssl
import tempfile
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, HTTPSHandler

import certifi

from .catalog import RELEASE, get_release
from .firmware import identify, patch_volume, sha256
from . import __version__

LATEST_URL = "https://files.creative.com/creative/bin/firmware/fwureleases/MF1730/MF1730_release.json"


def latest_official_version():
    """Read the official release feed without authorizing any firmware."""
    opener = build_opener(OfficialRedirects(), HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where())))
    request = Request(LATEST_URL, headers={"User-Agent": f"xf1-usb-volume/{__version__}"})
    with opener.open(request, timeout=30) as response:
        check_url(response.geturl())
        if response.status != 200:
            raise ValueError(f"Firmware release feed returned HTTP {response.status}")
        data = response.read(65537)
    if len(data) > 65536:
        raise ValueError("Unexpectedly large firmware release feed")
    metadata = json.loads(data)
    version = metadata.get("latestVersion") if isinstance(metadata, dict) else None
    if not isinstance(version, str) or not version:
        raise ValueError("Firmware release feed has no valid latestVersion")
    return version


def latest_official_release():
    """Check freshness without trusting a feed to authorize unknown firmware."""
    version = latest_official_version()
    if version != RELEASE.version:
        raise ValueError(f"Creative lists official firmware {version}, which this tool has not reviewed. "
                         "Update this tool before restoring the latest release. No firmware was sent.")
    return get_release(version)


def default_directory():
    return Path.home() / "Library/Application Support/xf1-usb-volume/firmware" / RELEASE.version


def check_url(url):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != "files.creative.com"
            or parsed.port not in (None, 443) or parsed.username or parsed.password):
        raise ValueError("Firmware downloads must remain on https://files.creative.com")


class OfficialRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_official(release):
    check_url(release.url)
    opener = build_opener(OfficialRedirects(), HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where())))
    request = Request(release.url, headers={"User-Agent": f"xf1-usb-volume/{__version__}", "Accept-Encoding": "identity"})
    with opener.open(request, timeout=30) as response:
        check_url(response.geturl())
        if response.status != 200:
            raise ValueError(f"Firmware server returned HTTP {response.status}")
        length = response.headers.get("Content-Length")
        if length is not None and int(length) != release.size:
            raise ValueError("Unexpected firmware download size")
        data = response.read(release.size + 1)
    if len(data) != release.size or sha256(data) != release.stock_sha256:
        raise ValueError("Downloaded firmware failed size/SHA-256 validation; nothing saved")
    identify(data)
    return data


def save_copy(path, data):
    """Atomic, no-overwrite installation; identical existing copies are reusable."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError(f"Refusing symlink output: {path}")
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f"Existing file differs; refusing to overwrite: {path}")
        return path
    fd, temporary = tempfile.mkstemp(prefix=".xf1-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), 0o444)
        # Linking is atomic and fails if a competing process created the target.
        os.link(temporary, path)
    finally:
        os.unlink(temporary)
    return path


def download(directory=None, version=RELEASE.version):
    release = get_release(version)
    directory = Path(directory) if directory is not None else default_directory()
    destination = directory / release.filename
    if destination.is_symlink():
        raise ValueError(f"Refusing symlink firmware: {destination}")
    if destination.exists():
        if identify(destination.read_bytes())["kind"] != "official":
            raise ValueError("The cached official file is not official firmware")
        return destination
    return save_copy(destination, fetch_official(release))


def prepare(directory=None, version=RELEASE.version, source=None):
    release = get_release(version)
    directory = Path(directory) if directory is not None else default_directory()
    if source is None:
        official = download(directory, version)
    else:
        data = Path(source).read_bytes()
        if identify(data)["kind"] != "official":
            raise ValueError("--input must be the supported official firmware")
        official = save_copy(directory / release.filename, data)
    patched = patch_volume(official.read_bytes())
    destination = save_copy(directory / release.patched_filename, patched)
    manifest = {
        "firmware_version": release.version,
        "patch": "USB master volume, deferred amplifier update and physical knob synchronization; no fade",
        "official_file": official.name, "official_sha256": release.stock_sha256,
        "patched_file": destination.name, "patched_sha256": release.patched_sha256,
        "flashed": False,
        "note": "Build record only; successful transfer and playback must be verified separately",
    }
    save_copy(directory / "patch-manifest-v2.json", (json.dumps(manifest, indent=2) + "\n").encode())
    return official, destination
