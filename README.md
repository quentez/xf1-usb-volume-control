# XF1 USB volume control

Enable the macOS volume slider and keyboard volume keys for **Creative XF1
(MF1730)** speakers over USB. Volume changes keep playback continuous, and
turning the speaker's physical knob updates the volume shown in macOS.

The current patch has been flashed and tested on one XF1. Wider hardware testing
is welcome. No fade is added.

**No Creative firmware, extracted code, or proprietary applications are included
in this repository or its releases.** The tool downloads a known official file
from Creative, verifies it, applies our patch locally, and preserves the official
file for restore.

## Quick start

1. Connect your XF1 to power and your Mac with a USB **data** cable. Turn it on.
2. Download and extract the release for your Mac, or install from source below.
3. Open Terminal in the extracted folder and run:

```sh
./xf1-usb-volume
```

You will see:

```text
XF1 USB volume control 0.2.0

  1. Enable USB volume and knob sync
  2. Restore official firmware
  q. Quit
```

Choose **1** to install the patch, or **2** to return to official firmware.
The tool finds the speaker, downloads and verifies the firmware, prepares the
patch when needed, and shows the exact speaker and version before writing.
If multiple XF1s are connected, it asks which one to use.

Stop playback, then type `FLASH` or `RESTORE` at the final prompt. The tool asks
for your Mac login password through `sudo` when administrator access is needed;
Terminal does not display characters while you type the password. You do not
need to start the interactive tool with `sudo`.

Keep power and USB connected throughout the transfer and reboot. The speaker
normally disconnects briefly after the last chunk. Once it returns, select it
in macOS Sound settings, start playback quietly, and test the keyboard volume
keys, slider, and several physical knob changes.

## Choose how to install

USB operations support macOS only. Self-contained binaries require **macOS 15
or later** and include Python and libusb. No Python, Homebrew, or separate library
installation is needed for the release download.

### Release download — easiest

