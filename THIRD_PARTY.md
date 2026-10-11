# Third-party components

This repository contains our Python tooling and replacement callback, with no
Creative firmware or extracted application code. Firmware is downloaded by the
user from Creative and processed locally; it is not covered by this project's
MIT license.

Release executables bundle third-party software. The release archive includes
license texts in `licenses/`, with exact build versions in `build-info.json`:

- [CPython](https://www.python.org/): Python Software Foundation license and
  notices for components included in Python's distribution.
- [PyUSB](https://github.com/pyusb/pyusb): BSD-3-Clause.
- [libusb](https://github.com/libusb/libusb): LGPL-2.1-or-later. The archive
  includes its license and the corresponding official source archive. It is
  dynamically loaded from the executable's extracted bundle. To replace it,
  build your preferred libusb and use `scripts/build_macos.py --libusb-prefix`.
- [certifi](https://github.com/certifi/python-certifi): MPL-2.0 CA certificate bundle.
- [PyInstaller](https://pyinstaller.org/): GPL with a distribution exception
  for its bootloader; its notices are included with the bundle.

The [Bluetrum format tools](https://github.com/kagaimiq/bluetrum-tools) were a
reference during format research. No code from that project is vendored here.

No Creative firmware is needed to build the executable. Release validation
downloads the allowlisted firmware temporarily for a reproducibility test;
that file is never added to release assets.
