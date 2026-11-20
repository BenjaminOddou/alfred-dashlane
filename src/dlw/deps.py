"""Locate / install the `cryptography` package (Argon2 + AES, native code).

It is installed once with pip into the workflow data folder, from PyPI, with
pinned versions and SHA-256 hashes (requirements.txt): pip refuses any file
whose hash does not match.
"""

import os
import platform
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REQUIREMENTS = os.path.join(HERE, 'requirements.txt')


def lib_dir(data_dir):
    tag = 'py%d%d-%s' % (sys.version_info[0], sys.version_info[1], platform.machine() or 'any')
    return os.path.join(data_dir, 'lib', tag)


def activate(data_dir):
    for path in (os.path.join(HERE, 'lib'), lib_dir(data_dir)):
        if os.path.isdir(path) and path not in sys.path:
            sys.path.insert(0, path)


def available():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
        from cryptography.hazmat.primitives.kdf.argon2 import Argon2d, Argon2id  # noqa: F401
        return True
    except Exception:
        return False


def install(data_dir):
    """pip install the pinned, hash-checked requirements. Returns (ok, message)."""
    if sys.version_info < (3, 9):
        return False, 'Python 3.9 or newer is required'
    target = lib_dir(data_dir)
    tmp = target + '.tmp'
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(os.path.dirname(target), mode=0o700, exist_ok=True)
    cmd = [sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check', '--no-input',
           '--no-deps', '--only-binary', ':all:', '--require-hashes', '--target', tmp, '-r', REQUIREMENTS]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    if proc.returncode != 0:
        lines = [l for l in (proc.stderr or proc.stdout).splitlines() if l.strip()]
        shutil.rmtree(tmp, ignore_errors=True)
        return False, lines[-1] if lines else 'pip failed'
    shutil.rmtree(target, ignore_errors=True)
    os.replace(tmp, target)
    return True, 'ok'
