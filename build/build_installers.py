"""Build the two standalone installer executables with PyInstaller.

Run from the project root after friday.spec produced dist/friday.exe and
dist/friday-embedded.exe:

    .venv/Scripts/python.exe build/build_installers.py
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"
INSTALLER_SRC = BUILD / "installer_app.py"
PYINSTALLER = [str(ROOT / ".venv" / "Scripts" / "python.exe"), "-m", "PyInstaller"]

VARIANTS = {
    # installer exe name -> payload exe that must exist
    "friday-installer-embedded.exe": DIST / "friday-embedded.exe",
    "friday-installer.exe": DIST / "friday.exe",
}


def main() -> int:
    missing = [str(p) for p in VARIANTS.values() if not p.exists()]
    if missing:
        print("Missing payload executables:", ", ".join(missing))
        print("Build them first: .venv/Scripts/python.exe -m PyInstaller friday.spec --noconfirm")
        return 1

    failures = []
    for installer_name, payload in VARIANTS.items():
        print(f"\n=== Building {installer_name} (payload: {payload.name}) ===")
        result = subprocess.run(
            PYINSTALLER
            + [
                "--noconfirm",
                "--clean",
                "--onefile",
                "--windowed",
                "--name", Path(installer_name).stem,
                "--icon", str(ROOT / "icon.ico"),
                "--distpath", str(DIST),
                "--workpath", str(BUILD / "installers-work"),
                "--specpath", str(BUILD / "installers-specs"),
                # payload under a folder so the installer can find it by name
                "--add-data", f"{payload};payload",
                "--add-data", f"{ROOT / 'icon.ico'};.",
                # the installer itself needs only tkinter + stdlib
                "--hidden-import", "tkinter",
                "--hidden-import", "tkinter.filedialog",
                "--hidden-import", "tkinter.messagebox",
                "--hidden-import", "tkinter.ttk",
                str(INSTALLER_SRC),
            ],
            cwd=str(ROOT),
        )
        if result.returncode != 0:
            failures.append(installer_name)

    if failures:
        print("\nFAILED:", ", ".join(failures))
        return 1

    print("\nAll installers built:")
    for name in VARIANTS:
        exe = DIST / name
        print(f"  {exe}  ({exe.stat().st_size / 1024 / 1024:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
