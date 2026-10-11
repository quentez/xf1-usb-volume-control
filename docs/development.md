# Development and releases

## Tests

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m unittest discover -s tests -v
```

Ordinary tests use synthetic data and mocked USB devices. Integration tests are
optional locally and mandatory in the release workflow. Download the official
file outside the repository, then point the tests at it:

```sh
.venv/bin/xf1-usb-volume download --directory /tmp/xf1-firmware
XF1_TEST_FIRMWARE=/tmp/xf1-firmware/MF1730_20D38E18.fot \
  .venv/bin/python -m unittest discover -s tests -v
```

This verifies a byte-identical unmodified repack and that the final patched
output has the exact SHA-256 of the image tested on a speaker. Corruption tests
check multiple container layers. Tests never flash hardware.

## Build a standalone executable

Build on the target architecture with macOS 15+, Python, and Homebrew libusb:

```sh
brew install python libusb
.venv/bin/python -m pip install . -r requirements-build.txt
.venv/bin/python scripts/build_macos.py
```

The script creates `release/xf1-usb-volume-v0.1.0-macos-ARCH.tar.gz` and a
matching SHA-256 file. It bundles libusb explicitly and runs `doctor` against
the executable. Frozen builds refuse to use a system/Homebrew fallback, so a
successful `doctor` verifies the included library can load.

The archive contains one executable, documentation, third-party license texts,
build versions, and the matching libusb source archive. A custom libusb build
can be used with `--libusb-prefix PREFIX --libusb-source SOURCE_ARCHIVE`; the
builder is responsible for supplying its corresponding source.

Build on each architecture separately. Do not combine two PyInstaller one-file
executables using `lipo`; each includes architecture-specific embedded libraries.
The workflow uses `macos-15` (arm64) and `macos-15-intel` (x86_64), following
[GitHub's runner labels](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).
Binary compatibility with older macOS versions is not claimed.

PyInstaller performs ad-hoc signing. Apple Developer ID signing and notarization
are not configured. No signing secrets are required for the current workflow.
See [PyInstaller's macOS notes](https://pyinstaller.org/en/stable/feature-notes.html)
if adding a signed/notarized release pipeline later.

## Publish a release

1. Update the version in both `pyproject.toml` and `src/xf1_usb_volume/__init__.py`.
2. Run the tests and review the source changes.
3. Commit and push, then create and push a matching tag:

```sh
git tag v0.1.0
git push origin v0.1.0
```

The release workflow tests both architectures, temporarily downloads official
firmware for verification, builds the executables, tests the extracted bundles,
then creates a GitHub Release with both archives and checksums. Only the final
publish job has `contents: write`. Firmware and device logs are never uploaded.

Running the workflow manually from a branch builds downloadable Actions
artifacts without publishing a release. Running it against a version tag also
publishes. The tag and both source versions must match; an existing release is
not silently overwritten.

## Patch scope

This tool supports one firmware layout and two exact whole-file hashes:
official input and the tested patched output. Its replacement callback is
documented in [usb-volume-deferred.S](usb-volume-deferred.S). Original Creative
instructions are checked by hash and are not stored in the repository.

The patch advertises USB master volume and replaces a 50-byte callback so it
posts the existing volume event (`0x7f2`) instead of synchronously writing
amplifier registers. It preserves the original state behavior and uses no new
RAM allocation. USB range conversion remains unchanged. There are 43 changed
application bytes versus stock; resources and bootstrap are unchanged.

Keep downloads, extracted images, firmware packages, device serials and logs
out of commits. The MIT license covers this project's tooling and authored
patch, not Creative firmware or third-party libraries.
