"""Alfred Dashlane workflow, built on the Dashlane CLI (dcli).

    python3 dl.py filter password|otp     Script Filter
    python3 dl.py run "<arg>"             actions (item variables come in the environment)
    python3 dl.py refresh|favicons|clearclip   background jobs
"""

import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib'))

from dlw import ui  # noqa: E402

cfg = ui.Config()
SCRIPT = os.path.abspath(__file__)
LETTERS = set('abcdefghijklmnopqrstuvwxyz')
REFRESH_AFTER = 60  # seconds before the cached list is refreshed in the background
INSTALL_DOC = 'https://dashlane.github.io/dashlane-cli/install'


class Done(Exception):
    """Stop an action and show `message` at the top of the list."""

    def __init__(self, message, icon='info', view='main'):
        Exception.__init__(self, message)
        self.icon, self.view = icon, view


# --------------------------------------------------------------------------- helpers

def cli():
    from dlw import dcli
    path = dcli.find(cfg.dcli_path)
    if not path:
        raise Done('Dashlane CLI not found: install it first', 'info')
    return dcli.Dcli(path)


def cache_path():
    return os.path.join(cfg.cache_dir, 'vault.json')


def favicon(domain):
    return os.path.join(cfg.cache_dir, domain + '.png')


def write_private(path, data):
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    tmp = '%s.%d.tmp' % (path, os.getpid())
    with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'wb') as fh:
        fh.write(data)
    os.replace(tmp, path)


def drop_cache():
    for name in os.listdir(cfg.cache_dir) if os.path.isdir(cfg.cache_dir) else ():
        if name.endswith('.json'):  # vault.json and the v1 password_*/otp_* files
            os.unlink(os.path.join(cfg.cache_dir, name))


def read_cache():
    try:
        with open(cache_path(), encoding='utf-8') as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if data.get('v') == 2 and data.get('login') == cfg.login else None


def fetch(dcli):
    """List credentials with dcli and keep what the list needs (no password, no OTP secret)."""
    records = []
    for c in dcli.json(['password', '-o', 'json']):
        domain = ui.extract_domain(c.get('url') or '')
        title = c.get('title') or domain or 'No title'
        records.append({
            'id': (c.get('id') or '').strip('{}'),
            'title': title,
            'key': ui.plain(title),
            'domain': domain,
            'url': c.get('url') or '',
            'login': c.get('email') or c.get('login') or c.get('secondaryLogin') or '',
            'otp': 'secret' if c.get('otpSecret') else ('uri' if c.get('otpUrl') else ''),
        })
    records.sort(key=lambda r: r['key'])
    drop_cache()  # also removes the v1 password_*.json / otp_*.json files
    if cfg.cache:
        data = {'v': 2, 'login': cfg.login, 'time': int(time.time()), 'items': records}
        write_private(cache_path(), json.dumps(data, separators=(',', ':')).encode())
    return records


def spawn(job):
    subprocess.Popen([sys.executable, SCRIPT, job], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True, cwd=os.path.dirname(SCRIPT))


def load_vault():
    """Cached list while dcli is unlocked (refreshed in the background), else ask dcli."""
    from dlw import dcli as d
    dcli = cli()
    if cfg.cache:
        cached = read_cache()
        if cached is not None:
            if d.is_unlocked(cfg.login):
                if time.time() - cached['time'] > REFRESH_AFTER:
                    spawn('refresh')
                return cached['items']
            drop_cache()  # locked (maybe from the terminal): forget the list
    else:
        drop_cache()
    return fetch(dcli)


# --------------------------------------------------------------------------- script filter

def status_items(base):
    message = ui.env('status')
    if not message:
        return []
    return [ui.item(message, ui.env('status_detail'), icon=ui.env('status_icon') or 'info', valid=False)]


