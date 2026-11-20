"""macOS login keychain access through /usr/bin/security.

Secrets go through stdin (`security -i`), never through argv, so they never
show up in the process list.
"""

import re
import subprocess

SERVICE = 'com.benjamino.dashlane'
SECURITY = '/usr/bin/security'
_SAFE = re.compile(r'^[0-9A-Za-z._-]+$')


class KeychainError(Exception):
    pass


def _run(args, stdin=None):
    try:
        return subprocess.run([SECURITY] + args, input=stdin, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise KeychainError('Keychain unavailable: %s' % exc)


def get(account):
    proc = _run(['find-generic-password', '-s', SERVICE, '-a', account, '-w'])
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def put(account, value):
    """Store a hex/base64-safe value. Raises KeychainError on failure."""
    if not (_SAFE.match(account) and _SAFE.match(value)):
        raise KeychainError('refusing to store a value with unsafe characters')
    _run(['-i'], 'add-generic-password -U -s %s -a %s -w %s\n' % (SERVICE, account, value))
    if get(account) != value:
        raise KeychainError('Could not write to the login keychain')


def delete(account):
    _run(['delete-generic-password', '-s', SERVICE, '-a', account])
