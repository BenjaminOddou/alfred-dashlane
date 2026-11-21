#!/bin/bash
# Refresh the bundled pure-Python libraries (no binary may ship with the workflow).
set -euo pipefail
cd "$(dirname "$0")/src"
rm -rf lib
pip3 install --no-deps --only-binary=:all: --target lib pexpect==4.9.0 ptyprocess==0.7.0 certifi==2026.10.23
rm -rf lib/bin lib/certifi/tests
if find lib -name '*.so' -o -name '*.dylib' | grep -q .; then
    echo "error: a native binary ended up in src/lib" >&2
    exit 1
fi
cd .. && python3 -m unittest discover -s tests
