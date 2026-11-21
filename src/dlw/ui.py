"""Alfred glue: configuration, JSON output, native dialogs, text helpers."""

import json
import os
import re
import subprocess
import sys
import unicodedata
from urllib.parse import urlsplit

BUNDLE = 'com.benjamino.dashlane'
ISSUES = 'https://github.com/BenjaminOddou/alfred-dashlane/issues/new'


def env(name, default=''):
    return os.environ.get(name, default)


def _int(name, default):
    try:
        return int(env(name, str(default)) or default)
    except ValueError:
        return default


class Config:
    def __init__(self):
        home = os.path.expanduser('~')
        self.login = env('user_mail').strip().lower()
        self.incognito = env('incognito_mode', '1') == '1'
        self.cache = env('cache_bool', '1') == '1'
        self.clipboard_clear = _int('clipboard_clear', 30)  # seconds, 0 = never
        self.dcli_path = env('dcli_path').strip()
        self.notify = env('notify', '1') == '1'
        self.sound = env('sound', 'Submarine')  # empty = mute: no fallback to the default
        self.cache_dir = env('alfred_workflow_cache') or os.path.join(
            home, 'Library', 'Caches', 'com.runningwithcrayons.Alfred', 'Workflow Data', BUNDLE)


def item(title, subtitle='', icon='info', valid=True, variables=None, mods=None, **extra):
    obj = {
        'title': title,
        'subtitle': subtitle,
        'arg': (variables or {}).get('action', ''),
        'valid': valid,
        'icon': {'path': icon if '/' in icon else 'icons/%s-ics.webp' % icon},
    }
    if variables:
        obj['variables'] = variables
    if mods:
        obj['mods'] = mods
    obj.update(extra)
    return obj


def output_items(items):
    # Keep the status line and the menu (Sync, Lock, ...) on top, in this order: items carry
    # no `uid`, so Alfred has no knowledge to sort them with (skipknowledge alone only stops new
    # learning, what Alfred already learned would still move items up), and skipknowledge
    # stops any new learning.
    # Alfred 6 keys (ignored by Alfred 5): strictmods makes undefined modifier combinations do
    # nothing instead of the default action; iconresize keeps favicons' aspect ratio.
    sys.stdout.write(json.dumps({'items': items, 'skipknowledge': True, 'strictmods': True,
                                 'iconresize': 'fit'}))  # ASCII-safe whatever the locale


def output_next(next_step, arg='', notify='', detail='', **variables):
    """End of the Run Script: tell the workflow what comes next (copy / rerun / none).

    notify / detail: title and text of the native notification (Post Notification object).
    Always reset, because Alfred variables live for the whole flow. Names are prefixed:
    Alfred runs scripts with zsh, which has special parameters such as `status`.
    """
    variables.update(next=next_step, dl_notify_title=notify, dl_notify_text=detail)
    sys.stdout.write(json.dumps({'alfredworkflow': {'arg': arg, 'variables': variables}}))


_DIALOG = '''on run argv
set theTitle to item 1 of argv
set thePrompt to item 2 of argv
activate
if item 3 of argv is "1" then
set r to display dialog thePrompt with title theTitle default answer "" with hidden answer buttons {"Cancel", "OK"} default button "OK" cancel button "Cancel" with icon caution giving up after 300
else
set r to display dialog thePrompt with title theTitle default answer "" buttons {"Cancel", "OK"} default button "OK" cancel button "Cancel" with icon note giving up after 300
end if
if gave up of r then error number -128
return text returned of r
end run'''


def ask(prompt, hidden=False, title='Dashlane'):
    """Native macOS input dialog. The answer comes back through a pipe (never argv / env).

    Returns None when cancelled.
    """
    try:
        proc = subprocess.run(['osascript', '-e', _DIALOG, title, prompt, '1' if hidden else '0'],
                              capture_output=True, text=True, timeout=330)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    out = proc.stdout
    return out[:-1] if out.endswith('\n') else out


def ask_valid(prompt, pattern, error, hidden=False, tries=3):
    for _ in range(tries):
        value = ask(prompt, hidden)
        if value is None:
            return None
        value = value.strip()
        if re.match(pattern, value):
            return value
        prompt = '%s\n\n⚠️ %s' % (prompt.split('\n\n⚠️')[0], error)
    return None


def mask(login):
    if not login:
        return 'No login'
    if '@' in login:
        name, _, domain = login.partition('@')
        return name[:2] + '•' * 4 + name[-1:] + '@' + domain
    return login[:2] + '•' * 4 + login[-1:]


def applescript_string(text):
    return '"%s"' % text.replace('\\', '\\\\').replace('"', '\\"')


def plain(text):
    """Lowercase, accent-free form used for sorting, letter icons and matching."""
    decomposed = unicodedata.normalize('NFKD', text.casefold())
    return ''.join(c for c in decomposed if not unicodedata.combining(c))


_HOST = re.compile(r'^[a-z0-9.-]+$')


def extract_domain(url):
    """'https://accounts.example.com/x' -> 'example.com' (same rule as before)."""
    if not url:
        return ''
    if '://' not in url:
        url = 'https://' + url
    try:
        host = (urlsplit(url).hostname or '').strip('.').lower()
    except ValueError:
        return ''
    if not _HOST.match(host):
        return ''
    parts = host.split('.')
    if 2 <= len(parts) <= 3 and not host.replace('.', '').isdigit():
        return '.'.join(parts[-2:])
    return host
