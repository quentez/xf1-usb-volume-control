# XF1 USB volume control

Enable the macOS volume slider and keyboard volume keys for **Creative XF1
(MF1730)** speakers connected over USB. The patch also defers amplifier updates
so changing volume does not briefly interrupt playback. It adds no fade.

The patch has been flashed and tested on one XF1: native volume controls work,
and the volume-change audio artifact is gone. Wider hardware testing is welcome.

**Known limitation:** turning the speaker's physical volume knob does not update
the volume shown in macOS. Synchronization of knob changes is under investigation.

**No Creative firmware, extracted code, or proprietary applications are included
in this repository or its releases.** The tool downloads one explicitly supported
official firmware from Creative, checks its SHA-256, and patches it locally.
It preserves the official file for restoring the speaker.

## Disclaimer

**Use entirely at your own risk.** This is an unofficial project, unaffiliated
with and unsupported by Creative. Firmware updates can fail and can permanently
damage or disable your speakers, cause data loss, or affect their functionality.
There is no guarantee of recovery or automatic rollback.

To the extent permitted by applicable law, the author and contributors accept
no responsibility or liability for hardware damage, failed updates, loss of
functionality, data loss, or any other damage arising from use of this project.
The software is provided **“AS IS,” without warranty of any kind**. See the
[MIT license](LICENSE).

## Choose how to run it

| Method | What you install |
| --- | --- |
| **Release download** — easiest | One executable; Python and libusb are bundled. No Python, Homebrew, or separate library installation needed. |
| **From source** | Python 3.11+ and libusb; setup below. |

USB operations support macOS only. Release binaries target **macOS 15 or later**,
with separate Apple Silicon and Intel downloads. Downloading, patching, and
verification never send firmware commands to the speaker.

### Option A: download a release