def cmd_filter(kind):
    from dlw import dcli as d
    base = {'kind': kind, 'view': 'main'}
    items = status_items(base)
    logout = ui.item('Logout', 'Revoke this device and erase local data', icon='delete',
                     variables=dict(base, action='logout'))
    if not cfg.login:
        return ui.output_items(items + [ui.item('Set your Dashlane login', 'Open the workflow configuration',
                                                valid=False)])
    try:
        if ui.env('view') == 'devices':
            return ui.output_items(items + devices_view(base))
        records = load_vault()
    except Done as exc:
        return ui.output_items(items + [ui.item(str(exc), '⏎ open the installation guide', icon='info',
                                                variables=dict(base, action='open_url', url=INSTALL_DOC))])
    except d.LoggedOut:
        return ui.output_items(items + [ui.item(
            'Login to Dashlane', 'Register this Mac for %s (browser + code + master password)' % cfg.login,
            icon='otp', variables=dict(base, action='login'))])
    except d.Locked:
        return ui.output_items(items + [
            ui.item('Your vault is locked', '⏎ unlock it with your master password', icon='lock',
                    variables=dict(base, action='unlock')),
            logout])
    except d.DcliError as exc:
        return ui.output_items(items + [
            ui.item('Dashlane CLI error', '%s ǀ ⏎ report an issue' % exc, icon='info',
                    variables=dict(base, action='open_url', url=ui.ISSUES)),
            logout])

    items += [
        ui.item('Sync', 'Download the latest changes of your vault', icon='sync',
                variables=dict(base, action='sync')),
        ui.item('Lock', 'Lock your vault', icon='lock', variables=dict(base, action='lock')),
        ui.item('Devices', 'Manage devices connected to your account', icon='devices',
                variables=dict(base, action='nav', target='devices')),
        ui.item('Download favicons', 'Fetch missing site icons (domains are sent to Google)', icon='download',
                variables=dict(base, action='favicons')),
        logout,
    ]
    try:
        icons = set(os.listdir(cfg.cache_dir))
    except OSError:
        icons = set()
    is_otp = kind == 'otp'
    for r in records:
        if is_otp and not r['otp']:
            continue
        shown = ui.mask(r['login']) if cfg.incognito else (r['login'] or 'No login')
        if r['domain'] and r['domain'] + '.png' in icons:
            icon = favicon(r['domain'])
        else:
            first = next((c for c in r['key'] if c in LETTERS), None)
            icon = 'icons/letter-%s.webp' % first if first else 'icons/question-ics.webp'

        def v(action, r=r):
            return dict(base, action=action, id=r['id'], otp=r['otp'], url=r['url'])

        mods = {
            'cmd': {'subtitle': '%s ǀ ⏎ copy login' % shown, 'arg': 'copy_login',
                    'variables': v('copy_login'), 'valid': bool(r['login'])},
            'alt': {'subtitle': '%s ǀ ⏎ open url' % (r['domain'] or 'No URL'), 'arg': 'open_url',
                    'variables': v('open_url'), 'valid': bool(r['domain'])},
            'shift': {'subtitle': '%s ǀ ⏎ type login ⇥ password in frontmost app' % shown, 'arg': 'inject',
                      'variables': v('inject')},
        }
        if r['otp'] and not is_otp:
            mods['ctrl'] = {'subtitle': '%s ǀ ⏎ copy OTP' % shown, 'arg': 'copy_otp', 'variables': v('copy_otp')}
        items.append(ui.item(
            r['title'], '%s ǀ ⏎ copy %s' % (shown, 'OTP' if is_otp else 'password'), icon=icon,
            variables=v('copy_otp' if is_otp else 'copy_password'), mods=mods, uid=r['id'],
            match=' '.join([r['title'], r['key'], r['domain']] + ([] if cfg.incognito else [r['login']]))))
    ui.output_items(items)


