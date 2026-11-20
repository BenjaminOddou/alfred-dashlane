"""Alfred glue: config, JSON output, notifications, native dialogs."""

import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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
        self.sound = env('sound', 'Submarine')
        self.autolock = _int('autolock', 60)          # minutes, 0 = never
        self.clipboard_clear = _int('clipboard_clear', 30)  # seconds, 0 = never
        self.autosync = _int('autosync', 60)          # minutes, 0 = never
        self.data_dir = env('alfred_workflow_data') or os.path.join(
            home, 'Library', 'Application Support', 'Alfred', 'Workflow Data', BUNDLE)
        self.cache_dir = env('alfred_workflow_cache') or os.path.join(
            home, 'Library', 'Caches', 'com.runningwithcrayons.Alfred', 'Workflow Data', BUNDLE)
        self.version = env('alfred_workflow_version', 'dev')


def item(title, subtitle='', icon='info', arg=None, valid=True, variables=None, mods=None, **extra):
    obj = {
        'title': title,
        'subtitle': subtitle,
        'arg': arg if arg is not None else (variables or {}).get('action', ''),
        'valid': valid,
        'icon': {'path': icon if '/' in icon else 'icons/%s-ics.webp' % icon},
    }
    if variables:
        obj['variables'] = variables
    if mods:
        obj['mods'] = mods
    obj.update(extra)
    return obj


def output_items(items, variables=None):
    data = {'items': items}
    if variables:
        data['variables'] = variables
    sys.stdout.write(json.dumps(data))  # ASCII-safe whatever the locale Alfred gives us


def output_next(next_step, arg='', **variables):
    """End of a Run Script: tell the workflow what to do next (copy / rerun / none)."""
    variables['next'] = next_step
    sys.stdout.write(json.dumps({"alfredworkflow": {"arg": arg, "variables": variables}}))


def notify(title, message, sound):
    path = os.path.join(HERE, 'notificator')
    try:
        subprocess.Popen([path, '--title', title, '--message', message, '--sound', sound],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except OSError:
        pass


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
    """Native macOS input dialog. The answer comes back on a pipe, never in argv/env.

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
