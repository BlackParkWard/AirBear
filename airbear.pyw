"""AirBear - mirror your iPhone screen to Windows using iOS Screen Mirroring (AirPlay).

The AirPlay protocol itself is handled by UxPlay (https://github.com/FDH2/UxPlay),
which setup.ps1 builds and installs. This file is the GUI that configures, starts,
stops and monitors it.
"""

import json
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import threading
import tkinter as tk
from collections import deque
from pathlib import Path

from PIL import Image, ImageDraw, ImageTk

APP_NAME = "AirBear"
HERE = Path(__file__).resolve().parent
FROZEN = getattr(sys, "frozen", False)  # running as the single-file AirBear.exe
BUNDLE = Path(getattr(sys, "_MEIPASS", HERE))  # where PyInstaller unpacked our data files
ASSETS = BUNDLE  # logo.png (bear), LogoUpdate.png (wordmark)
SETTINGS_FILE = Path(os.environ.get("APPDATA", HERE)) / APP_NAME / "settings.json"
# The exe carries UxPlay + GStreamer as backend.zip and unpacks it here once per version.
# A fixed location (not PyInstaller's per-run temp dir) keeps the firewall rule valid.
DATA_DIR = Path(os.environ.get("LOCALAPPDATA", HERE)) / APP_NAME
BACKEND_DIR = DATA_DIR / "backend"
UXPLAY_CANDIDATES = [
    BACKEND_DIR / "bin" / "uxplay.exe",
    Path(r"C:\msys64\ucrt64\bin\uxplay.exe"),
]

DEFAULTS = {
    "name": APP_NAME,
    "resolution": "1920x1080",
    "fps": "60",
    "fullscreen": False,
    "audio": True,
    "pin": False,
    "sync_av": False,  # replaces "low_latency": fast mode is now the default for everyone
    "autostart": True,
}

# Palette (ACCENT and TEXT are taken from the logo)
BG = "#ffffff"
TEXT = "#1b1b1b"
MUTED = "#8a8a8e"
SUBTLE = "#f2f2f4"
SUBTLE_HOVER = "#e6e6ea"
DIVIDER = "#eeeef0"
SWITCH_OFF = "#dcdce0"
ACCENT = "#ff5757"
ACCENT_HOVER = "#f04545"
STATE_COLORS = {
    "stopped": "#c7c7cc",
    "starting": "#ffb340",
    "ready": "#34c759",
    "connected": "#ffb340",
    "mirroring": ACCENT,
    "error": "#d70015",
}

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
RE_ACCEPT = re.compile(r"Accepted \S+ client on socket (\d+)")
RE_CLOSE = re.compile(r"(?:Connection closed on socket|Removing connection for socket) (\d+)")
RE_DEVICE = re.compile(r"connection request from (.+?) \((.*?)\) with deviceID")
RE_PIN = re.compile(r'ENTER PIN = "(\d+)"')
RE_MAC = re.compile(r"using system MAC address (\S+)")


def bundled_backend_ready():
    version = (BUNDLE / "backend.version").read_text().strip()
    marker = BACKEND_DIR / "version.txt"
    return marker.is_file() and marker.read_text().strip() == version


def unpack_backend():
    """Unpack the bundled UxPlay + GStreamer (first launch, or after an AirBear update)."""
    import zipfile
    shutil.rmtree(BACKEND_DIR, ignore_errors=True)
    with zipfile.ZipFile(BUNDLE / "backend.zip") as zf:
        zf.extractall(BACKEND_DIR)
    (DATA_DIR / "registry.bin").unlink(missing_ok=True)  # stale GStreamer plugin cache
    shutil.copy2(BUNDLE / "backend.version", BACKEND_DIR / "version.txt")
    return BACKEND_DIR / "bin" / "uxplay.exe"


def find_uxplay():
    if FROZEN:
        return BACKEND_DIR / "bin" / "uxplay.exe" if bundled_backend_ready() else None
    for path in UXPLAY_CANDIDATES:
        if path.is_file():
            return path
    found = shutil.which("uxplay")
    return Path(found) if found else None


