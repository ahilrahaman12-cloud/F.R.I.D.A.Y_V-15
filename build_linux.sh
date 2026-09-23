#!/usr/bin/env bash
# F.R.I.D.A.Y. — Linux AppImage build script (run inside WSL Ubuntu).
#
# Usage (from the project root):
#   ./build_linux.sh --sudo-password 'yourpassword'   # install system deps, then build
#   ./build_linux.sh                                  # build only (deps already installed)
#
# Steps:
#   1. apt-install WebKitGTK/GTK dev packages + build tools (only with --sudo-password).
#   2. Create .venv-linux and pip-install requirements (skipping Windows-only packages).
#   3. PyInstaller-build the Linux binary (portable variant, setup page on first run).
#   4. Assemble friday.AppDir (AppRun env hooks, icon, WebKit helpers, glib schemas).
#   5. Download linuxdeploy + the GTK plugin and produce dist/F.R.I.D.A.Y.*-x86_64.AppImage.
set -euo pipefail

cd "$(dirname "$0")"

SUDO_PASSWORD=""
if [[ "${1:-}" == "--sudo-password" ]]; then
    SUDO_PASSWORD="${2:?usage: build_linux.sh --sudo-password <password>}"
fi

log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }

# ------------------------------------------------------------------
# 1. System packages (WebKitGTK runtime + dev files for the plugin)
# ------------------------------------------------------------------
if [[ -n "$SUDO_PASSWORD" ]]; then
    log "Installing system packages (apt)"
    printf '%s\n' "$SUDO_PASSWORD" | sudo -S -p '' apt-get update -qq
    sudo -n DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        python3-venv python3-pip python3.14-dev build-essential \
        file findutils pkg-config patchelf \
        libgtk-3-dev librsvg2-dev libgirepository1.0-dev \
        gir1.2-webkit2-4.1 libwebkit2gtk-4.1-dev \
        gir1.2-gtk-3.0 gir1.2-gdkpixbuf-2.0 \
        glib-networking shared-mime-info
    sudo -k   # drop cached credentials (never needs a password)
fi

python3 -c 'import gi; gi.require_version("WebKit2", "4.1"); from gi.repository import WebKit2' \
    || { echo "ERROR: WebKit2 4.1 GIR typelib missing — run: ./build_linux.sh --sudo-password '...'"; exit 1; }

# ------------------------------------------------------------------
# 2. Python virtualenv with the Linux dependencies
# ------------------------------------------------------------------
log "Creating .venv-linux and installing Python requirements"
# --system-site-packages: reuse apt's PyGObject (gi) instead of compiling it.
if [[ ! -d .venv-linux ]]; then
    python3 -m venv --system-site-packages .venv-linux
fi
# shellcheck disable=SC1091
source .venv-linux/bin/activate
pip install --upgrade pip wheel >/dev/null
# requirements.txt carries Windows-only markers (pycaw, comtypes) — pip skips
# those automatically on Linux. PyGObject (gi) comes from the system install
# via --system-site-packages, so pywebview's GTK backend needs nothing extra.
pip install -r requirements.txt "pyinstaller"

# ------------------------------------------------------------------
# 3. PyInstaller build (portable variant — setup page on first run)
# ------------------------------------------------------------------
log "Building Linux binary with PyInstaller"
mkdir -p build
cat > build/rthook_portable_linux.py <<'EOF'
import os
os.environ['FRIDAY_PORTABLE'] = '1'
os.environ.pop('GEMINI_API_KEY', None)
EOF
pyinstaller friday-linux.spec --noconfirm --distpath dist/linux-build --workpath build/pyinstaller-linux

# ------------------------------------------------------------------
# 4. Assemble the AppDir
# ------------------------------------------------------------------
log "Assembling friday.AppDir"
APPDIR=friday.AppDir
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/lib"

# onedir layout: exe at usr/bin/friday with _internal/ next to it, so the
# frozen bootloader finds its bundle and linuxdeploy's default AppRun (which
# executes usr/bin/<desktop Exec>) works unchanged.
cp -r dist/linux-build/friday/. "$APPDIR/usr/bin/"

# WebKitGTK runtime: the main library + JavaScriptCore so the AppImage works
# on distros without WebKit installed. linuxdeploy walks usr/lib and pulls
# their transitive dependencies.
mkdir -p "$APPDIR/usr/lib/girepository-1.0"
cp -a /usr/lib/x86_64-linux-gnu/libwebkit2gtk-4.1.so.0* "$APPDIR/usr/lib/" 2>/dev/null || true
cp -a /usr/lib/x86_64-linux-gnu/libjavascriptcoregtk-4.1.so.0* "$APPDIR/usr/lib/" 2>/dev/null || true
cp -a /usr/lib/x86_64-linux-gnu/girepository-1.0/WebKit2-4.1.typelib "$APPDIR/usr/lib/girepository-1.0/" 2>/dev/null || true
cp -a /usr/lib/x86_64-linux-gnu/girepository-1.0/JavaScriptCore-4.1.typelib "$APPDIR/usr/lib/girepository-1.0/" 2>/dev/null || true

