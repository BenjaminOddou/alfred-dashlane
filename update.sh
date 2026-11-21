#!/bin/bash
# Maintenance helper (not used at runtime): re-vendor the bundled packages.
# Edit the pinned wheels / SHA-256 in vendor.py first, then run ./update.sh
set -euo pipefail
cd "$(dirname "$0")"
python3 vendor.py
python3 -m unittest discover -s tests
