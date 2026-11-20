"""Alfred Dashlane workflow entry point (no Dashlane CLI needed).

    python3 dl.py filter password|otp "<query>"   Script Filter
    python3 dl.py run "<arg>"                     actions (item variables in env)
"""

import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import time

from dlw import ui

cfg = ui.Config()
SCRIPT = os.path.abspath(__file__)
LETTERS = set('abcdefghijklmnopqrstuvwxyz')


class Abort(Exception):
    """Stop an action with a notification (title, message)."""


# --------------------------------------------------------------------------- helpers

def boot():
    from dlw import deps
    deps.activate(cfg.data_dir)
    return deps.available()


def get_store():
    from dlw.store import Store
    return Store(cfg.data_dir, cfg.autolock)


def notify(title, message):
    ui.notify(title, message, cfg.sound)


def favicon_dir():
    return os.path.join(cfg.cache_dir, 'favicons')


def favicon_name(domain):
    return hashlib.sha256(domain.encode()).hexdigest()[:32] + '.png'


def ago(ts):
    if not ts:
        return 'never'
    s = int(time.time() - ts)
    for unit, size in (('d', 86400), ('h', 3600), ('min', 60)):
        if s >= size:
            return '%d %s ago' % (s // size, unit)
    return 'just now'


def migrate_v1():
    """Remove the plaintext JSON vault backbone written by v1 and rename its favicons."""
    marker = os.path.join(cfg.data_dir, '.v2')
    if os.path.exists(marker) or not os.path.isdir(cfg.cache_dir):
        return
    os.makedirs(favicon_dir(), mode=0o700, exist_ok=True)
    for name in os.listdir(cfg.cache_dir):
        path = os.path.join(cfg.cache_dir, name)
        if not os.path.isfile(path):
            continue
        if name.endswith('.json'):
            os.unlink(path)
        elif name.endswith('.png'):
            os.replace(path, os.path.join(favicon_dir(), favicon_name(name[:-4].lower())))
    os.makedirs(cfg.data_dir, mode=0o700, exist_ok=True)
    open(marker, 'w').close()


def clear_local(store):
    import shutil
    store.wipe()
    shutil.rmtree(favicon_dir(), ignore_errors=True)


def save_vault(store, vk, data, error=None):
    from dlw import service
    store.write('secrets', vk, data)
    store.write('index', vk, {'items': service.build_index(data.get('items', {}))})
    store.state['last_sync'] = int(time.time())
    store.state['last_error'] = error
    store.save_state()


def device_of(data):
    return data['device']['accessKey'], data['device']['secretKey']


def require_session(store):
    vk = store.session_key()
    if vk is None:
        raise Abort('🔒 Locked', 'Unlock your vault first')
    return vk


# --------------------------------------------------------------------------- script filter

def cmd_filter(kind, query):
    base = {'kind': kind, 'view': 'main'}
    if sys.version_info < (3, 9):
        return ui.output_items([ui.item('Python 3.9+ is required', 'Found %s' % sys.version.split()[0],
                                        valid=False)])
    if not boot():
        return ui.output_items([ui.item(
            'Install the crypto engine (one time)',
            'Downloads the hash-pinned "cryptography" package from PyPI (~5 MB)', icon='download',
            variables=dict(base, action='install'))])
    if not cfg.login:
        return ui.output_items([ui.item('Set your Dashlane login', 'Open the workflow configuration first',
                                        valid=False)])
    store = get_store()
    migrate_v1()
    logout = ui.item('Logout', 'Revoke this device and erase all local data', icon='delete',
                     variables=dict(base, action='logout'))
    if not store.exists():
        return ui.output_items([
            ui.item('Login to Dashlane', 'Register this Mac as a device of %s' % cfg.login, icon='otp',
                    variables=dict(base, action='login')),
        ])
    state = store.state
    if state.get('login') != cfg.login:
        return ui.output_items([ui.item('Logged in as another account',
                                        'Logout first to switch to %s' % cfg.login, icon='delete',
                                        variables=dict(base, action='logout'))])
    vk = store.session_key()
    if vk is None:
        return ui.output_items([
            ui.item('Your vault is locked', 'Press ⏎ to unlock it with your master password', icon='lock',
                    variables=dict(base, action='unlock')),
            logout,
        ])
    if ui.env('view') == 'devices':
        return devices_view(store, vk, base)
    return main_view(store, vk, kind, base, logout)


def main_view(store, vk, kind, base, logout):
    state = store.state
    entries = store.read('index', vk)['items']
    items = []
    if state.get('last_error'):
        items.append(ui.item('Last sync failed', state['last_error'], icon='info',
                             variables=dict(base, action='sync')))
    items += [
        ui.item('Sync', 'Last sync: %s' % ago(state.get('last_sync')), icon='sync',
                variables=dict(base, action='sync')),
        ui.item('Lock', 'Lock your vault now', icon='lock', variables=dict(base, action='lock')),
        ui.item('Devices', 'Manage devices connected to your account', icon='devices',
                variables=dict(base, action='nav', target='devices')),
        ui.item('Download favicons', 'Fetch missing site icons (domains are sent to Google)',
                icon='download', variables=dict(base, action='favicons')),
        logout,
    ]
    try:
        icons = set(os.listdir(favicon_dir()))
    except OSError:
        icons = set()
    is_otp = kind == 'otp'
    for e in entries:  # pre-sorted, domains pre-parsed at sync time
        if is_otp and not e['otp']:
            continue
        title, key, domain = e['title'], e['key'], e['domain']
        shown = ui.mask(e['login']) if cfg.incognito else (e['login'] or 'No login')
        fav = favicon_name(domain) if domain else ''
        if fav in icons:
            icon = os.path.join(favicon_dir(), fav)
        else:
            first = next((c for c in key if c in LETTERS), None)
            icon = 'icons/letter-%s.webp' % first if first else 'icons/question-ics.webp'

        def v(action):
            return dict(base, action=action, id=e['id'])

        mods = {
            'cmd': {'subtitle': '%s ǀ ⏎ copy login' % shown, 'variables': v('copy_login'),
                    'arg': 'copy_login', 'valid': bool(e['login'])},
            'alt': {'subtitle': '%s ǀ ⏎ open url' % (domain or 'No URL'), 'variables': v('open_url'),
                    'arg': 'open_url', 'valid': bool(domain)},
            'shift': {'subtitle': '%s ǀ ⏎ type login ⇥ password in frontmost app' % shown,
                      'variables': v('inject'), 'arg': 'inject'},
        }
        if not is_otp and e['otp']:
            mods['ctrl'] = {'subtitle': '%s ǀ ⏎ copy OTP' % shown, 'variables': v('copy_otp'), 'arg': 'copy_otp'}
        items.append(ui.item(
            title, '%s ǀ ⏎ copy %s' % (shown, 'OTP' if is_otp else 'password'),
            icon=icon, variables=v('copy_otp' if is_otp else 'copy_password'), mods=mods,
            uid=e['id'], match=' '.join(
                [title, key, domain] + ([] if cfg.incognito else [e['login']]))))
    ui.output_items(items)
    maybe_background_sync(store)


def devices_view(store, vk, base):
    from dlw import api
    data = store.read('secrets', vk)
    items = [ui.item('Return', 'Back to your vault', icon='return',
                     variables=dict(base, action='nav', target='main'))]
    try:
        devices = api.list_devices(api.Client(), cfg.login, device_of(data)).get('devices', [])
    except api.ApiError as exc:
        return ui.output_items(items + [ui.item('Cannot list devices', str(exc), valid=False)])
    items += [
        ui.item('Remove all devices', 'Including this Mac (logs you out)', icon='delete',
                variables=dict(base, action='devices_remove_all', view='devices')),
        ui.item('Remove other devices', 'Keep only this Mac', icon='delete',
                variables=dict(base, action='devices_remove_others', view='devices')),
    ]
    devices.sort(key=lambda d: -(d.get('lastActivityDateUnix') or 0))
    for d in devices:
        current = d.get('deviceId') == data['device']['accessKey']
        name = d.get('deviceName') or d.get('devicePlatform') or 'Unknown device'
        stamp = lambda key: time.strftime('%d-%m-%Y %H:%M', time.localtime(d.get(key) or 0))
        variables = dict(base, action='logout') if current else \
            dict(base, action='device_remove', view='devices', id=d.get('deviceId', ''), name=name)
        items.append(ui.item(
            name + (' (this Mac)' if current else ''),
            'Created %s ǀ Last active %s' % (stamp('creationDateUnix'), stamp('lastActivityDateUnix')),
            icon='devices', valid=False,
            mods={'cmd': {'subtitle': '⏎ remove this device', 'valid': True, 'arg': variables['action'],
                          'variables': variables, 'icon': {'path': 'icons/delete-ics.webp'}}}))
    ui.output_items(items)


def maybe_background_sync(store):
    state = store.state
    now = time.time()
    if not cfg.autosync or now - (state.get('last_sync') or 0) < cfg.autosync * 60:
        return
    if now - (state.get('last_attempt') or 0) < 300:
        return
    subprocess.Popen([sys.executable, SCRIPT, 'bgsync'], cwd=os.path.dirname(SCRIPT),
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


# --------------------------------------------------------------------------- actions

def action_install(arg):
    from dlw import deps
    notify('⏳ Please wait', 'Installing the crypto engine…')
    ok, message = deps.install(cfg.data_dir)
    if not ok:
        raise Abort('🚨 Install failed', message)
    notify('✅ Ready', 'Crypto engine installed')
    ui.output_next('rerun', view='main')


def action_login(arg):
    from urllib.parse import quote
    from dlw import api, service
    store = get_store()
    subprocess.run(['open', 'https://www.dashlane.com/cli-device-registration?login=' + quote(cfg.login)])
    token_id = ui.ask_valid('Step 1/3\n\nA Dashlane page opened in your browser. Follow it, then paste '
                            'the token it displays:', r'^[0-9a-fA-F-]{36}$', 'This is not a valid token')
    if token_id is None:
        raise Abort('⚠️ Canceled', 'Login canceled')
    code = ui.ask_valid('Step 2/3\n\nEnter the 6-digit code received by email (or from your '
                        'authenticator app):', r'^\d{6}$', 'The code must have 6 digits')
    if code is None:
        raise Abort('⚠️ Canceled', 'Login canceled')

    def ask_password(attempt):
        warn = '\n\n⚠️ Wrong master password, try again.' if attempt else ''
        return ui.ask('Step 3/3\n\nMaster password of %s:%s' % (cfg.login, warn), hidden=True)

    client = api.Client()
    reg = service.register_device(client, cfg.login, token_id.lower(), code, ask_password)
    notify('⏳ Please wait', 'Downloading and decrypting your vault…')
    device = (reg['access_key'], reg['secret_key'])
    data = {'device': {'accessKey': reg['access_key'], 'secretKey': reg['secret_key']},
            'secret': reg['secret'], 'derivates': {}, 'items': {}, 'ts': 0}
    try:
        service.check_team_2fa(client, cfg.login, device, reg['auth_mode'])
        service.sync(client, cfg.login, device, reg['secret'], data)
    except Exception:
        try:  # never leave a half-registered device behind
            api.deactivate_devices(client, cfg.login, device, [reg['access_key']])
        except Exception:
            pass
        raise
    store.wipe()
    vk = store.create(cfg.login, reg['secret'], reg['auth_mode'], reg['access_key'])
    save_vault(store, vk, data)
    notify('✅ Success', 'Connected as %s (%d items)' % (cfg.login, len(data['items'])))
    ui.output_next('rerun', view='main')


def action_unlock(arg):
    from dlw import api, service
    from dlw.store import WrongPassword
    store = get_store()
    prefix = ''
    if store.state.get('auth_mode') == 'totp_login':
        otp = ui.ask_valid('Enter the 6-digit code from your authenticator app:', r'^\d{6}$',
                           'The code must have 6 digits')
        if otp is None:
            raise Abort('⚠️ Canceled', 'Unlock canceled')
        prefix = service.server_key_for_unlock(api.Client(), cfg.login, store.state['access_key'], otp)
    vk, warn = None, ''
    for _ in range(3):
        password = ui.ask('Master password of %s:%s' % (cfg.login, warn), hidden=True)
        if password is None:
            raise Abort('⚠️ Canceled', 'Unlock canceled')
        try:
            vk = store.unwrap(prefix + password)
            break
        except WrongPassword:
            warn = '\n\n⚠️ Wrong master password, try again.'
    if vk is None:
        raise Abort('⚠️ Warning', 'Wrong master password')
    store.open_session(vk)
    notify('🔓 Unlocked', 'Vault unlocked' + (' for %d min' % cfg.autolock if cfg.autolock else ''))
    maybe_background_sync(store)
    ui.output_next('rerun', view='main')


def action_lock(arg):
    get_store().lock()
    notify('🔒 Locked', 'Your vault is locked')
    ui.output_next('none')


def run_sync(store, vk):
    import fcntl
    from dlw import api, service
    store._ensure_dir()
    with open(store.lock_path, 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise Abort('⏳ Please wait', 'A sync is already running')
        data = store.read('secrets', vk)
        changes = service.sync(api.Client(), cfg.login, device_of(data), data['secret'], data)
        save_vault(store, vk, data)
        return changes, len(data.get('items', {}))


def action_sync(arg):
    store = get_store()
    vk = require_session(store)
    try:
        changes, total = run_sync(store, vk)
    except Abort:
        raise
    except Exception as exc:
        store.state['last_error'] = str(exc)
        store.save_state()
        raise
    notify('✅ Synced', '%d change(s), %d items' % (changes, total))
    ui.output_next('rerun', view='main')


def action_favicons(arg):
    import ssl
    import urllib.request
    from concurrent.futures import ThreadPoolExecutor
    from urllib.parse import quote
    from dlw.store import write_private
    store = get_store()
    vk = require_session(store)
    domains = {e['domain'] for e in store.read('index', vk)['items']} - {''}
    os.makedirs(favicon_dir(), mode=0o700, exist_ok=True)
    have = set(os.listdir(favicon_dir()))
    todo = [d for d in domains if favicon_name(d) not in have]
    if not todo:
        raise Abort('👀 Finished', 'All favicons are already there')
    notify('⏳ Please wait', 'Downloading %d favicons…' % len(todo))
    ctx = ssl.create_default_context()
    try:
        import certifi
        ctx.load_verify_locations(certifi.where())
    except Exception:
        pass

    def fetch(domain):
        url = 'https://www.google.com/s2/favicons?domain=%s&sz=128' % quote(domain)
        try:
            with urllib.request.urlopen(url, timeout=10, context=ctx) as resp:
                data = resp.read(256 * 1024 + 1)
                if resp.status != 200 or not data.startswith(b'\x89PNG') or len(data) > 256 * 1024:
                    return False
        except Exception:
            return False
        write_private(os.path.join(favicon_dir(), favicon_name(domain)), data)
        return True

    with ThreadPoolExecutor(max_workers=8) as pool:
        got = sum(pool.map(fetch, todo))
    notify('👀 Finished', '%d new favicon(s)' % got)
    ui.output_next('none')


def action_nav(arg):
    ui.output_next('rerun', view=ui.env('target', 'main'))


def action_logout(arg):
    from dlw import api
    if arg.strip().lower() != 'yes':
        raise Abort('⚠️ Warning', 'Action canceled')
    store = get_store()
    revoked = False
    if store.exists():
        vk = store.session_key(touch=False)
        if vk is not None:
            try:
                data = store.read('secrets', vk)
                api.deactivate_devices(api.Client(), cfg.login, device_of(data), [data['device']['accessKey']])
                revoked = True
            except Exception:
                pass
    clear_local(store)
    notify('✅ Success', 'Logged out, local data erased' + (
        '' if revoked else ' (remove this device from Dashlane settings)'))
    ui.output_next('none')


def remove_devices(ids, current):
    from dlw import api
    store = get_store()
    data = store.read('secrets', require_session(store))
    api.deactivate_devices(api.Client(), cfg.login, device_of(data), ids)
    if current in ids:
        clear_local(store)
        notify('✅ Success', 'Devices removed, you are logged out')
        return ui.output_next('none')
    notify('✅ Success', '%d device(s) removed' % len(ids))
    ui.output_next('rerun', view='devices')


def action_device_remove(arg):
    remove_devices([ui.env('id')], None)


def action_devices_bulk(arg):
    from dlw import api
    if arg.strip().lower() != 'yes':
        raise Abort('⚠️ Warning', 'Action canceled')
    store = get_store()
    data = store.read('secrets', require_session(store))
    current = data['device']['accessKey']
    ids = [d['deviceId'] for d in api.list_devices(api.Client(), cfg.login, device_of(data)).get('devices', [])]
    if ui.env('action') == 'devices_remove_others':
        ids = [i for i in ids if i != current]
    if not ids:
        raise Abort('👀 Nothing to do', 'No other device')
    remove_devices(ids, current)


def credential(field_reader):
    store = get_store()
    vk = require_session(store)
    fields = store.read('secrets', vk).get('items', {}).get(ui.env('id'))
    if not fields:
        raise Abort('🚨 Error', 'Item not found, try to sync')
    return field_reader(fields)


def schedule_clipboard_clear(text):
    if not cfg.clipboard_clear or not text:
        return
    salt = os.urandom(16)
    payload = json.dumps({'salt': salt.hex(), 'delay': cfg.clipboard_clear,
                          'mac': hmac.new(salt, text.encode(), hashlib.sha256).hexdigest()})
    proc = subprocess.Popen([sys.executable, SCRIPT, 'clearclip'], stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    proc.stdin.write(payload.encode())
    proc.stdin.close()


def action_copy_password(arg):
    password = credential(lambda f: f.get('Password', ''))
    if not password:
        raise Abort('⚠️ Warning', 'No password for this item')
    schedule_clipboard_clear(password)
    notify('📋 Copied', 'Password copied' + (' (cleared in %ds)' % cfg.clipboard_clear if cfg.clipboard_clear else ''))
    ui.output_next('copy', password)


def action_copy_login(arg):
    login = credential(lambda f: f.get('Email') or f.get('Login') or f.get('SecondaryLogin') or '')
    ui.output_next('copy', login)


def action_copy_otp(arg):
    from dlw import otp
    code, left = credential(lambda f: otp.generate(f.get('OtpSecret'), f.get('OtpUrl')))
    schedule_clipboard_clear(code)
    notify('📋 Copied', 'OTP copied' + (' (expires in %ds)' % left if left else ''))
    ui.output_next('copy', code)


def action_open_url(arg):
    url = credential(lambda f: f.get('Url') or f.get('UserSelectedUrl') or '')
    if url and '://' not in url:
        url = 'https://' + url
    if not re.match(r'^https?://', url, re.I):
        raise Abort('⚠️ Warning', 'Only http(s) links can be opened')
    subprocess.run(['open', url])
    ui.output_next('none')


def action_inject(arg):
    login, password = credential(lambda f: (f.get('Email') or f.get('Login') or '', f.get('Password', '')))
    script = 'delay 0.3\ntell application "System Events"\n'
    if login:
        script += 'keystroke %s\nkey code 48\n' % ui.applescript_string(login)
    script += 'keystroke %s\nend tell\n' % ui.applescript_string(password)
    # Script on stdin: the password never appears in a process argument list.
    proc = subprocess.run(['osascript'], input=script, capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise Abort('🚨 Error', 'Typing failed: allow Alfred in Privacy > Accessibility')
    ui.output_next('none')


def action_issue(arg):
    subprocess.run(['open', ui.ISSUES])
    ui.output_next('none')


ACTIONS = {
    'issue': action_issue,
    'install': action_install,
    'login': action_login,
    'unlock': action_unlock,
    'lock': action_lock,
    'sync': action_sync,
    'favicons': action_favicons,
    'nav': action_nav,
    'logout': action_logout,
    'device_remove': action_device_remove,
    'devices_remove_all': action_devices_bulk,
    'devices_remove_others': action_devices_bulk,
    'copy_password': action_copy_password,
    'copy_login': action_copy_login,
    'copy_otp': action_copy_otp,
    'open_url': action_open_url,
    'inject': action_inject,
}


def cmd_run(arg):
    action = ACTIONS.get(ui.env('action'))
    if action is None:
        return ui.output_next('none')
    if action not in (action_install, action_issue) and not boot():
        notify('🚨 Error', 'Crypto engine missing, reopen the workflow')
        return ui.output_next('none')  # always reset `next`: variables live for the whole flow
    try:
        action(arg)
    except Abort as exc:
        notify(*exc.args)
        ui.output_next('none')
    except Exception as exc:
        notify('🚨 Error', str(exc) or exc.__class__.__name__)
        ui.output_next('none')


# --------------------------------------------------------------------------- background jobs

def cmd_bgsync():
    if not boot():
        return
    store = get_store()
    if not store.exists():
        return
    store.state['last_attempt'] = int(time.time())
    store.save_state()
    vk = store.session_key(touch=False)
    if vk is None:
        return
    try:
        run_sync(store, vk)
    except Abort:
        pass
    except Exception as exc:
        store._state = None
        store.state['last_error'] = str(exc) or exc.__class__.__name__
        store.save_state()


def cmd_clearclip():
    job = json.loads(sys.stdin.read())
    time.sleep(job['delay'])
    try:
        current = subprocess.run(['pbpaste'], capture_output=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return
    mac = hmac.new(bytes.fromhex(job['salt']), current, hashlib.sha256).hexdigest()
    if hmac.compare_digest(mac, job['mac']):
        subprocess.run(['pbcopy'], input=b'', timeout=10)


def main(argv):
    os.umask(0o077)  # every file the workflow writes is private to the user
    cmd = argv[1] if len(argv) > 1 else ''
    if cmd == 'filter':
        cmd_filter(argv[2] if len(argv) > 2 else 'password', argv[3] if len(argv) > 3 else '')
    elif cmd == 'run':
        cmd_run(argv[2] if len(argv) > 2 else '')
    elif cmd == 'bgsync':
        cmd_bgsync()
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
                                     arg=ui.ISSUES, variables={'action': 'issue'})])
            code = 0
        else:
            raise
    sys.exit(code)