# GStreamer plugins so WebKit can play <audio>/<video> (voice playback).
mkdir -p "$APPDIR/usr/lib/gstreamer-1.0"
cp -a /usr/lib/x86_64-linux-gnu/gstreamer-1.0/*.so "$APPDIR/usr/lib/gstreamer-1.0/" 2>/dev/null || true

# WebKit spawns helper processes from a fixed relative path; bundle them and
# point WEBKIT_EXEC_PATH at them via the AppRun hook below.
WEBKIT_HELPERS="/usr/libexec/webkit2gtk-4.1"
[[ -d "$WEBKIT_HELPERS" ]] || WEBKIT_HELPERS="/usr/lib/x86_64-linux-gnu/webkit2gtk-4.1"
mkdir -p "$APPDIR/usr/lib/webkit2gtk-4.1"
cp -a "$WEBKIT_HELPERS/." "$APPDIR/usr/lib/webkit2gtk-4.1/"

# GLib settings schemas (GtkSettings need them inside the bundle).
SCHEMA_DIR="/usr/share/glib-2.0/schemas"
if [[ -d "$SCHEMA_DIR" ]]; then
    mkdir -p "$APPDIR/usr/share/glib-2.0/schemas"
    cp -a "$SCHEMA_DIR"/*.xml "$APPDIR/usr/share/glib-2.0/schemas/" 2>/dev/null || true
    glib-compile-schemas "$APPDIR/usr/share/glib-2.0/schemas" 2>/dev/null || true
fi

# Desktop entry + icon (hicolor layout so linuxdeploy picks them up).
mkdir -p "$APPDIR/usr/share/applications" "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cat > "$APPDIR/usr/share/applications/friday.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=F.R.I.D.A.Y.
Comment=AI desktop assistant
Exec=friday
Icon=friday
Categories=Utility;
Terminal=false
StartupWMClass=FRIDAY
EOF
python3 - <<'PY'
from PIL import Image
img = Image.open("icon.ico")
try:
    img.size = max(img.ico.sizes())  # pick the largest frame in the .ico
except AttributeError:
    pass
img.save("friday.AppDir/usr/share/icons/hicolor/256x256/apps/friday.png", "PNG")
PY
ln -sfn usr/share/icons/hicolor/256x256/apps/friday.png "$APPDIR/.DirIcon"

# AppRun hook: the linuxdeploy-generated AppRun sources every script in
# apprun-hooks/, which keeps the GTK plugin's own environment intact and adds
# what WebKit needs on top.
mkdir -p "$APPDIR/apprun-hooks"
cat > "$APPDIR/apprun-hooks/50-friday.sh" <<'EOF'
export WEBKIT_EXEC_PATH="${APPDIR}/usr/lib/webkit2gtk-4.1"
export WEBKIT_DISABLE_COMPOSITING_MODE=1
export GST_PLUGIN_SYSTEM_PATH="${APPDIR}/usr/lib/gstreamer-1.0${GST_PLUGIN_SYSTEM_PATH:+:$GST_PLUGIN_SYSTEM_PATH}"
export FRIDAY_PORTABLE=1
EOF

# ------------------------------------------------------------------
# 5. Pack the AppImage with linuxdeploy + the GTK plugin
# ------------------------------------------------------------------
log "Downloading linuxdeploy + GTK plugin"
TOOLS=build/tools
mkdir -p "$TOOLS"
[[ -x "$TOOLS/linuxdeploy-x86_64.AppImage" ]] || curl -fsSL -o "$TOOLS/linuxdeploy-x86_64.AppImage" \
    "https://github.com/linuxdeploy/linuxdeploy/releases/download/continuous/linuxdeploy-x86_64.AppImage"
[[ -f "$TOOLS/linuxdeploy-plugin-gtk.sh" ]] || curl -fsSL -o "$TOOLS/linuxdeploy-plugin-gtk.sh" \
    "https://raw.githubusercontent.com/linuxdeploy/linuxdeploy-plugin-gtk/master/linuxdeploy-plugin-gtk.sh"
chmod +x "$TOOLS/linuxdeploy-x86_64.AppImage" "$TOOLS/linuxdeploy-plugin-gtk.sh"

log "Packing AppImage"
export ARCH=x86_64
export DEPLOY_GTK_VERSION=3
export LINUXDEPLOY_OUTPUT_VERSION="11.0.0"
# --appimage-extract-and-run: works even when FUSE is unavailable (WSL).
"$TOOLS/linuxdeploy-x86_64.AppImage" --appimage-extract-and-run \
    --appdir "$APPDIR" \
    --desktop-file "$APPDIR/usr/share/applications/friday.desktop" \
    --icon-file "$APPDIR/usr/share/icons/hicolor/256x256/apps/friday.png" \
    --plugin gtk \
    --output appimage

mkdir -p dist
mv -f *.AppImage dist/ 2>/dev/null || true

log "Done"
ls -lh dist/*.AppImage