def devices_view(base):
    devices = cli().json(['devices', 'list', '--json'])
    items = [
        ui.item('Return', 'Back to your vault', icon='return', variables=dict(base, action='nav', target='main')),
        ui.item('Remove all devices', 'Including this Mac (logs you out)', icon='delete',
                variables=dict(base, action='devices_remove_all', view='devices')),
        ui.item('Remove other devices', 'Keep only this Mac', icon='delete',
                variables=dict(base, action='devices_remove_others', view='devices')),
    ]

    def stamp(value):
        return time.strftime('%d-%m-%Y %H:%M', time.localtime(value or 0))

    for d in sorted(devices, key=lambda d: -(d.get('lastActivityDateUnix') or 0)):
        current = d.get('isCurrentDevice')
        name = d.get('deviceName') or d.get('devicePlatform') or 'Unknown device'
        variables = dict(base, action='logout') if current else \
            dict(base, action='device_remove', view='devices', id=d.get('deviceId', ''), name=name)
        items.append(ui.item(
            name + (' (this Mac)' if current else ''),
            'Created %s ǀ Last active %s' % (stamp(d.get('creationDateUnix')), stamp(d.get('lastActivityDateUnix'))),
            icon='devices', valid=False,
            mods={'cmd': {'subtitle': '⏎ remove this device', 'valid': True, 'arg': variables['action'],
                          'variables': variables, 'icon': {'path': 'icons/delete-ics.webp'}}}))
    return items


# --------------------------------------------------------------------------- actions

def answers(warn_password=''):
    """Answer dcli's questions with native dialogs (hidden for the master password)."""
    state = {'retries': 0}

    def answer(name, transcript):
        if name == 'email':
            return cfg.login
        if name == 'token':
            found = re.search(r'https://www\.dashlane\.com/cli-device-registration\?\S+', transcript)
            subprocess.run(['open', found.group(0) if found else
                            'https://www.dashlane.com/cli-device-registration?login=' + cfg.login])
            return ui.ask_valid('Step 1/3\n\nA Dashlane page opened in your browser. Follow it, then paste the '
                                'token it displays:', r'^[0-9a-fA-F-]{36}$', 'This is not a valid token')
        if name == 'code':
            return ui.ask_valid('Step 2/3\n\nEnter the 6-digit code received by email (or from your '
                                'authenticator app):', r'^\d{6}$', 'The code must have 6 digits')
        if name == 'otp':
            return ui.ask_valid('Enter the 6-digit code of your authenticator app:', r'^\d{6}$',
                                'The code must have 6 digits')
        if name == 'password':
            warn = warn_password if not state['retries'] else '\n\n⚠️ Wrong master password, try again.'
            return ui.ask('Master password of %s:%s' % (cfg.login, warn), hidden=True)
        if name == 'retry':
            state['retries'] += 1
            return 'y' if state['retries'] <= 2 else 'n'
        if name == 'confirm':  # the user already typed "yes" in Alfred
            return 'y'
        return None
    return answer


def interactive(args, timeout=180):
    from dlw import dcli as d
    try:
        return cli().run(args, answers(), timeout)
    except d.Cancelled:
        raise Done('Canceled', 'info')
    except d.DcliError as exc:
        message = str(exc)
        if 'mismatching signatures' in message or 'wrong master password' in message.lower():
            message = 'Wrong master password'
        raise Done(message, 'info')


def refresh_after_change(message, icon):
    try:
        records = fetch(cli())
        message += ' · %d items' % len(records)
    except Exception:
        pass
    raise Done(message, icon)


def action_login(arg):
    interactive(['sync'], timeout=300)
    refresh_after_change('✅ Connected as %s' % cfg.login, 'otp')


def action_unlock(arg):
    interactive(['sync'])
    refresh_after_change('🔓 Unlocked', 'lock')


def action_sync(arg):
    from dlw import dcli as d
    try:
        cli().run(['sync'], timeout=120)
    except d.Locked:
        raise Done('🔒 Your vault is locked', 'lock')
    except d.DcliError as exc:
        raise Done('🚨 Sync failed: %s' % exc)
    refresh_after_change('✅ Synced', 'sync')