1. Open [Releases](https://github.com/quentez/xf1-usb-volume-control/releases).
2. Download the archive for your Mac and its matching `.sha256` file:
   - `xf1-usb-volume-v…-macos-arm64.tar.gz` for Apple Silicon (M-series).
   - `xf1-usb-volume-v…-macos-x86_64.tar.gz` for Intel.
3. In Terminal, change to the download folder. Verify and extract the archive,
   replacing `VERSION` and `ARCH` with the downloaded names:

```sh
shasum -a 256 -c xf1-usb-volume-vVERSION-macos-ARCH.tar.gz.sha256
tar -xzf xf1-usb-volume-vVERSION-macos-ARCH.tar.gz
cd xf1-usb-volume-vVERSION-macos-ARCH
./xf1-usb-volume doctor
```

The workflow creates releases when a `v…` tag is pushed. If none is published
yet, use the source installation below.

Releases currently use ad-hoc code signing, not an Apple Developer ID or
notarization. macOS may block the first launch. After verifying the download,
use **System Settings → Privacy & Security → Open Anyway** if offered. Do not
disable Gatekeeper globally. Users who prefer can build from source instead.

### Option B: run from source

Install the prerequisites with [Homebrew](https://brew.sh), then clone and install:

```sh
brew install python libusb
git clone https://github.com/quentez/xf1-usb-volume-control.git
cd xf1-usb-volume-control
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/xf1-usb-volume doctor
```

In the commands below, replace `./xf1-usb-volume` with
`.venv/bin/xf1-usb-volume` when running from source. Keep the explicit path when
using `sudo`; you do not need to install the package as root.

## Enable USB volume

### 1. Connect and identify your speaker

Connect power and a USB **data** cable, turn the speaker on, then run:

```sh
./xf1-usb-volume devices
```

Copy the serial number shown. Replace `YOUR_SERIAL` below with that value.
Every write targets that exact serial, even if other USB devices are connected.

### 2. Download and prepare the firmware

Run this **without sudo**:

```sh
./xf1-usb-volume prepare --directory "$HOME/Downloads/xf1-firmware"
```

This saves three files:

| File | Purpose |
| --- | --- |
| `MF1730_20D38E18.fot` | Unmodified official firmware for restore. Keep it. |
| `MF1730_20D38E18_usb-volume-v1.fot` | Verified patch with native USB volume and deferred updates. |
| `patch-manifest.json` | Checksums and build information. |

Firmware files are saved read-only. Repeating preparation reuses identical
copies; it refuses to overwrite a different file. Nothing has been flashed yet.

### 3. Flash the patch

Stop playback. Keep power and USB connected throughout the transfer and reboot.
This command **writes firmware** and temporarily disconnects USB audio:

```sh
sudo ./xf1-usb-volume flash \
  "$HOME/Downloads/xf1-firmware/MF1730_20D38E18_usb-volume-v1.fot" \
  --serial YOUR_SERIAL
```

Administrator access is needed to temporarily release the macOS USB driver.
Every 512-byte transfer is checked. The tool stops on an uncertain transfer and
does not retry it automatically. It saves a unique log in `xf1-firmware/logs/`.

The speaker normally disconnects and reboots after the last chunk. A message
saying the USB disconnect is expected during reboot is normal. Wait for the
speaker to return; acknowledged transfers alone do not prove successful boot.

### 4. Check the result

Select the XF1 in macOS Sound settings. The volume slider and keyboard volume
keys should now work. Start playback quietly, try a few volume changes, and
check that playback stays continuous. Check mute/unmute and your other usual
inputs as well.

## Restore official firmware

This removes the patch, including the advertised native USB-volume capability.
It restores the **supported official release**, not a backup of whichever
firmware was installed before you started. The device's previous version is
not read or backed up by this tool.

Use the official file preserved during preparation:

```sh
sudo ./xf1-usb-volume restore \
  "$HOME/Downloads/xf1-firmware/MF1730_20D38E18.fot" \
  --serial YOUR_SERIAL
```

If you no longer have that file, download a fresh verified copy first, without sudo:

```sh
./xf1-usb-volume download --directory "$HOME/Downloads/xf1-firmware"
```

Restore requires the speaker to remain accessible through its USB update
interface. This is not a recovery tool for an unresponsive/bricked device.

## Supported firmware

Only **Creative XF1 / MF1730**, USB VID/PID **041e:32b9**, is supported.

| Item | Value |
| --- | --- |
| Official release | `1.1.260703.1630` |
| Internal firmware version | `20D38E18` |
| Official SHA-256 | `dc4c1e5fae2667eb08bf80713f55b9180b3f9dad40ec03e571e19bd1b0b111f0` |
| Patched SHA-256 | `a2ff67f5553f7bbe28072ea478e6c15dedf4dff27c02bfef402560d64b261151` |

There is no automatic “latest firmware” selection and no force option for
unknown files. A new firmware version requires separate analysis and an
explicit code update. Download URLs are restricted to Creative's HTTPS host.
Both input and final output hashes are pinned, and the known container,
section, region, and bootstrap checksums are validated.

These checks establish file identity and integrity; they do not guarantee
compatibility with every hardware revision or verify the currently installed
firmware version. Do not use the tool on a different speaker model.

## Other commands and troubleshooting

```sh
./xf1-usb-volume --help
./xf1-usb-volume versions
./xf1-usb-volume verify "$HOME/Downloads/xf1-firmware/MF1730_20D38E18_usb-volume-v1.fot"
sudo ./xf1-usb-volume probe --serial YOUR_SERIAL
```

`probe` performs only a SCSI INQUIRY, with no firmware commands. It temporarily
releases the USB driver, so audio can disconnect even during this probe.

- **No device found:** check power and the USB data cable, then run `devices`
  again. Bluetooth pairing does not provide the USB update connection.
- **libusb unavailable:** source users should run `brew install libusb`.
  Release users should re-extract the complete archive and run `doctor`.
- **Unknown firmware / checksum failure:** do not flash it. Check the supported
  version above. If an existing local file is damaged, move it aside and download
  again; the tool deliberately refuses to overwrite it.
- **Transfer stopped / uncertain write:** do not blindly repeat the flash.
  Keep the log, check whether the speaker reboots and reappears, and establish
  its state before another attempt.
- **Already have the official file:** use `prepare --input /path/to/file.fot
  --directory /path/to/output` to work offline. Unknown files are rejected.

Logs include your device serial and local paths. Redact those before posting
logs in a public issue. Do not upload firmware or extracted vendor code.

## Development and releases

See [development and release instructions](docs/development.md). The GitHub
Actions workflow builds and tests both macOS architectures, bundles Python and
libusb, and attaches archives and SHA-256 files to a GitHub Release when a
version tag is pushed. No firmware is included in those assets.

The source code and our replacement patch are [MIT licensed](LICENSE).
Bundled third-party software retains its own licenses; see
[third-party notices](THIRD_PARTY.md). Creative retains its rights to its
firmware and trademarks.
