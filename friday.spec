# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for F.R.I.D.A.Y. — builds TWO windowed onefile executables.
#
# Build from the project root:
#   .venv/Scripts/python.exe -m PyInstaller friday.spec --noconfirm
#
# Produces:
#   dist/friday.exe           — portable; asks for the Gemini API key on first
#                               run (in-app setup page; the key is saved to a
#                               local .env next to the exe and remembered).
#   dist/friday-embedded.exe  — embedded; carries a precompiled Gemini key in
#                               build/rthook_embedded.py (kept out of git),
#                               no setup page on boot.
#
# The portable build never compiles a key into the binary; it reads the key at
# runtime from the .env it creates during setup.

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH)
BUILD_DIR = ROOT / "build"
BUILD_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------
# Runtime hooks for the two variants:
#   portable — mark this build as portable (setup page on boot) and make sure
#              no ambient key leaks into the packaged app.
#   embedded — inject the precompiled key from build/rthook_embedded.py into
#              the frozen process environment at boot.
# ---------------------------------------------------------------
hook_portable = BUILD_DIR / "rthook_portable.py"
hook_portable.write_text(
    "import os\n"
    "os.environ['FRIDAY_PORTABLE'] = '1'\n"
    "os.environ.pop('GEMINI_API_KEY', None)\n",
    encoding="utf-8",
)

hook_embedded = BUILD_DIR / "rthook_embedded.py"
if not hook_embedded.exists():
    raise SystemExit(
        "Missing build/rthook_embedded.py — create it with:\n"
        "  import os\n"
        "  os.environ.pop('FRIDAY_PORTABLE', None)\n"
        "  os.environ.pop('GEMINI_API_KEY', None)\n"
        "  os.environ['FRIDAY_EMBEDDED_KEY'] = '<your Gemini API key>'\n"
    )

# ---------------------------------------------------------------
# Data files and hidden imports
# ---------------------------------------------------------------
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
hiddenimports += [
    "pycaw.pycaw",
    "comtypes",
    "psutil",
    "pyautogui",
    "pygetwindow",
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
    excludes=["tkinter", "matplotlib", "numpy"],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(analysis.pure)

# Portable exe: setup page on first run.
EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="friday",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # no terminal window
    icon=str(ROOT / "icon.ico"),
)

# Embedded-key exe: fresh Analysis so the portable hook never runs.
analysis_embedded = Analysis(
    [str(ROOT / "app.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(hook_embedded)],
    excludes=["tkinter", "matplotlib", "numpy"],
    noarchive=False,
    optimize=1,
)
pyz_embedded = PYZ(analysis_embedded.pure)

EXE(
    pyz_embedded,
    analysis_embedded.scripts,
    analysis_embedded.binaries,
    analysis_embedded.datas,
    [],
    name="friday-embedded",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # no terminal window
    icon=str(ROOT / "icon.ico"),
)