def action_lock(arg):
    drop_cache()
    cli().run(['lock'])
    raise Done('🔒 Locked', 'lock')


def confirm(arg):
    if arg.strip().lower() != 'yes':
        raise Done('Canceled: type yes to confirm')


def wipe_local():
    drop_cache()
    if os.path.isdir(cfg.cache_dir):
        for name in os.listdir(cfg.cache_dir):
            if name.endswith('.png'):
                os.unlink(os.path.join(cfg.cache_dir, name))


def action_logout(arg):
    confirm(arg)
    wipe_local()
    interactive(['logout'], timeout=120)
    raise Done('✅ Logged out, local data erased', 'delete')


def action_device_remove(arg):
    cli().run(['devices', 'remove', ui.env('id')], timeout=60)
    raise Done('✅ Device "%s" removed' % ui.env('name'), 'devices', view='devices')


def action_devices_remove_all(arg):
    confirm(arg)
    wipe_local()
    interactive(['devices', 'remove', '--all'], timeout=120)
    raise Done('✅ All devices removed, you are logged out', 'delete')


def action_devices_remove_others(arg):
    confirm(arg)
    cli().run(['devices', 'remove', '--others'], timeout=60)
    raise Done('✅ Other devices removed', 'devices', view='devices')


def action_favicons(arg):
    spawn('favicons')
    raise Done('⏳ Downloading favicons in the background', 'download')


def action_nav(arg):
    ui.output_next('rerun', view=ui.env('target', 'main'), status='')


def item_path(field=''):
    item_id = ui.env('id')
    if not re.match(r'^[0-9A-Fa-f-]{36}$', item_id):
        raise Done('🚨 Unknown item')
    return 'dl://%s%s' % (item_id, '/' + field if field else '')


def read_item():
    try:
        return json.loads(cli().read(item_path()))
    except ValueError:
        raise Done('🚨 Unreadable item')


