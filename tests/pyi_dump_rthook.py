"""Verify which Gemini key a packaged F.R.I.D.A.Y. exe actually embeds.

Usage: python pyi_dump_rthook.py <exe>
Searches the PyInstaller onefile archive (decompressed) for known key needles
and prints a masked preview of the FRIDAY_EMBEDDED_KEY value it carries.
"""

import sys

from PyInstaller.archive.readers import CArchiveReader

NEEDLES = [
    b"FRIDAY_EMBEDDED_KEY",
    b"FRIDAY_PORTABLE",
]


def main():
    exe = sys.argv[1] if len(sys.argv) > 1 else "dist/friday-embedded.exe"
    reader = CArchiveReader(exe)
    for key, entry in reader.toc.items():
        if not str(key).startswith("rthook"):
            continue
        data = reader.extract(key)
        if isinstance(data, tuple):
            data = data[-1]
        hits = [needle.decode() for needle in NEEDLES if needle in data]
        print(f"=== {key} ({len(data)} bytes) hits={hits}")
        for needle in NEEDLES:
            index = data.find(needle)
            if index == -1:
                continue
            chunk = data[index : index + 90]
            printable = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
            # Mask the key value but keep the recognizable prefix.
            print("   ", printable.replace(printable.split("=", 1)[-1][:14], printable.split("=", 1)[-1][:6] + "...", 1))


if __name__ == "__main__":
    main()
