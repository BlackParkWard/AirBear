"""Build dist/AirBear.exe: a single file containing the GUI plus a private copy of UxPlay
and the GStreamer plugins it uses. Requires setup.ps1 to have been run on the build machine
(end users only need the exe).

    python build.py
"""

import hashlib
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
UCRT = Path(r"C:\msys64\ucrt64")
OBJDUMP = UCRT / "bin" / "objdump.exe"
BUILD = HERE / "build"
STAGE = BUILD / "backend"

# GStreamer plugins UxPlay's pipelines use (see renderers/*.c in UxPlay):
# video  appsrc ! queue ! h264parse/h265parse ! decodebin ! videoconvert ! videoscale ! d3d11videosink
# audio  appsrc ! queue ! avdec_aac/avdec_alac ! audioconvert ! audioresample ! volume ! level ! autoaudiosink
# cover  appsrc ! jpegdec ! videoconvert ! videoscale ! imagefreeze ! textoverlay ! d3d11videosink
PLUGINS = [
    "coreelements", "app", "playback", "typefindfunctions",
    "videoparsersbad", "libav", "d3d11", "d3d12",
    "videoconvertscale", "videofilter", "audioconvert", "audioresample", "volume", "level",
    "autodetect", "wasapi", "wasapi2", "directsound",
    "jpeg", "imagefreeze", "pango",
]


def dll_imports(path):
    out = subprocess.run([str(OBJDUMP), "-p", str(path)], capture_output=True, text=True, check=True).stdout
    return re.findall(r"DLL Name: (\S+)", out)


def collect_dlls(binaries):
    """Every DLL from ucrt64/bin that the given binaries load, recursively."""
    found, todo = {}, list(binaries)
    while todo:
        for name in dll_imports(todo.pop()):
            src = UCRT / "bin" / name
            if name.lower() not in found and src.is_file():  # Windows system DLLs aren't in ucrt64/bin
                found[name.lower()] = src
                todo.append(src)
    return found.values()


def stage():
    shutil.rmtree(STAGE, ignore_errors=True)
    (STAGE / "bin").mkdir(parents=True)
    (STAGE / "lib" / "gstreamer-1.0").mkdir(parents=True)
    (STAGE / "libexec" / "gstreamer-1.0").mkdir(parents=True)

    binaries = [UCRT / "bin" / "uxplay.exe", UCRT / "libexec" / "gstreamer-1.0" / "gst-plugin-scanner.exe"]
    for plugin in PLUGINS:
        path = UCRT / "lib" / "gstreamer-1.0" / f"libgst{plugin}.dll"
        if not path.is_file():
            sys.exit(f"missing GStreamer plugin {path.name}; run setup.ps1 first")
        binaries.append(path)
        shutil.copy2(path, STAGE / "lib" / "gstreamer-1.0")
    shutil.copy2(binaries[0], STAGE / "bin")
    shutil.copy2(binaries[1], STAGE / "libexec" / "gstreamer-1.0")
    for dll in collect_dlls(binaries):
        shutil.copy2(dll, STAGE / "bin")
    shutil.copy2(UCRT / "share" / "doc" / "uxplay" / "LICENSE", STAGE / "UXPLAY-LICENSE.txt")


def pack():
    """Zip the staged backend; the exe unpacks it once to %LOCALAPPDATA%\\AirBear."""
    archive = BUILD / "backend.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(STAGE.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(STAGE).as_posix())
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()[:12]
    (BUILD / "backend.version").write_text(digest)
    return archive


def make_icon():
    """logo.png, cropped to the bear and centred on a square transparent canvas."""
    from PIL import Image
    img = Image.open(HERE / "logo.png").convert("RGBA")
    img = img.crop(img.getchannel("A").getbbox())
    side = max(img.size)
    square = Image.new("RGBA", (side, side))
    square.paste(img, ((side - img.width) // 2, (side - img.height) // 2))
    icon = BUILD / "airbear.ico"
    square.resize((256, 256), Image.LANCZOS).save(
        icon, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    return icon


def main():
    BUILD.mkdir(exist_ok=True)
    stage()
    archive = pack()
    icon = make_icon()
    sep = ";"
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile", "--windowed",
        "--name", "AirBear", "--icon", str(icon),
        "--add-data", f"{archive}{sep}.",
        "--add-data", f"{BUILD / 'backend.version'}{sep}.",
        "--add-data", f"{HERE / 'logo.png'}{sep}.",
        "--add-data", f"{HERE / 'LogoUpdate.png'}{sep}.",
        "--distpath", str(HERE / "dist"), "--workpath", str(BUILD / "pyinstaller"),
        "--specpath", str(BUILD),
        str(HERE / "airbear.pyw"),
    ], check=True)
    exe = HERE / "dist" / "AirBear.exe"
    print(f"\nBuilt {exe} ({exe.stat().st_size / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
