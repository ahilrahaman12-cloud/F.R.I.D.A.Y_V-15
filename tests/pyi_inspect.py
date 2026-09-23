"""Inspect the contents of a built F.R.I.D.A.Y. exe (PyInstaller onefile).

Usage: python pyi_inspect.py <exe>
Prints bundle stats proving the exe is standalone: bundled interpreter DLL,
templates, icon, runtime hooks, pure-Python modules inside the PYZ archive,
and compiled extension modules. Exits non-zero if anything required is missing.
"""

import struct
import sys
import tempfile
import zlib
from pathlib import Path

from PyInstaller.archive.readers import CArchiveReader

# Pure-Python modules live inside the embedded PYZ; compiled .pyd/.dll
# binaries and data files live in the outer CArchive.
REQUIRED_PYZ_MODULES = [
    "pyautogui",
    "psutil",
    "webview",
    "PIL.Image",
    "pycaw.pycaw",
    "google.genai",
    "flask",
    "jinja2",
    # pywebview's Windows backend (lazy import — easy for packagers to miss):
    "webview.platforms.edgechromium",
    "webview.platforms.winforms",
]
REQUIRED_SCRIPTS = ["app"]
REQUIRED_BINARIES = [
    "python314.dll",
]
REQUIRED_DATAS = [
    "templates\\index.html",
    "templates\\office.html",
    "templates\\setup.html",
    "icon.ico",
]


def read_pyz_names(reader: CArchiveReader) -> set[str]:
    """Extract the embedded PYZ archive and list the modules compiled into it."""
    key = next((name for name in reader.toc if str(name).endswith(".pyz")), None)
    if key is None:
        return set()
    data = reader.extract(key)
    if isinstance(data, tuple):
        data = data[-1]
    # PYZ format: magic "PYZ\x00" (4B) + pyc magic (4B) + TOC offset (uint32 BE)
    # followed by zlib-compressed module data; the marshalled TOC sits at the end.
    if data[:4] != b"PYZ\x00":
        return set()
    (toc_offset,) = struct.unpack("!I", data[8:12])
    import marshal

    try:
        toc = marshal.loads(data[toc_offset:])
    except Exception:
        return set()
    # TOC is a dict {name: (typ, pos, length)} in modern PyInstaller.
    if isinstance(toc, dict):
        return set(str(name) for name in toc)
    return set(str(entry[0]) for entry in toc)


def main():
    exe = sys.argv[1] if len(sys.argv) > 1 else "dist/friday-embedded.exe"
    reader = CArchiveReader(exe)
    names = [str(name) for name in reader.toc]
    print(f"=== {exe}: {len(names)} bundled CArchive entries")

    python_dll = sorted(name for name in names if "python3" in name.lower() and name.lower().endswith(".dll"))
    print("  python DLL:", python_dll)

    hooks = sorted(name for name in names if name.startswith("rthook"))
    print("  runtime hooks:", hooks)

    missing = []

    for required in REQUIRED_DATAS:
        found = required in names or required.replace("\\", "/") in names
        print(f"  data {required}:", "bundled" if found else "MISSING")
        if not found:
            missing.append(required)

    for script in REQUIRED_SCRIPTS:
        found = script in names
        print(f"  entry script {script}:", "bundled" if found else "MISSING")
        if not found:
            missing.append(script)

    pyz_names = read_pyz_names(reader)
    print(f"  PYZ modules: {len(pyz_names)}")
    for module in REQUIRED_PYZ_MODULES:
        found = module in pyz_names or any(name.startswith(module + ".") for name in pyz_names)
        print(f"  module {module}:", "bundled" if found else "MISSING")
        if not found:
            missing.append(module)

    binaries = [name for name in names if name.endswith((".dll", ".pyd"))]
    print(f"  binary extensions/DLLs: {len(binaries)}")
    for fragment in REQUIRED_BINARIES:
        found = any(fragment in name for name in binaries)
        print(f"  binary ~ {fragment}:", "bundled" if found else "MISSING")
        if not found:
            missing.append(fragment)

    if missing:
        print("RESULT: INCOMPLETE —", sorted(set(missing)))
        sys.exit(1)
    print("RESULT: STANDALONE — all required assets, modules, and binaries bundled.")


if __name__ == "__main__":
    main()
