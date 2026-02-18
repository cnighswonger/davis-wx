#!/bin/bash
# Build the davis-wx .deb package.
# Run from the repo root.
#
# Prerequisites:
#   sudo apt install dpkg-dev debhelper python3-venv nodejs npm
#
set -e
dpkg-buildpackage -us -uc -b
echo ""
echo "Package built: ../davis-wx_*.deb"