Open [Releases](https://github.com/quentez/xf1-usb-volume-control/releases/latest)
and download the archive and matching `.sha256` file for your Mac:

| Mac | Archive suffix |
| --- | --- |
| Apple Silicon (M-series) | `macos-arm64.tar.gz` |
| Intel | `macos-x86_64.tar.gz` |

In Terminal, change to your download folder. Verify and extract the archive,
replacing `VERSION` and `ARCH` with the downloaded names:

```sh
shasum -a 256 -c xf1-usb-volume-vVERSION-macos-ARCH.tar.gz.sha256
tar -xzf xf1-usb-volume-vVERSION-macos-ARCH.tar.gz
cd xf1-usb-volume-vVERSION-macos-ARCH
./xf1-usb-volume
```

Releases use ad-hoc code signing, not an Apple Developer ID or notarization.
macOS may block the first launch. After verifying the download, use **System
Settings → Privacy & Security → Open Anyway** if offered. Do not disable
Gatekeeper globally. You can also build from source.

### From source

Install the prerequisites with [Homebrew](https://brew.sh), then clone and install:

```sh
brew install python libusb
git clone https://github.com/quentez/xf1-usb-volume-control.git
cd xf1-usb-volume-control
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/xf1-usb-volume
```

Python 3.11+ is required. Replace `./xf1-usb-volume` in subsequent examples with
`.venv/bin/xf1-usb-volume`. Keep this explicit path when using `sudo` for advanced
commands; the package does not need to be installed as root.

## Official restore and supported firmware

The interactive restore option checks Creative's release feed and downloads the
latest official version **only if it is in this tool's reviewed allowlist**.
If Creative publishes an unreviewed version, the tool stops and asks you to
update the tool. It never flashes an unknown file or silently substitutes an
older version as “latest.” A network connection is required for this check;
the advanced `restore` command can use a preserved official file offline.

Restore installs the listed official release. It does not recover whichever
version was installed before you first used this tool; that previous image is
not read or backed up. Restore needs a functioning USB update interface and
cannot recover an unresponsive/bricked speaker.

Only **Creative XF1 / MF1730**, USB VID/PID **041e:32b9**, is supported.

| Item | Value |
| --- | --- |
| Supported official release | `1.1.260703.1630` |
| Internal firmware version | `20D38E18` |
| Patch revision | `usb-volume-v2` — USB volume, deferred gain updates, knob sync |
| Official SHA-256 | `dc4c1e5fae2667eb08bf80713f55b9180b3f9dad40ec03e571e19bd1b0b111f0` |
| Patched SHA-256 | `87e4a54b687b4e25136b7abcad590fdac09ff2f34caf9d7dcd69270e1364f16e` |

Creative's [release feed](https://files.creative.com/creative/bin/firmware/fwureleases/MF1730/MF1730_release.json)
listed this official version as latest when checked on 2026-10-11 UTC.
Both input and output hashes are pinned. Container, section, region and
bootstrap checksums are also validated. Download URLs are restricted to
Creative's HTTPS host. These checks establish file identity and integrity,
not compatibility with every hardware revision.

The [firmware monitor](https://github.com/quentez/xf1-usb-volume-control/actions/workflows/firmware-check.yml)
checks Creative's feed every three days and opens one issue per newer version,
mentioning @quentez. It remembers closed reports too. New firmware still needs
manual review before this tool can patch or restore it. Maintainers can also
choose **Run workflow** for an immediate check.

## Saved files and logs

By default, downloads and builds are kept under:

```text
~/Library/Application Support/xf1-usb-volume/firmware/1.1.260703.1630/
```

| File | Purpose |
| --- | --- |
| `MF1730_20D38E18.fot` | Untouched official firmware for restore |
| `MF1730_20D38E18_usb-volume-v2.fot` | Exact tested patch with knob sync |
| `patch-manifest-v2.json` | Build details and checksums |
| `logs/` | A unique log for each flash or restore attempt |

Firmware and build manifests are saved read-only. Identical files are reused;
different files are never overwritten. Earlier v1 files and manifests are
preserved when upgrading to v2.

Every 512-byte transfer is checked. The tool stops on an uncertain transfer and
never retries it automatically. A complete transfer still needs a successful
reboot and playback check. Logs contain serial numbers and local paths; redact
those before posting an issue. Do not upload firmware or extracted vendor code.

## Advanced commands

The explicit commands remain available for scripting and offline preparation.
Run `./xf1-usb-volume --help` for all options.

```sh
./xf1-usb-volume doctor
./xf1-usb-volume devices
./xf1-usb-volume versions
./xf1-usb-volume prepare --directory "$HOME/Downloads/xf1-firmware"
./xf1-usb-volume verify "$HOME/Downloads/xf1-firmware/MF1730_20D38E18_usb-volume-v2.fot"
```

After preparation, replace `YOUR_SERIAL` with the value from `devices`:

```sh
sudo ./xf1-usb-volume flash \
  "$HOME/Downloads/xf1-firmware/MF1730_20D38E18_usb-volume-v2.fot" \
  --serial YOUR_SERIAL
```

To restore the preserved official file:

```sh
sudo ./xf1-usb-volume restore \
  "$HOME/Downloads/xf1-firmware/MF1730_20D38E18.fot" \
  --serial YOUR_SERIAL
```

`download` fetches only the supported official file. `prepare --input /path/to/file.fot`
uses a local official copy instead of downloading. `sudo ./xf1-usb-volume probe
--serial YOUR_SERIAL` tests the update transport with SCSI INQUIRY only; it sends
no firmware commands, but temporarily releases the USB driver, so audio can disconnect.

## Troubleshooting

- **No device found:** check power and the USB data cable. Bluetooth pairing does
  not provide the USB update connection.
- **USB identity / language / serial error:** a control request failed before
  flashing. Audio may still work. Reconnect USB or restart the speaker, then
  run the tool again. The serial check is never bypassed.
- **libusb unavailable:** source users should run `brew install libusb`. Release
  users should re-extract the complete archive and run `doctor`.
- **Unknown firmware / checksum failure:** use only the supported files. Move a
  damaged cached file aside before downloading again; the tool will not overwrite it.
- **Transfer stopped / uncertain write:** do not blindly repeat the flash. Keep
  the log and establish whether the speaker reboots and reappears before retrying.
- **Interactive setup needs a terminal:** launch the executable in Terminal.
  Piped input cannot start interactive flashing; use explicit commands for scripting.

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

## Development and releases

See [development and release instructions](docs/development.md). GitHub Actions
builds and tests both macOS architectures and publishes self-contained archives
and SHA-256 files when a version tag is pushed. No firmware is included.

The tool and our authored patches are [MIT licensed](LICENSE). Bundled third-party
software retains its own licenses; see [third-party notices](THIRD_PARTY.md).
Creative retains its rights to its firmware and trademarks.
