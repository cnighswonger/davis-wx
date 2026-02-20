#!/bin/bash
# Davis Weather Station — Installer
# Usage: sudo ./install.sh
#   or:  ./install.sh  (will prompt for password)
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEB="$SCRIPT_DIR/davis-wx_0.1.0_all.deb"

if [ ! -f "$DEB" ]; then
    echo "Error: $DEB not found."
    echo "Place this script in the same folder as the .deb file."
    exit 1
fi

# Ensure we're running as root
if [ "$(id -u)" -ne 0 ]; then
    echo "Davis Weather Station Installer"
    echo "================================"
    echo "Administrator privileges are required."
    exec sudo "$0" "$@"
fi

echo "Davis Weather Station Installer"
echo "================================"
echo ""

# Copy to /tmp to avoid _apt sandbox permission issues
cp "$DEB" /tmp/davis-wx_0.1.0_all.deb

echo "Installing Davis Weather Station..."
apt install -y /tmp/davis-wx_0.1.0_all.deb

rm -f /tmp/davis-wx_0.1.0_all.deb

# Place desktop shortcut for the user who ran sudo
REAL_USER="${SUDO_USER:-$USER}"
if [ -n "$REAL_USER" ] && [ "$REAL_USER" != "root" ]; then
    USER_DESKTOP=$(eval echo "~$REAL_USER/Desktop")
    if [ -d "$USER_DESKTOP" ]; then
        SHORTCUT="$USER_DESKTOP/davis-wx.desktop"
        cp /usr/share/applications/davis-wx.desktop "$SHORTCUT"
        chmod +x "$SHORTCUT"
        chown "$REAL_USER":"$REAL_USER" "$SHORTCUT"
        # Mark trusted on GNOME so it's clickable without prompts
        su "$REAL_USER" -c "gio set '$SHORTCUT' metadata::trusted true" 2>/dev/null || true
        echo "Desktop shortcut created."
    fi
fi

echo ""
echo "Installation complete!"
echo ""
echo "A shortcut has been placed on your Desktop."
echo "Right-click it and select 'Allow Launching' to enable it."
echo ""
echo "You can also find it in the application menu or browse"
echo "directly to http://localhost:8000"
echo ""
