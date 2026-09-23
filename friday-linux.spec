# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the Linux AppImage build of F.R.I.D.A.Y.
#
# Produces a windowed onedir bundle at dist/linux-build/friday/ containing the
# `friday` executable and its _internal/ dependency tree. The AppImage
# packaging (AppRun, icons, WebKit helpers) is handled by build_linux.sh.

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH)
BUILD_DIR = ROOT / "build"
BUILD_DIR.mkdir(exist_ok=True)

hook_portable = BUILD_DIR / "rthook_portable_linux.py"
if not hook_portable.exists():
    hook_portable.write_text(
        "import os\n"
        "os.environ['FRIDAY_PORTABLE'] = '1'\n"
        "os.environ.pop('GEMINI_API_KEY', None)\n",
        encoding="utf-8",
    )

datas = [
    (str(ROOT / "templates"), "templates"),
    (str(ROOT / "static"), "static"),
    (str(ROOT / "icon.ico"), "."),
]
datas += collect_data_files("google_genai")
datas += collect_data_files("pydantic")

hiddenimports = []
hiddenimports += collect_submodules("google.genai")
hiddenimports += collect_submodules("pydantic")
hiddenimports += collect_submodules("pywebview")
hiddenimports += [
    "psutil",
    "pyautogui",
    "pygetwindow",
    "pyrect",
    "webview",
    "PIL",
    "pynvml",
]

analysis = Analysis(
    [str(ROOT / "app.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(hook_portable)],
    # NOTE: tkinter must NOT be excluded on Linux. pyautogui imports
    # mouseinfo, which does `from tkinter import Event` and calls sys.exit()
    # (SystemExit — uncatchable by pyautogui's ImportError handler) when
    # tkinter is missing, silently killing the whole app at startup.
    excludes=["matplotlib", "numpy", "pycaw", "comtypes"],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="friday",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=False,
    icon=None,
)

coll = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="friday",
)
