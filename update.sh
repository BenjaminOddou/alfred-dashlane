#!/bin/bash
# Maintenance helper (not used at runtime).
#   CERTIFI=2026.10.23 CRYPTOGRAPHY=48.0.1 CFFI=2.0.0 ./update.sh
# 1. bundles certifi (pure Python CA bundle) in src/lib
# 2. rewrites src/requirements.txt with the SHA-256 of every macOS wheel
set -euo pipefail
cd "$(dirname "$0")/src"

rm -rf lib
pip3 install --no-deps --only-binary=:all: --target lib "certifi==${CERTIFI:?}"
rm -rf lib/bin

python3 - "${CRYPTOGRAPHY:?}" "${CFFI:?}" <<'EOF'
import json, sys, urllib.request
lines = [
    '# Native crypto engine for the workflow (Argon2 + AES).',
    '# Installed by the workflow with: pip install --no-deps --only-binary :all: --require-hashes',
    '# Only macOS wheels are listed; pip rejects any file whose SHA-256 is not below.',
    '# cffi is needed at runtime by cryptography; pycparser / typing-extensions are not.',
]
for name, version in (('cryptography', sys.argv[1]), ('cffi', sys.argv[2])):
    data = json.load(urllib.request.urlopen('https://pypi.org/pypi/%s/%s/json' % (name, version)))
    hashes = sorted(u['digests']['sha256'] for u in data['urls']
                    if u['filename'].endswith('.whl') and 'macosx' in u['filename'] and 'pypy' not in u['filename'])
    lines.append('%s==%s \\' % (name, version))
    lines += ['    --hash=sha256:%s%s' % (h, ' \\' if i < len(hashes) - 1 else '') for i, h in enumerate(hashes)]
open('requirements.txt', 'w').write('\n'.join(lines) + '\n')
EOF
echo "Done. Run the tests: python3 -m unittest discover -s tests"