FIREWALL_RULE = "AirBear (UxPlay)"


def firewall_rule_exists(exe):
    """True if our rule exists and points at this uxplay.exe."""
    result = subprocess.run(["netsh", "advfirewall", "firewall", "show", "rule", f"name={FIREWALL_RULE}",
                             "verbose"], capture_output=True, text=True, errors="replace",
                            creationflags=subprocess.CREATE_NO_WINDOW)
    return result.returncode == 0 and str(exe).lower() in result.stdout.lower()


def run_elevated(exe, params):
    """Run a hidden command as administrator (one UAC prompt). Returns False if the user declines."""
    import ctypes
    from ctypes import wintypes

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND),
                    ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR),
                    ("lpParameters", wintypes.LPCWSTR), ("lpDirectory", wintypes.LPCWSTR),
                    ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE), ("lpIDList", ctypes.c_void_p),
                    ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY), ("dwHotKey", wintypes.DWORD),
                    ("hIconOrMonitor", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]

    SEE_MASK_NOCLOSEPROCESS, SW_HIDE = 0x40, 0
    info = SHELLEXECUTEINFOW(cbSize=ctypes.sizeof(SHELLEXECUTEINFOW), fMask=SEE_MASK_NOCLOSEPROCESS,
                             lpVerb="runas", lpFile=exe, lpParameters=params, nShow=SW_HIDE)
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
        return False  # UAC declined or failed
    ctypes.windll.kernel32.WaitForSingleObject(info.hProcess, 60_000)
    ctypes.windll.kernel32.CloseHandle(info.hProcess)
    return True


def add_firewall_rule(exe):
    """Let iPhones on the local network reach uxplay.exe, whatever the network's profile
    (Public included), so users never have to change Windows network settings. Rules that
    Windows' own "allow access?" popup made for uxplay.exe are removed first: a Cancel
    there creates Block rules, which would override ours."""
    prog = str(exe)
    script = (f'netsh advfirewall firewall delete rule name=all program="{prog}" & '
              f'netsh advfirewall firewall delete rule name="{FIREWALL_RULE}" & '
              f'netsh advfirewall firewall add rule name="{FIREWALL_RULE}" dir=in action=allow '
              f'program="{prog}" profile=any remoteip=localsubnet enable=yes')
    return run_elevated("cmd.exe", f'/c "{script}"') and firewall_rule_exists(exe)


def load_settings():
    try:
        return {**DEFAULTS, **json.loads(SETTINGS_FILE.read_text("utf-8"))}
    except (OSError, ValueError):
        return dict(DEFAULTS)


def save_settings(settings):
    try:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(settings, indent=2), "utf-8")
    except OSError:
        pass


def local_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # no packets are sent for UDP connect
            return s.getsockname()[0]
    except OSError:
        return "unknown"


