"""Put the bundled third-party packages (src/lib) on sys.path.

Nothing is downloaded at runtime: `cryptography` (universal2, stable ABI) and
one `_cffi_backend` per Python version and CPU ship with the workflow, see
vendor.py at the repository root.
"""

import os
import platform
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(HERE, 'lib')
SUPPORTED = ((3, 9), (3, 15))


def activate():
    """Bundled packages first, so the pinned versions win over anything installed."""
    paths = [LIB]
    if sys.platform == 'darwin':  # the native files are macOS builds
        paths.insert(0, os.path.join(LIB, '_cffi', platform.machine()))
    else:  # dev / CI on Linux: certifi only, cryptography comes from the environment
        paths = []
    for path in reversed(paths):
        if os.path.isdir(path) and path not in sys.path:
            sys.path.insert(0, path)


def available():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
        from cryptography.hazmat.primitives.kdf.argon2 import Argon2d, Argon2id  # noqa: F401
        return True
    except Exception:
        return False


def problem():
    """Human readable reason why the crypto engine can't load."""
    version = '%d.%d' % sys.version_info[:2]
    if not SUPPORTED[0] <= sys.version_info[:2] <= SUPPORTED[1]:
        return 'Python %s is not supported (3.9 to 3.15)' % version
    if platform.machine() not in ('arm64', 'x86_64'):
        return 'Unsupported CPU: %s' % platform.machine()
    return 'Crypto engine failed to load with Python %s (%s)' % (version, sys.executable)
