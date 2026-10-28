# AirBear setup: installs MSYS2 (if needed), then builds and installs the UxPlay
# AirPlay receiver plus the GStreamer plugins it needs for video/audio playback.
# Run from PowerShell:  powershell -ExecutionPolicy Bypass -File setup.ps1

$ErrorActionPreference = "Stop"
$msys = "C:\msys64"
$bash = Join-Path $msys "usr\bin\bash.exe"

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }

if (-not (Test-Path $bash)) {
    Step "Installing MSYS2 (via winget)"
    winget install --id MSYS2.MSYS2 -e --accept-package-agreements --accept-source-agreements
    if (-not (Test-Path $bash)) { throw "MSYS2 did not install to $msys. Install it from https://www.msys2.org and re-run." }
}

function Msys($cmd) {
    $env:MSYSTEM = "UCRT64"
    $env:CHERE_INVOKING = "1"
    & $bash -lc $cmd
    if ($LASTEXITCODE -ne 0) { throw "MSYS2 command failed: $cmd" }
}

# MSYS2 mirrors rate-limit (HTTP 429) pacman's parallel downloads, so download one
# file at a time and retry; packages that already downloaded stay in pacman's cache.
function Pacman($pkgArgs) {
    for ($try = 1; $try -le 5; $try++) {
        $env:MSYSTEM = "UCRT64"
        & $bash -lc "pacman --noconfirm --config <(sed 's/^ParallelDownloads.*/ParallelDownloads = 1/' /etc/pacman.conf) $pkgArgs"
        if ($LASTEXITCODE -eq 0) { return }
        $wait = 20 * $try
        Write-Host "pacman failed (attempt $try of 5), retrying in $wait s..." -ForegroundColor Yellow
        Start-Sleep -Seconds $wait
    }
    throw "pacman kept failing: $pkgArgs"
}

Step "Updating MSYS2 packages"
# First -Syu may update the core runtime and exit; run it twice.
& $bash -lc "pacman -Syu --noconfirm" | Out-Host
Pacman "-Syu"

Step "Installing build tools, GStreamer and libraries"
$pkgs = @(
    "git", "mingw-w64-ucrt-x86_64-cmake", "mingw-w64-ucrt-x86_64-gcc", "mingw-w64-ucrt-x86_64-ninja",
    "mingw-w64-ucrt-x86_64-libplist", "mingw-w64-ucrt-x86_64-openssl",
    "mingw-w64-ucrt-x86_64-gstreamer", "mingw-w64-ucrt-x86_64-gst-plugins-base",
    "mingw-w64-ucrt-x86_64-gst-plugins-good", "mingw-w64-ucrt-x86_64-gst-plugins-bad",
    "mingw-w64-ucrt-x86_64-gst-libav"
) -join " "
Pacman "-S --needed $pkgs"

Step "Building UxPlay"
$src = "/tmp/airbear-uxplay"
# UxPlay logs with printf and never flushes, so when AirBear reads it through a pipe
# status lines would arrive late. Force-include a tiny header that makes stdout unbuffered.
$unbuf = "/tmp/airbear-unbuffered.h"
Msys "printf '%s\n' '#include <stdio.h>' 'static void __attribute__((constructor)) airbear_unbuffered(void) { setvbuf(stdout, NULL, _IONBF, 0); }' > $unbuf"
# gcc is a native Windows program, so it needs the Windows form of the /tmp path.
$unbufWin = ($msys -replace '\\', '/') + $unbuf
# NO_MARCH_NATIVE: AirBear.exe ships this binary to other PCs, so don't tune it to this CPU.
$flags = "-DNO_MARCH_NATIVE=ON -DCMAKE_C_FLAGS='-include $unbufWin' -DCMAKE_CXX_FLAGS='-include $unbufWin'"
Msys "rm -rf $src && git clone --depth 1 https://github.com/FDH2/UxPlay $src && mkdir -p $src/build && cd $src/build && cmake -G Ninja $flags .. && ninja && cmake --install . --prefix /ucrt64"

$exe = Join-Path $msys "ucrt64\bin\uxplay.exe"
if (-not (Test-Path $exe)) { throw "Build finished but $exe was not found." }

# The firewall rule is added by AirBear itself on first start (one UAC prompt).
Step "Done. Launch AirBear with:  pythonw airbear.pyw"
