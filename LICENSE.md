# AirBear License

Copyright (c) 2026 BlackParkWard. All rights reserved, except as granted below.

AirBear's source code is public so that anyone can read, review and learn from it.
It is **source-available, not open source**: you may use AirBear for any
noncommercial purpose, but you may **not redistribute** it or publish modified
versions of it.

## What is covered by which license

| Part | License |
|---|---|
| Everything in this repository not listed below (`airbear.pyw`, `build.py`, documentation) | [PolyForm Strict 1.0.0](LICENSES/PolyForm-Strict-1.0.0.md) |
| `setup.ps1` (builds UxPlay from source) | [GNU GPL v3.0 or later](LICENSES/GPL-3.0.txt) |
| `assets/` (the AirBear name, bear logo and wordmark) | All rights reserved. Not licensed for any use other than identifying this project |
| Third-party components bundled in `AirBear.exe` | Their own licenses (see below) |

### PolyForm Strict 1.0.0, in short

This summary is not a substitute for the [full license text](LICENSES/PolyForm-Strict-1.0.0.md):

- **You may** download, run and use AirBear for personal, educational, research,
  charitable and other noncommercial purposes.
- **You may not** redistribute AirBear (the source code or `AirBear.exe`), sell it,
  or publish changed versions or works based on it.
- Commercial use is not permitted without separate written permission from the
  copyright holder.

Suggestions and contributions are welcome through issues and pull requests on
[GitHub](https://github.com/BlackParkWard/AirBear).

### Third-party components

`AirBear.exe` bundles the following separately licensed programs and libraries.
Nothing in this license limits the rights those licenses give you:

- **UxPlay**, GNU GPL v3.0. Source: <https://github.com/FDH2/UxPlay>. Each release
  names the exact UxPlay commit it was built from. `setup.ps1` contains the build
  steps and settings used.
- **GStreamer** and its plugins, GNU LGPL v2.1 or later. Source: <https://gitlab.freedesktop.org/gstreamer/gstreamer>
- **FFmpeg** (libav), GNU LGPL/GPL. Source: <https://ffmpeg.org>
- Other libraries from the [MSYS2](https://www.msys2.org) UCRT64 distribution (OpenSSL,
  libplist, GLib and others) under their respective licenses. Source is available from
  <https://github.com/msys2/MINGW-packages>.

## Required Notice

Required Notice: Copyright (c) 2026 BlackParkWard (https://github.com/BlackParkWard/AirBear)
