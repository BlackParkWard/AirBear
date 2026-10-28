<p align="center">
  <img src="logo.png" width="160" alt="AirBear bear logo"><br>
  <img src="LogoUpdate.png" width="240" alt="AirBear">
</p>

<p align="center"><b>Mirror your iPhone or iPad screen to a Windows PC using the built-in Screen Mirroring button.</b><br>
No app on the phone, no account, no cables.</p>

---

## Contents

- [Requirements](#requirements)
- [Install](#install)
- [Mirror your iPhone](#mirror-your-iphone)
- [Settings](#settings)
- [Troubleshooting](#troubleshooting)
- [Building from source](#building-from-source)
- [How it works](#how-it-works)
- [License](#license)

## Requirements

- A Windows 10 or Windows 11 PC (64-bit)
- An iPhone or iPad with **Screen Mirroring** in Control Center (any recent iOS/iPadOS)
- The PC and the iPhone on the **same Wi-Fi network**. The PC can also be on the same network over an Ethernet cable.

## Install

1. Download **`AirBear.exe`** from the [Releases](https://github.com/BlackParkWard/AirBear/releases) page.
2. Put it anywhere you like (Desktop, Documents, etc.) and double-click it. You don't need an installer.

**The first time you open it:**

- AirBear spends a few seconds getting ready. It unpacks its mirroring engine to `%LOCALAPPDATA%\AirBear`.
- Windows asks **"Do you want to allow this app to make changes to your device?"** Click **Yes**. AirBear adds one firewall rule so your iPhone can find this PC on your local network. This happens only once, and you don't need to change any Windows network settings.
- Windows SmartScreen may warn that the app is from an unknown publisher. Click **More info**, then **Run anyway**.

## Mirror your iPhone

1. Open **AirBear** on the PC. It starts automatically and shows a green **Ready**. If it shows **Off**, click **Start**.
2. On your iPhone, open **Control Center**: swipe down from the top-right corner.
3. Tap **Screen Mirroring** (the two overlapping rectangles).
4. Choose **AirBear** from the list.
5. Your iPhone's screen appears in a window on the PC.

**While mirroring:**

| To... | Do this |
|---|---|
| Go full screen | Press **Alt+Enter** in the mirror window |
| Stop mirroring | On the iPhone, tap **Screen Mirroring → Stop Mirroring**. Or click **Stop** in AirBear |

If **Require a PIN** is on, AirBear shows a 4-digit code the first time you connect. Type it on the iPhone.

## Settings

Click **Settings** at the bottom of the AirBear window.

| Setting | What it does |
|---|---|
| **Name on iPhone** | The name shown in the iPhone's Screen Mirroring list |
| **Quality** | 720p, 1080p or 1440p. Choose 720p on slow or busy Wi-Fi |
| **Frame rate** | 30 or 60 frames per second |
| **Play sound on this PC** | Play the iPhone's audio through the PC's speakers |
| **Sync sound to video** | Keeps sound and lips perfectly matched for watching films, but adds a noticeable delay. Leave it off for the most responsive mirroring |
| **Open in full screen** | Start the mirror window in full screen |
| **Require a PIN** | Ask for a code before anyone can mirror. Recommended on shared Wi-Fi (cafés, hotels, offices) |
| **Start automatically** | Start receiving as soon as AirBear opens |
| **View log** | Technical details, useful when something isn't working |

Changes take effect the next time the receiver starts. Click **Stop** then **Start** to apply them straight away.

## Troubleshooting

**AirBear doesn't appear in the iPhone's Screen Mirroring list**
- Check that the PC and the iPhone are on the same Wi-Fi network, not a guest network. Guest networks and some public networks block devices from seeing each other ("client isolation").
- Make sure AirBear shows **Ready**.
- If you clicked **No** on the Windows permission prompt, close and reopen AirBear and click **Yes**.
- Third-party antivirus or firewall software can block AirBear. Allow `%LOCALAPPDATA%\AirBear\backend\bin\uxplay.exe` in it.

**The mirror lags behind the iPhone**
- Make sure **Sync sound to video** is off.
- Use 5 GHz Wi-Fi rather than 2.4 GHz, or connect the PC to the router with a cable.
- Lower **Quality** to 720p.

**AirBear says "Something went wrong"**
- Open **Settings → View log** and look at the last lines. Including them in a [GitHub issue](https://github.com/BlackParkWard/AirBear/issues) helps a lot.

**Resetting AirBear**
- Delete `%APPDATA%\AirBear` (settings) and `%LOCALAPPDATA%\AirBear` (engine). AirBear sets itself up again the next time it opens.

## Building from source

For developers who want to run or change AirBear.

### Prerequisites

- Windows 10/11 (64-bit)
- [Python 3.12+](https://www.python.org/downloads/) with Pillow and PyInstaller:
  ```powershell
  pip install pillow pyinstaller
  ```
- winget, which is included in Windows 10/11, so `setup.ps1` can install MSYS2. You can also install [MSYS2](https://www.msys2.org) yourself to `C:\msys64`.

### 1. Build the mirroring engine (once)

```powershell
git clone https://github.com/BlackParkWard/AirBear
cd AirBear
powershell -ExecutionPolicy Bypass -File setup.ps1
```

`setup.ps1` does the following, and takes about 10–15 minutes the first time:
1. Installs MSYS2 if it's missing.
2. Installs GStreamer, FFmpeg and the build tools.
3. Builds [UxPlay](https://github.com/FDH2/UxPlay) and installs it to `C:\msys64\ucrt64\bin\uxplay.exe`.

If it stops with download errors (MSYS2 mirrors sometimes rate-limit), just run it again. It resumes where it left off.

### 2. Run from source

```powershell
pythonw airbear.pyw
```

### 3. Build the single-file exe

```powershell
python build.py
```

This produces `dist\AirBear.exe`. It contains the GUI, UxPlay, and only the GStreamer plugins and DLLs UxPlay needs, so it runs on any Windows 10/11 PC with nothing else installed.

### Project layout

| File | Purpose |
|---|---|
| `airbear.pyw` | The app: tkinter GUI, runs and monitors UxPlay, firewall setup |
| `setup.ps1` | Developer setup: MSYS2 + GStreamer, builds UxPlay |
| `build.py` | Bundles UxPlay + GStreamer and packages `AirBear.exe` with PyInstaller |
| `logo.png`, `LogoUpdate.png` | App icon / bear logo and wordmark |

## How it works

iOS Screen Mirroring uses Apple's AirPlay protocol. AirBear is a front end for **[UxPlay](https://github.com/FDH2/UxPlay)**, an open-source AirPlay mirroring server:

- **UxPlay** advertises the PC on the network, handles the AirPlay handshake and decrypts the video and audio streams.
- **GStreamer** decodes the H.264 video and AAC audio, using your graphics card's hardware decoder when one is available. It then shows the video in a Direct3D window.
- **AirBear** starts and stops UxPlay, turns its log into the status you see, manages settings, and sets up the firewall rule.

## License

AirBear bundles UxPlay (GPL-3.0) and GStreamer/FFmpeg components (LGPL/GPL). If you redistribute `AirBear.exe`, you must comply with those licenses, including offering the corresponding source code. The UxPlay license is included in the bundle as `UXPLAY-LICENSE.txt`.

AirPlay, iPhone and iPad are trademarks of Apple Inc. AirBear is not affiliated with or endorsed by Apple.