def schedule_clipboard_clear(text):
    if not cfg.clipboard_clear or not text:
        return
    salt = os.urandom(16)
    payload = json.dumps({'salt': salt.hex(), 'delay': cfg.clipboard_clear,
                          'mac': hmac.new(salt, text.encode(), hashlib.sha256).hexdigest()})
    proc = subprocess.Popen([sys.executable, SCRIPT, 'clearclip'], stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    proc.stdin.write(payload.encode())  # through a pipe: never visible in the process list
    proc.stdin.close()


def action_copy_password(arg):
    password = cli().read(item_path('password'))
    if not password:
        raise Done('⚠️ No password for this item')
    schedule_clipboard_clear(password)
    ui.output_next('copy', password, status='')


def action_copy_login(arg):
    item = read_item()
    ui.output_next('copy', item.get('email') or item.get('login') or '', status='')


def action_copy_otp(arg):
    path = item_path('otpUrl?otp_uri+expiry' if ui.env('otp') == 'uri' else 'otpSecret?otp+expiry')
    code = cli().read(path).split(' ')[0]
    if not code.isdigit():
        raise Done('🚨 No OTP for this item')
    schedule_clipboard_clear(code)
    ui.output_next('copy', code, status='')


def action_open_url(arg):
    url = ui.env('url').strip()
    has_scheme = '://' in url or re.match(r'^[a-z][a-z0-9+.-]*:(?!\d)', url, re.I)  # javascript:, file:…
    if url and not has_scheme:
        url = 'https://' + url
    if not re.match(r'^https?://', url, re.I):
        raise Done('⚠️ Only http(s) links can be opened')
    subprocess.run(['open', url])
    ui.output_next('none', status='')


def action_inject(arg):
    item = read_item()
    login, password = item.get('email') or item.get('login') or '', item.get('password') or ''
    script = 'delay 0.3\ntell application "System Events"\n'
    if login:
        script += 'keystroke %s\nkey code 48\n' % ui.applescript_string(login)
    script += 'keystroke %s\nend tell\n' % ui.applescript_string(password)
    # Script on stdin: the password never shows up in a process argument list.
    proc = subprocess.run(['osascript'], input=script, capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise Done('🚨 Typing failed: allow Alfred in Privacy & Security > Accessibility')
    ui.output_next('none', status='')


ACTIONS = {name[7:]: fn for name, fn in globals().items() if name.startswith('action_')}


def cmd_run(arg):
    from dlw import dcli as d
    action = ACTIONS.get(ui.env('action'))
    if action is None:
        return ui.output_next('none', status='')
    try:
        action(arg)
    except Done as exc:
        ui.output_next('rerun', view=exc.view, status=str(exc), status_icon=exc.icon)
    except d.Locked:
        drop_cache()
        ui.output_next('rerun', view='main', status='🔒 Your vault is locked', status_icon='lock')
    except d.LoggedOut:
        drop_cache()
        ui.output_next('rerun', view='main', status='You are not logged in', status_icon='otp')
    except d.DcliError as exc:
        ui.output_next('rerun', view='main', status='🚨 %s' % exc, status_icon='info')


# --------------------------------------------------------------------------- background jobs

def cmd_refresh():
    import fcntl
    from dlw import dcli as d
    os.makedirs(cfg.cache_dir, mode=0o700, exist_ok=True)
    with open(os.path.join(cfg.cache_dir, '.refresh.lock'), 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return
        try:
            fetch(cli())
        except (d.Locked, d.LoggedOut):
            drop_cache()
        except Exception:
            pass


def cmd_favicons():
    import ssl
    import urllib.request
    from concurrent.futures import ThreadPoolExecutor
    from urllib.parse import quote
    records = read_cache()
    domains = {r['domain'] for r in (records['items'] if records else fetch(cli()))} - {''}
    os.makedirs(cfg.cache_dir, mode=0o700, exist_ok=True)
    todo = [d for d in domains if not os.path.exists(favicon(d))]
    ctx = ssl.create_default_context()
    try:
        import certifi  # python.org builds ship without root certificates
        ctx.load_verify_locations(certifi.where())
    except Exception:
        pass

    def download(domain):
        url = 'https://www.google.com/s2/favicons?domain=%s&sz=128' % quote(domain)
        try:
            with urllib.request.urlopen(url, timeout=10, context=ctx) as resp:
                data = resp.read(256 * 1024 + 1)
                if resp.status == 200 and data.startswith(b'\x89PNG') and len(data) <= 256 * 1024:
                    write_private(favicon(domain), data)
        except Exception:
            pass

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(download, todo))


def cmd_clearclip():
    job = json.loads(sys.stdin.read())
    time.sleep(job['delay'])
    try:
        current = subprocess.run(['pbpaste'], capture_output=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return
    if hmac.compare_digest(hmac.new(bytes.fromhex(job['salt']), current, hashlib.sha256).hexdigest(), job['mac']):
        subprocess.run(['pbcopy'], input=b'', timeout=10)


def main(argv):
    os.umask(0o077)  # every file written by the workflow is private
    cmd = argv[1] if len(argv) > 1 else ''
    if cmd == 'filter':
        cmd_filter(argv[2] if len(argv) > 2 else 'password')
    elif cmd == 'run':
        cmd_run(argv[2] if len(argv) > 2 else '')
    elif cmd == 'refresh':
        cmd_refresh()
    elif cmd == 'favicons':
        cmd_favicons()
    elif cmd == 'clearclip':
        cmd_clearclip()
    else:
        sys.stderr.write(__doc__)
        return 2
    return 0


if __name__ == '__main__':
    try:
        code = main(sys.argv)
    except Exception as exc:  # last resort: show something in Alfred
        if len(sys.argv) > 1 and sys.argv[1] == 'filter':
            ui.output_items([ui.item('Something went wrong', '%s ǀ ⏎ report an issue' % exc, icon='info',
                                     variables={'action': 'open_url', 'url': ui.ISSUES})])
            code = 0
        else:
            raise
    sys.exit(code)
