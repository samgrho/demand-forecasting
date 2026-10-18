# -*- mode: python ; coding: utf-8 -*-
# PyInstaller build for the desktop app. Run via packaging\build.ps1.

import re
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo,
)

ROOT = Path(SPECPATH).parent
VERSION = re.search(r'__version__ = "([^"]+)"', (ROOT / "app" / "__init__.py").read_text()).group(1)
NUMS = tuple(int(x) for x in (VERSION.split(".") + ["0", "0", "0"])[:4])
NAME = "HotelDemandForecaster"

version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=NUMS, prodvers=NUMS),
    kids=[
        StringFileInfo([StringTable("040904B0", [
            StringStruct("FileDescription", "Hotel Demand Forecaster"),
            StringStruct("ProductName", "Hotel Demand Forecaster"),
            StringStruct("FileVersion", VERSION),
            StringStruct("ProductVersion", VERSION),
            StringStruct("OriginalFilename", f"{NAME}.exe"),
        ])]),
        VarFileInfo([VarStruct("Translation", [1033, 1200])]),
    ],
)

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    datas=[
        (str(ROOT / "app" / "templates"), "app/templates"),
        (str(ROOT / "app" / "static"), "app/static"),
        *collect_data_files("tzdata"),  # time zones for iCalendar feeds (Windows has no system tz database)
    ],
    # uvicorn picks its event loop / protocol implementations at runtime
    hiddenimports=collect_submodules("uvicorn"),
    excludes=["tkinter", "pytest", "respx", "PIL", "IPython", "matplotlib", "numpy"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=NAME,
    console=False,  # windowed app; logs go to %LOCALAPPDATA%\HotelDemandForecaster\app.log
    icon=str(ROOT / "packaging" / "app.ico"),
    version=version_info,
    upx=False,  # UPX-packed executables trip antivirus heuristics
)
coll = COLLECT(exe, a.binaries, a.datas, name=NAME, upx=False)