class Receiver:
    """Runs uxplay.exe and turns its log output into state events on a queue."""

    def __init__(self, events):
        self.events = events
        self.proc = None
        self.sockets = set()

    @property
    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def build_args(self, exe, s):
        width, height = s["resolution"].split("x")
        args = [str(exe), "-n", s["name"].strip() or APP_NAME, "-nh",
                "-s", f"{width}x{height}@{s['fps']}", "-fps", s["fps"],
                "-vs", "d3d11videosink"]
        if s["fullscreen"]:
            args.append("-fs")
        if not s["audio"]:
            args.append("-a")
        if s["pin"]:
            args.append("-pin")
        if not s["sync_av"]:
            # UxPlay's default holds each video frame until the (later-arriving) audio with the
            # same timestamp plays, which adds noticeable delay. Show frames as soon as decoded.
            args += ["-vsync", "no"]
        if s.get("mac"):  # skips UxPlay's ~10 s MAC address lookup on Windows
            args += ["-m", s["mac"]]
        return args

    def start(self, exe, settings):
        env = os.environ.copy()
        bindir = str(exe.parent)
        env["PATH"] = bindir + os.pathsep + env.get("PATH", "")
        # Both MSYS2 and the bundled backend use the layout bin/, lib/gstreamer-1.0/, libexec/.
        # Pin GStreamer to these plugins so another GStreamer install on the PC can't interfere.
        root = exe.parent.parent
        plugins = root / "lib" / "gstreamer-1.0"
        scanner = root / "libexec" / "gstreamer-1.0" / "gst-plugin-scanner.exe"
        if plugins.is_dir():
            env["GST_PLUGIN_SYSTEM_PATH"] = str(plugins)
            env.pop("GST_PLUGIN_PATH", None)
        if scanner.is_file():
            env["GST_PLUGIN_SCANNER"] = str(scanner)
        if FROZEN:
            env["GST_REGISTRY"] = str(DATA_DIR / "registry.bin")
        args = self.build_args(exe, settings)
        self.sockets.clear()
        self.events.put(("log", "$ " + subprocess.list2cmdline(args)))
        self.proc = subprocess.Popen(
            args, cwd=bindir, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
        threading.Thread(target=self._read, args=(self.proc,), daemon=True).start()

    def stop(self):
        proc, self.proc = self.proc, None
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()

    def _read(self, proc):
        for raw in proc.stdout:
            line = ANSI.sub("", raw).rstrip()
            if line:
                self.events.put(("log", line))
                self._parse(line)
        code = proc.wait()
        if proc is self.proc:  # exited on its own, not via stop()
            self.proc = None
            self.events.put(("exited", code))

    def _parse(self, line):
        if "Initialized server socket" in line:
            self.events.put(("state", "ready"))
        elif m := RE_MAC.search(line):
            self.events.put(("mac", m.group(1)))
        elif m := RE_DEVICE.search(line):
            self.events.put(("device", m.group(1)))
        elif m := RE_PIN.search(line):
            self.events.put(("pin", m.group(1)))
        elif "Begin streaming" in line or "on_video_play" in line:
            self.events.put(("state", "mirroring"))
        elif m := RE_ACCEPT.search(line):
            self.sockets.add(m.group(1))
            self.events.put(("state", "connected"))
        elif m := RE_CLOSE.search(line):
            self.sockets.discard(m.group(1))
            if not self.sockets:
                self.events.put(("state", "ready"))
        elif "*** ERROR" in line and ("raop" in line or "dnssd" in line or "socket" in line):
            self.events.put(("error", line.replace("*** ERROR:", "").strip()))


def trimmed(path):
    """Load a PNG and crop away its transparent padding."""
    img = Image.open(path).convert("RGBA")
    return img.crop(img.getchannel("A").getbbox())


class Ui:
    """DPI-scaled sizes plus a cache of antialiased shapes (Tk's canvas can't antialias)."""

    def __init__(self, root):
        self.scale = root.winfo_fpixels("1i") / 96
        self.cache = {}

    def px(self, n):
        return max(1, round(n * self.scale))

    def image(self, key, draw, w, h):
        """Render draw(ImageDraw, w, h) at 4x and downsample, for smooth edges."""
        if key not in self.cache:
            w, h, s = self.px(w), self.px(h), 4
            big = Image.new("RGBA", (w * s, h * s))
            draw(ImageDraw.Draw(big), w * s, h * s)
            self.cache[key] = ImageTk.PhotoImage(big.resize((w, h), Image.LANCZOS))
        return self.cache[key]

    def pill(self, w, h, fill):
        return self.image(("pill", w, h, fill), lambda d, W, H: d.rounded_rectangle(
            (0, 0, W - 1, H - 1), H // 2, fill=fill), w, h)

    def dot(self, d, fill):
        return self.image(("dot", d, fill), lambda dr, W, H: dr.ellipse((0, 0, W - 1, H - 1), fill=fill), d, d)

    def logo(self, path, height):
        key = ("logo", path, height)
        if key not in self.cache:
            img = trimmed(path)
            h = self.px(height)
            self.cache[key] = ImageTk.PhotoImage(img.resize((round(img.width * h / img.height), h), Image.LANCZOS))
        return self.cache[key]


class PillButton(tk.Label):
    """Rounded button: a pill image with the text drawn over it."""

    def __init__(self, master, ui, command, width=300, height=46):
        super().__init__(master, bg=master["bg"], bd=0, cursor="hand2", compound="center",
                         font=("Segoe UI Semibold", 11))
        self.ui, self.command, self.size = ui, command, (width, height)
        self.colors = (ACCENT, ACCENT_HOVER, "#ffffff")
        self.hover = False
        self.bind("<Enter>", lambda e: self._paint(True))
        self.bind("<Leave>", lambda e: self._paint(False))
        self.bind("<Button-1>", lambda e: self.command())

    def set_style(self, text, bg, hover, fg="#ffffff"):
        self.colors = (bg, hover, fg)
        self.config(text=text)
        self._paint(self.hover)

    def _paint(self, hover):
        self.hover = hover
        bg, hover_bg, fg = self.colors
        self.config(image=self.ui.pill(*self.size, hover_bg if hover else bg), fg=fg)


class Toggle(tk.Label):
    """iOS-style switch bound to a BooleanVar."""

    def __init__(self, master, ui, var):
        super().__init__(master, bg=master["bg"], bd=0, cursor="hand2")
        self.ui, self.var = ui, var
        self.bind("<Button-1>", lambda e: var.set(not var.get()))
        var.trace_add("write", lambda *_: self._paint())
        self._paint()

    def _paint(self):
        on = self.var.get()

        def draw(d, w, h):
            d.rounded_rectangle((0, 0, w - 1, h - 1), h // 2, fill=ACCENT if on else SWITCH_OFF)
            pad = h // 9
            knob = h - 2 * pad
            x = w - pad - knob if on else pad
            d.ellipse((x, pad, x + knob, pad + knob), fill="#ffffff")

        self.config(image=self.ui.image(("toggle", on), draw, 42, 26))


class Choice(tk.Frame):
    """A row of chips bound to a StringVar; the selected chip is filled."""

    def __init__(self, master, ui, var, options):
        super().__init__(master, bg=master["bg"])
        self.ui, self.var, self.chips = ui, var, {}
        for value, text in options:
            chip = tk.Label(self, text=text, compound="center", bd=0, cursor="hand2",
                            bg=master["bg"], font=("Segoe UI", 9))
            chip.pack(side="left", padx=(ui.px(4), 0))
            chip.bind("<Button-1>", lambda e, v=value: var.set(v))
            self.chips[value] = chip
        var.trace_add("write", lambda *_: self._paint())
        self._paint()

    def _paint(self):
        for value, chip in self.chips.items():
            on = value == self.var.get()
            chip.config(image=self.ui.pill(56, 28, TEXT if on else SUBTLE), fg="#ffffff" if on else TEXT)


class App:
    def __init__(self, root):
        self.root = root
        self.events = queue.Queue()
        self.receiver = Receiver(self.events)
        self.settings = load_settings()
        self.state = "stopped"
        self.device = None
        self.log_lines = deque(maxlen=2000)
        self.log_window = None

        self.ui = ui = Ui(root)
        root.title(APP_NAME)
        root.configure(bg=BG)
        root.geometry(f"{ui.px(380)}x{ui.px(590)}")
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.iconphoto(True, self._window_icon())

        self.vars = {
            "name": tk.StringVar(value=self.settings["name"]),
            "resolution": tk.StringVar(value=self.settings["resolution"]),
            "fps": tk.StringVar(value=self.settings["fps"]),
        }
        for key in ("fullscreen", "audio", "pin", "sync_av", "autostart"):
            self.vars[key] = tk.BooleanVar(value=self.settings[key])
        for var in self.vars.values():
            var.trace_add("write", self.on_setting_changed)

        self.main_page = self._build_main()
        self.settings_page = self._build_settings()
        self.show_page(self.main_page)
        self.apply_state("stopped")

        self.exe = find_uxplay()
        if FROZEN and not self.exe:
            self.apply_state("starting", "Getting AirBear ready.\nThis only happens the first time.")
            threading.Thread(target=self._unpack, daemon=True).start()
        elif not self.exe:
            self.show_missing_backend()
        elif self.settings["autostart"]:
            root.after(300, self.start)
        root.after(100, self.poll_events)

    def _unpack(self):
        try:
            self.events.put(("unpacked", unpack_backend()))
        except OSError as exc:
            self.events.put(("unpacked", exc))

    # ---------- UI construction ----------

    def _window_icon(self):
        img = trimmed(ASSETS / "logo.png")
        side = max(img.size)
        square = Image.new("RGBA", (side, side))
        square.paste(img, ((side - img.width) // 2, (side - img.height) // 2))
        self._icon = ImageTk.PhotoImage(square.resize((64, 64), Image.LANCZOS))
        return self._icon

    def _link(self, parent, text, command, **kw):
        link = tk.Label(parent, text=text, bg=parent["bg"], fg=MUTED, cursor="hand2",
                        font=("Segoe UI", 9), **kw)
        link.bind("<Button-1>", lambda e: command())
        link.bind("<Enter>", lambda e: link.config(fg=TEXT))
        link.bind("<Leave>", lambda e: link.config(fg=MUTED))
        return link

    def _build_main(self):
        ui, px = self.ui, self.ui.px
        page = tk.Frame(self.root, bg=BG)

        tk.Label(page, image=ui.logo(ASSETS / "logo.png", 64), bg=BG).pack(pady=(px(48), 0))
        tk.Label(page, image=ui.logo(ASSETS / "LogoUpdate.png", 24), bg=BG).pack(pady=(px(14), 0))

        row = tk.Frame(page, bg=BG)
        row.pack(pady=(px(52), 0))
        self.dot = tk.Label(row, bg=BG, bd=0)
        self.dot.pack(side="left", padx=(0, px(8)))
        self.status_title = tk.Label(row, bg=BG, fg=TEXT, font=("Segoe UI Semibold", 15))
        self.status_title.pack(side="left")
        self.status_body = tk.Label(page, bg=BG, fg=MUTED, font=("Segoe UI", 10),
                                    justify="center", wraplength=px(300))
        self.status_body.pack(pady=(px(8), 0))
        self.pin_label = tk.Label(page, bg=BG, fg=TEXT, font=("Segoe UI Light", 32))

        footer = tk.Frame(page, bg=BG)
        footer.pack(side="bottom", fill="x", pady=(0, px(18)))
        self._link(footer, "Settings", lambda: self.show_page(self.settings_page)).pack()
        self.action = PillButton(page, ui, self.toggle)
        self.action.pack(side="bottom", pady=(0, px(16)))
        self.notice = tk.Label(page, bg=BG, fg=MUTED, font=("Segoe UI", 9),
                               justify="center", wraplength=px(300))
        self.notice.pack(side="bottom", pady=(0, px(10)))
        return page

    def _build_settings(self):
        ui, px = self.ui, self.ui.px
        page = tk.Frame(self.root, bg=BG)

        head = tk.Frame(page, bg=BG)
        head.pack(fill="x", padx=px(16), pady=(px(16), px(8)))
        back = self._link(head, "‹  Back", lambda: self.show_page(self.main_page))
        back.config(font=("Segoe UI", 10))
        back.pack(side="left")
        tk.Label(page, text="Settings", bg=BG, fg=TEXT, font=("Segoe UI Semibold", 15)
                 ).pack(anchor="w", padx=px(24), pady=(0, px(10)))

        body = tk.Frame(page, bg=BG)
        body.pack(fill="x", padx=px(24))

        def row(label, hint=None):
            if body.winfo_children():
                tk.Frame(body, bg=DIVIDER, height=1).pack(fill="x")
            r = tk.Frame(body, bg=BG, height=px(48))
            r.pack(fill="x")
            r.pack_propagate(False)
            text = tk.Frame(r, bg=BG)
            text.pack(side="left")
            tk.Label(text, text=label, bg=BG, fg=TEXT, font=("Segoe UI", 10)).pack(anchor="w")
            if hint:
                tk.Label(text, text=hint, bg=BG, fg=MUTED, font=("Segoe UI", 8)).pack(anchor="w")
            return r

        entry = tk.Entry(row("Name on iPhone"), textvariable=self.vars["name"], font=("Segoe UI", 10),
                         relief="flat", bg=SUBTLE, fg=TEXT, insertbackground=TEXT, width=14, justify="right",
                         highlightthickness=px(1), highlightbackground=SUBTLE, highlightcolor=ACCENT)
        entry.pack(side="right", ipady=px(4), ipadx=px(6))
        Choice(row("Quality"), ui, self.vars["resolution"],
               [("1280x720", "720p"), ("1920x1080", "1080p"), ("2560x1440", "1440p")]).pack(side="right")
        Choice(row("Frame rate"), ui, self.vars["fps"], [("30", "30"), ("60", "60")]).pack(side="right")
        for key, text, hint in (("audio", "Play sound on this PC", None),
                                ("sync_av", "Sync sound to video", "Best for films, but adds delay"),
                                ("fullscreen", "Open in full screen", None),
                                ("pin", "Require a PIN", None),
                                ("autostart", "Start automatically", None)):
            Toggle(row(text, hint), ui, self.vars[key]).pack(side="right")

        footer = tk.Frame(page, bg=BG)
        footer.pack(side="bottom", fill="x", padx=px(24), pady=(0, px(18)))
        self._link(footer, "View log", self.open_log).pack(side="left")
        self.restart_hint = tk.Label(page, bg=BG, fg=MUTED, font=("Segoe UI", 9),
                                     justify="left", wraplength=px(330))
        self.restart_hint.pack(side="bottom", anchor="w", padx=px(24), pady=(0, px(8)))
        return page

    def show_page(self, page):
        for p in (self.main_page, self.settings_page):
            p.pack_forget()
        page.pack(fill="both", expand=True)
        self.root.focus_set()  # don't leave the cursor in the name field

    # ---------- behaviour ----------

    def current_settings(self):
        return {**self.settings, **{k: v.get() for k, v in self.vars.items()}}

    def on_setting_changed(self, *_):
        self.settings = self.current_settings()
        save_settings(self.settings)
        if self.receiver.running:
            self.restart_hint.config(text="Changes apply the next time AirBear starts receiving.")
        if self.state == "ready":
            self.apply_state("ready")  # the name shown in the instructions may have changed

    def toggle(self):
        if self.receiver.running:
            self.stop()
        else:
            self.start()

    def start(self):
        if self.state == "starting":
            return
        self.exe = self.exe or find_uxplay()
        if not self.exe:
            self.show_missing_backend()
            return
        self.restart_hint.config(text="")
        self.notice.config(text="")
        self.device = None
        if not firewall_rule_exists(self.exe):
            self.apply_state("starting", "Windows will ask for permission so your iPhone "
                                         "can find this PC. This only happens once.")
            threading.Thread(target=lambda: self.events.put(("firewall", add_firewall_rule(self.exe))),
                             daemon=True).start()
            return
        self.launch()

    def launch(self):
        try:
            self.receiver.start(self.exe, self.current_settings())
        except OSError as exc:
            self.apply_state("error", f"Couldn't start: {exc}")
            return
        self.apply_state("starting")

    def stop(self):
        self.receiver.stop()
        self.restart_hint.config(text="")
        self.apply_state("stopped")

    def apply_state(self, state, detail=None):
        self.state = state
        name = self.vars["name"].get().strip() or APP_NAME
        device = self.device or "Your iPhone"
        titles = {
            "stopped": "Off",
            "starting": "Starting",
            "ready": "Ready",
            "connected": "Connecting",
            "mirroring": "Mirroring",
            "error": "Something went wrong",
        }
        bodies = {
            "stopped": "Start AirBear to show your iPhone's screen on this PC.",
            "starting": "Just a moment.",
            "ready": (f"On your iPhone, open Control Center, tap Screen Mirroring and choose “{name}”.\n\n"
                      "Both devices need to be on the same Wi-Fi."),
            "connected": f"{device} is connecting.",
            "mirroring": f"{device} is on screen.\nPress Alt+Enter for full screen.",
            "error": "",
        }
        self.dot.config(image=self.ui.dot(10, STATE_COLORS[state]))
        self.status_title.config(text=titles[state])
        self.status_body.config(text=detail or bodies[state])
        if state in ("stopped", "error", "ready"):
            self.pin_label.pack_forget()
        self.action.command = self.toggle
        if self.receiver.running or state == "starting":
            self.action.set_style("Stop", SUBTLE, SUBTLE_HOVER, fg=TEXT)
        else:
            self.action.set_style("Try again" if state == "error" else "Start", ACCENT, ACCENT_HOVER)

    def show_pin(self, pin):
        self.pin_label.config(text=" ".join(pin))
        self.pin_label.pack(after=self.status_body, pady=(self.ui.px(12), 0))
        self.status_title.config(text="Enter this PIN on your iPhone")

    def show_missing_backend(self):
        self.apply_state("error", "The mirroring engine (UxPlay) isn't installed yet. "
                                  "Setup installs it and takes about 10 minutes.")
        self.action.command = self.run_setup
        self.action.set_style("Run setup", ACCENT, ACCENT_HOVER)

    def run_setup(self):
        script = HERE / "setup.ps1"
        subprocess.Popen(["powershell", "-NoExit", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                         creationflags=subprocess.CREATE_NEW_CONSOLE)
        self.status_body.config(text="Setup is running in another window. When it says Done, "
                                     "close it and click Start.")
        self.action.command = self.toggle
        self.action.set_style("Start", ACCENT, ACCENT_HOVER)

    def open_log(self):
        if self.log_window and self.log_window.winfo_exists():
            self.log_window.lift()
            return
        win = self.log_window = tk.Toplevel(self.root, bg=BG)
        win.title(f"{APP_NAME} log")
        win.geometry(f"{self.ui.px(640)}x{self.ui.px(360)}")
        self.log = tk.Text(win, bg="#1b1b1b", fg="#d1d1d6", relief="flat", font=("Consolas", 9),
                           wrap="none", padx=10, pady=8)
        self.log.pack(fill="both", expand=True)
        self.log.insert("end", "\n".join(self.log_lines) + "\n" if self.log_lines else "")
        self.log.see("end")
        self.log.config(state="disabled")

    def append_log(self, line):
        self.log_lines.append(line)
        if self.log_window and self.log_window.winfo_exists():
            self.log.config(state="normal")
            self.log.insert("end", line + "\n")
            self.log.see("end")
            self.log.config(state="disabled")

    def poll_events(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "log":
                    self.append_log(value)
                elif kind == "state":
                    if value == "connected" and self.state == "mirroring":
                        continue  # extra sockets open during a session
                    if value == "ready":
                        self.device = None
                    self.apply_state(value)
                elif kind == "device":
                    self.device = value
                    if self.state != "mirroring":
                        self.apply_state("connected")
                elif kind == "pin":
                    self.show_pin(value)
                elif kind == "unpacked":
                    if isinstance(value, Exception):
                        self.apply_state("error", f"Couldn't prepare AirBear: {value}")
                        continue
                    self.exe = value
                    self.apply_state("stopped")
                    if self.settings["autostart"]:
                        self.start()
                elif kind == "firewall":
                    if self.state != "starting":
                        continue  # user pressed Stop while the permission prompt was up
                    self.launch()
                    if not value:
                        self.notice.config(text="Permission wasn't granted, so your iPhone may not "
                                                "find this PC. Restart AirBear to try again.")
                elif kind == "mac":
                    self.settings["mac"] = value
                    save_settings(self.settings)
                elif kind == "error":
                    self.append_log("! " + value)
                elif kind == "exited":
                    self.apply_state("error", f"AirBear stopped unexpectedly (code {value}). "
                                              "Settings › View log has the details.")
        except queue.Empty:
            pass
        self.root.after(100, self.poll_events)

    def on_close(self):
        self.receiver.stop()
        self.root.destroy()


def main():
    try:  # crisp text on high-DPI displays, and our own taskbar icon/group
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_NAME)
    except (AttributeError, OSError):
        pass
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    if sys.platform != "win32":
        sys.exit("AirBear is a Windows application.")
    main()
