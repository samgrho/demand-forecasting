# Build the Windows desktop app and its installer.
#   dist\HotelDemandForecaster\                      the app folder (runnable as-is)
#   dist\installer\HotelDemandForecaster-Setup-X.exe  the installer
# Usage: powershell -ExecutionPolicy Bypass -File packaging\build.ps1 [-SkipTests]
param([switch]$SkipTests)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "Creating virtual environment..."
    python -m venv .venv
}
& $py -m pip install -q -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

if (-not $SkipTests) {
    Write-Host "Running tests..."
    & $py -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "tests failed" }
}

$version = (Select-String -Path "app\__init__.py" -Pattern '__version__ = "([^"]+)"').Matches[0].Groups[1].Value
Write-Host "Building version $version"

if (-not (Test-Path "packaging\app.ico")) { & $py packaging\make_icon.py }

& $py -m PyInstaller packaging\hdf.spec --noconfirm --clean --distpath dist --workpath build
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$iscc = @(
    (Get-Command iscc -ErrorAction SilentlyContinue).Source,
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $iscc) {
    Write-Warning "Inno Setup not found; skipping the installer. The app folder is in dist\HotelDemandForecaster."
    Write-Warning "Install it with: winget install JRSoftware.InnoSetup"
    exit 0
}
& $iscc "/DAppVersion=$version" "/Q" packaging\installer.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
Write-Host "Installer: dist\installer\HotelDemandForecaster-Setup-$version.exe"
