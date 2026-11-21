"""Vendor the third-party packages of the workflow into src/lib (maintainers only).

    python3 vendor.py            # download pinned wheels, check SHA-256, extract
    python3 vendor.py --check    # only verify src/lib against the pins

Alfred Gallery workflows can't download code at runtime, so everything ships
inside the workflow:

  src/lib/certifi/                 CA bundle (pure Python)
  src/lib/cryptography/            Argon2 + AES. Universal2 (arm64 + x86_64),
                                   stable ABI: one copy for every Python >= 3.9
  src/lib/_cffi/<arch>/            _cffi_backend, the only piece of cffi that
                                   cryptography loads; one file per Python
                                   version (3.9 to 3.15) and per CPU

Wheels come from PyPI and must match the SHA-256 below, byte for byte.
"""

import hashlib
import io
import json
import os
import shutil
import sys
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(ROOT, 'src', 'lib')

PINS = {
    'certifi-2026.10.23-py3-none-any.whl':
        'e9b54de76e530bb6cf0ccd036787103acb58fd42ba930ea8bf948ddbaa2f61d1',
    'cryptography-48.0.1-cp39-abi3-macosx_10_9_universal2.whl':
        '4fdc69f8e4316bcf0c8c8ec1f26f285d12e8142d88d96c876a59a03be3f6ae67',
    # cffi 2.1 dropped Python 3.9; the backends are independent files.
    'cffi-2.0.0-cp39-cp39-macosx_10_13_x86_64.whl':
        'fe562eb1a64e67dd297ccc4f5addea2501664954f2692b69a76449ec7913ecbf',
    'cffi-2.0.0-cp39-cp39-macosx_11_0_arm64.whl':
        'de8dad4425a6ca6e4e5e297b27b5c824ecc7581910bf9aee86cb6835e6812aa7',
    'cffi-2.1.1-cp310-cp310-macosx_10_15_x86_64.whl':
        'baed1e86cc735622097354b9d1281406caf42ff42a886d29faa8e8d1630333be',
    'cffi-2.1.1-cp310-cp310-macosx_11_0_arm64.whl':
        'ca82be1a1d406ecfe1d25dc16cb33488e5a16bf4438c9fb590484ea29d92478b',
    'cffi-2.1.1-cp311-cp311-macosx_10_15_x86_64.whl':
        'c8d2c9fd1f2d16f780d15127abb050d13d1a76c03a4bd87d7e4980e45e511e12',
    'cffi-2.1.1-cp311-cp311-macosx_11_0_arm64.whl':
        '398aff33cee2767e3e781d2554c54bd0dff386bb437581e0d8011fde1a942ec1',
    'cffi-2.1.1-cp312-cp312-macosx_10_15_x86_64.whl':
        'c8c69575568085ba0b1b10c0249d779a214aea6f6522e949a0fc9fb0fcb449d0',
    'cffi-2.1.1-cp312-cp312-macosx_11_0_arm64.whl':
        'f81b3b8f3d4e343550fa4baa0e479bba9f2d29ce9c2e9b51d1ce1718d7442fcf',
    'cffi-2.1.1-cp313-cp313-macosx_10_15_x86_64.whl':
        '9d2055050ea716bd38b7f7f1579c275386646b4894c155a3e2f3cd62ed41b7c6',
    'cffi-2.1.1-cp313-cp313-macosx_11_0_arm64.whl':
        '19ee6127ee34de7d83ce3d371ebc5ed91addbdcc39f9ab15ce4eb35a4e534971',
    'cffi-2.1.1-cp314-cp314-macosx_10_15_x86_64.whl':
        'd28630f5854ab07ab1fd4aba756de52326c82e6be15d414b12793f1975048b54',
    'cffi-2.1.1-cp314-cp314-macosx_11_0_arm64.whl':
        '661c298b4821edebead0c91edd2b00374d67ad7c5a1f7a91d4442633b79d6a72',
    'cffi-2.1.1-cp315-cp315-macosx_10_15_x86_64.whl':
        'fb92203a88b3d3053034db775110081c49d28be6551923805e039924093761e4',
    'cffi-2.1.1-cp315-cp315-macosx_11_0_arm64.whl':
        '2ae64be792b8966f2c69538199728b290e34726562896df1e5dc8ffd8d8188e8',
}


def fetch(filename):
    name, version = filename.split('-')[:2]
    meta = json.load(urllib.request.urlopen('https://pypi.org/pypi/%s/%s/json' % (name, version), timeout=60))
    url = next(u['url'] for u in meta['urls'] if u['filename'] == filename)
    data = urllib.request.urlopen(url, timeout=300).read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != PINS[filename]:
        sys.exit('SHA-256 mismatch for %s: %s' % (filename, digest))
    return zipfile.ZipFile(io.BytesIO(data))


def extract(wheel, member, dest):
    """Write one wheel member to dest (no path traversal possible)."""
    if member.startswith('/') or '..' in member.split('/'):
        sys.exit('refusing suspicious path ' + member)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with wheel.open(member) as src, open(dest, 'wb') as out:
        shutil.copyfileobj(src, out)


def arch_of(filename):
    return 'arm64' if 'arm64' in filename else 'x86_64'


def vendor():
    shutil.rmtree(LIB, ignore_errors=True)
    for filename in sorted(PINS):
        wheel = fetch(filename)
        names = wheel.namelist()
        if filename.startswith(('certifi-', 'cryptography-')):
            pkg = filename.split('-')[0]
            for member in names:
                top = member.split('/')[0]
                is_license = top.endswith('.dist-info') and ('/licenses/' in member or member.endswith('/LICENSE'))
                if (top == pkg or is_license) and not member.endswith('/'):
                    extract(wheel, member, os.path.join(LIB, member))
        else:
            backend = [m for m in names if m.startswith('_cffi_backend.') and m.endswith('.so')]
            if len(backend) != 1:
                sys.exit('no _cffi_backend in ' + filename)
            extract(wheel, backend[0], os.path.join(LIB, '_cffi', arch_of(filename), backend[0]))
            lic = [m for m in names if m.endswith('.dist-info/licenses/LICENSE') or m.endswith('.dist-info/LICENSE')]
            if lic and not os.path.exists(os.path.join(LIB, '_cffi', 'LICENSE')):
                extract(wheel, lic[0], os.path.join(LIB, '_cffi', 'LICENSE'))
        print('ok', filename)


def check():
    expected = ['certifi/cacert.pem', 'cryptography/hazmat/bindings/_rust.abi3.so']
    for filename in PINS:
        if filename.startswith('cffi-'):
            tag = filename.split('-')[2]
            expected.append('_cffi/%s/_cffi_backend.cpython-%s-darwin.so' % (arch_of(filename), tag[2:]))
    missing = [p for p in expected if not os.path.isfile(os.path.join(LIB, p))]
    if missing:
        sys.exit('missing in src/lib: ' + ', '.join(missing))
    print('src/lib is complete (%d native files)' % (len(expected) - 1))


if __name__ == '__main__':
    if '--check' not in sys.argv:
        vendor()
    check()
