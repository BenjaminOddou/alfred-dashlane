"""Thin, safe wrapper around the Dashlane CLI (dcli).

dcli asks its questions through a terminal, so it runs in a pty (pexpect).
Secrets typed by the user are sent to that pty: they never appear in a
command line or an environment variable.
"""

import json
import os
import re
import shutil
import subprocess

SEARCH = ('/opt/homebrew/bin/dcli', '/usr/local/bin/dcli', '~/.local/bin/dcli', '~/bin/dcli')
SECURITY = '/usr/bin/security'
KEYCHAIN_SERVICE = 'dashlane-cli'  # where dcli keeps its local key while unlocked
ANSI = re.compile(r'\x1b\[[0-9;?]*[ -/]*[@-~]')

# Questions dcli can ask, matched on stable fragments of its prompts.
PROMPTS = (
    ('email', r'enter your email address'),
    ('token', r'token given in the browser'),
    ('code', r'code you received by email'),
    ('otp', r'enter your OTP code'),
    ('password', r'enter your master password'),
    ('retry', r'provided is incorrect, would you like to retry'),
    ('confirm', r'Do you really want to logout'),
)
LOCKED = ('password', 'otp')


class DcliError(Exception):
    pass


class Locked(DcliError):
    pass


class LoggedOut(DcliError):
    pass


class Cancelled(DcliError):
    pass


def find(custom=''):
    for candidate in ([custom] if custom else []) + [shutil.which('dcli') or ''] + list(SEARCH):
        path = os.path.expanduser(candidate)
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def is_unlocked(login):
    """True when dcli's local key is in the keychain (attributes only, no secret read)."""
    try:
        proc = subprocess.run([SECURITY, 'find-generic-password', '-s', KEYCHAIN_SERVICE, '-a', login],
                              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def clean(text):
    return ANSI.sub('', text or '').replace('\r', '')


def error_message(output):
    """Last `error: ...` line of dcli, with the server message extracted when it is JSON."""
    lines = [l.strip() for l in clean(output).splitlines() if l.strip()]
    for line in reversed(lines):
        if line.lower().startswith('error:'):
            message = line[6:].strip()
            try:
                return json.loads(message[message.index('{'):message.rindex('}') + 1])['errors'][0]['message']
            except (ValueError, KeyError, IndexError, TypeError):
                return message.strip('"') or 'Dashlane CLI error'
    return lines[-1] if lines else 'Dashlane CLI error'


class Dcli:
    def __init__(self, path, timeout=30):
        self.path = path
        self.timeout = timeout
        self.env = dict(os.environ, NO_COLOR='1', FORCE_COLOR='0', TERM='xterm', LANG='en_US.UTF-8')

    def run(self, args, answer=None, timeout=None):
        """Run dcli, answering its questions with answer(name, transcript) -> str | None.

        Without `answer`, any question raises Locked / LoggedOut / DcliError.
        Returns dcli's output (prompts and ANSI codes removed for JSON commands).
        """
        import pexpect  # only when dcli really runs: the cached list path stays lean
        child = pexpect.spawn(self.path, list(args), env=self.env, encoding='utf-8', codec_errors='replace',
                              timeout=timeout or self.timeout, dimensions=(50, 2000), echo=False)
        patterns = [p for _, p in PROMPTS] + [pexpect.EOF, pexpect.TIMEOUT]
        transcript, last = '', None
        try:
            while True:
                index = child.expect(patterns)
                transcript += child.before or ''
                if index == len(PROMPTS):
                    break
                if index == len(PROMPTS) + 1:
                    raise DcliError('The Dashlane CLI did not answer in time')
                name = PROMPTS[index][0]
                transcript += child.after or ''
                if name == last:  # dcli redraws an answered question: ignore
                    continue
                if answer is None:
                    if name in LOCKED:
                        raise Locked('Your vault is locked')
                    if name in ('email', 'token', 'code'):
                        raise LoggedOut('You are not logged in')
                    raise DcliError('Unexpected question from the Dashlane CLI')
                value = answer(name, clean(transcript))
                if value is None:
                    raise Cancelled('Canceled')
                child.sendline(value)
                last = name if name != 'retry' else None
        finally:
            child.close(force=True)
        if child.exitstatus not in (0, None):
            raise DcliError(error_message(transcript))
        return transcript

    def json(self, args):
        out = clean(self.run(args))
        start = min([i for i in (out.find('['), out.find('{')) if i >= 0] or [-1])
        if start < 0:
            raise DcliError(error_message(out))
        try:
            return json.loads(out[start:])
        except ValueError:
            raise DcliError('Unreadable answer from the Dashlane CLI')

    def read(self, path):
        """`dcli read dl://...`: a secret, only ever passed through the pty."""
        lines = clean(self.run(['read', path])).split('\n')
        while lines and not lines[-1]:
            lines.pop()
        return lines[-1] if lines else ''  # keep spaces: they can be part of a password
