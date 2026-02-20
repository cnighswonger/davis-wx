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

echo ""
echo "Installation complete!"
echo "You can open Davis Weather Station from the application menu"
echo "or visit http://localhost:8000 in your browser."
echo ""
