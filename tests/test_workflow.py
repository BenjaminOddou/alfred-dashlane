"""Run dl.py against a fake Dashlane CLI (real pty) and a fake keychain.

    python3 -m unittest discover -s tests
"""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(ROOT, 'tests')
sys.path.insert(0, os.path.join(ROOT, 'src'))

import dl  # noqa: E402
from dlw import dcli, ui  # noqa: E402

TOKEN = '0f8fad5b-d9cb-469f-a165-70867728950e'
GITHUB = '11111111-1111-1111-1111-111111111111'
MAIL = '33333333-3333-3333-3333-333333333333'
ITEMS = [
    {'id': '{%s}' % GITHUB, 'title': 'GitHub', 'url': 'https://github.com/login', 'login': 'octocat',
     'email': 'octo@example.com', 'password': 'p@ss "quoted" \\ back ', 'otpSecret': 'JBSWY3DPEHPK3PXP'},
    {'id': '{22222222-2222-2222-2222-222222222222}', 'title': 'Émile & Co', 'url': 'shop.example.co.uk',
     'login': 'emile', 'password': 'ünïcødé'},
    {'id': '{%s}' % MAIL, 'title': '', 'url': 'https://mail.google.com', 'email': 'someone@gmail.com',
     'password': 'x', 'otpUrl': 'otpauth://totp/G:s?secret=GEZDGNBVGY3TQOJQ'},
]


class FakeSubprocess:
    """Replaces subprocess inside dl.py only (dcli and pexpect use the real one)."""
    DEVNULL = PIPE = -1

    def __init__(self):
        self.runs, self.spawned = [], []

    def run(self, cmd, **kw):
        self.runs.append((cmd, kw.get('input')))

        class R:
            returncode = 0
        return R()

    def Popen(self, cmd, **kw):
        self.spawned.append(cmd)

        class P:
            stdin = io.BytesIO()
        return P()


class WorkflowTest(unittest.TestCase):
    """Notifications off: every result shows on the first line of the list."""
    totp = False
    notify = '0'

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.state_file = os.path.join(self.tmp, 'state.json')
        self.state = {'logged_in': False, 'locked': False, 'mp': 'correct horse ✓', 'totp': self.totp,
                      'items': ITEMS, 'devices': [
                          {'deviceId': 'ME', 'deviceName': 'Mac', 'isCurrentDevice': True,
                           'creationDateUnix': 1, 'lastActivityDateUnix': 2},
                          {'deviceId': 'PHONE', 'deviceName': 'iPhone', 'isCurrentDevice': False,
                           'creationDateUnix': 1, 'lastActivityDateUnix': 3}]}
        self.save()
        self.old_env = dict(os.environ)
        os.environ.update({
            'FAKE_DCLI_STATE': self.state_file, 'dcli_path': os.path.join(TESTS, 'fake_dcli.py'),
            'alfred_workflow_cache': os.path.join(self.tmp, 'cache'), 'user_mail': 'Octo@Example.com',
            'incognito_mode': '1', 'cache_bool': '1', 'clipboard_clear': '30', 'notify': self.notify,
        })
        dl.cfg = ui.Config()
        self.answers = []
        self.saved = [(dcli, 'SECURITY', dcli.SECURITY), (ui, 'ask', ui.ask), (dl, 'subprocess', dl.subprocess)]
        dcli.SECURITY = os.path.join(TESTS, 'fake_security.py')
        ui.ask = self.fake_ask
        self.sub = dl.subprocess = FakeSubprocess()

    def tearDown(self):
        for obj, name, value in self.saved:
            setattr(obj, name, value)
        os.environ.clear()
        os.environ.update(self.old_env)
        shutil.rmtree(self.tmp)

    def save(self):
        with open(self.state_file, 'w') as fh:
            json.dump(self.state, fh)

    def load(self):
        with open(self.state_file) as fh:
            return json.load(fh)

    def fake_ask(self, prompt, hidden=False, title='Dashlane'):
        self.assertTrue(self.answers, 'unexpected dialog: ' + prompt)
        hidden_expected, answer = self.answers.pop(0)
        self.assertEqual(hidden, hidden_expected, prompt)
        return answer

    def call(self, *args, **variables):
        saved = dict(os.environ)
        os.environ.update(variables)
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                dl.main(['dl.py'] + list(args))
        finally:
            os.environ.clear()
            os.environ.update(saved)
        return json.loads(buf.getvalue())

    def titles(self, out):
        return [i['title'] for i in out['items']]

    def run_action(self, arg='', **variables):
        out = self.call('run', arg, **variables)['alfredworkflow']
        return out['arg'], out['variables']

    def login(self):
        self.answers = [(False, TOKEN), (False, '12345'), (False, '123456'), (True, self.state['mp'])]
        _, v = self.run_action(action='login')
        self.assertEqual(v['dl_status'], '✅ Connected · octo@example.com · 3 items', v)
        self.assertFalse(self.answers)

    def test_full_flow(self):
        cache = os.path.join(self.tmp, 'cache')
        os.makedirs(cache)
        with open(os.path.join(cache, 'password_octo@example.com.json'), 'w') as fh:
            fh.write('{"v1": "plaintext backbone"}')
        with open(os.path.join(cache, 'github.com.png'), 'wb') as fh:
            fh.write(b'\x89PNG')

        self.assertEqual(self.titles(self.call('filter', 'password')), ['Login to Dashlane'])
        self.login()
        opened = [cmd for cmd, _ in self.sub.runs if cmd[0] == 'open']
        self.assertEqual(opened[-1][1], 'https://www.dashlane.com/cli-device-registration?login=octo%40example.com')
        self.assertFalse(os.path.exists(os.path.join(cache, 'password_octo@example.com.json')))

        listing = self.call('filter', 'password')
        raw = json.dumps(listing, ensure_ascii=False)
        for secret in ('p@ss', 'ünïcødé', 'JBSWY3', 'GEZDGNBV', 'octo@example.com'):
            self.assertNotIn(secret, raw)
        self.assertEqual(self.titles(listing), ['Sync', 'Lock', 'Devices', 'Download favicons', 'Clear cache', 'Logout',
                                                'Émile & Co', 'GitHub', 'google.com'])
        # Alfred must not move items above the menu: no uid (knowledge already learned would
        # still apply with skipknowledge alone) and no new learning.
        for view in (listing, self.call('filter', 'otp'), self.call('filter', 'password', view='devices'),
                     self.call('filter', 'password', dl_status='✅ Synced')):
            self.assertIs(view['skipknowledge'], True)
            self.assertEqual([i['title'] for i in view['items'] if 'uid' in i], [])
        github = listing['items'][7]
        self.assertEqual(github['subtitle'], 'oc••••o@example.com ǀ ⏎ copy password')
        self.assertTrue(github['icon']['path'].endswith('github.com.png'))
        self.assertEqual(self.titles(self.call('filter', 'otp'))[6:], ['GitHub', 'google.com'])

        # cache: no secret, private, served without calling dcli while unlocked
        with open(os.path.join(cache, 'vault.json'), 'rb') as fh:
            blob = fh.read()
        for secret in (b'p@ss', b'JBSWY3', b'GEZDGNBV', b'password'):
            self.assertNotIn(secret, blob)
        self.assertEqual(os.stat(os.path.join(cache, 'vault.json')).st_mode & 0o077, 0)
        calls = len(self.load()['log'])
        self.call('filter', 'password')
        self.assertEqual(len(self.load()['log']), calls)

        # secrets only travel through the pty
        arg, v = self.run_action(action='copy_password', id=GITHUB)
        self.assertEqual((arg, v['next']), ('p@ss "quoted" \\ back ', 'copy'))
        self.assertEqual(self.sub.spawned[-1][-1], 'clearclip')
        self.assertEqual(self.run_action(action='copy_otp', id=GITHUB, otp='secret')[0], '123456')
        self.assertEqual(self.load()['log'][-1], ['read', 'dl://%s/otpSecret?otp+expiry' % GITHUB])
        self.run_action(action='copy_otp', id=MAIL, otp='uri')
        self.assertEqual(self.load()['log'][-1], ['read', 'dl://%s/otpUrl?otp_uri+expiry' % MAIL])
        self.assertEqual(self.run_action(action='copy_login', id=GITHUB)[0], 'octo@example.com')
        self.run_action(action='inject', id=GITHUB)
        cmd, script = self.sub.runs[-1]
        self.assertEqual(cmd, ['osascript'])
        self.assertIn('keystroke "p@ss \\"quoted\\" \\\\ back "', script)
        self.run_action(action='open_url', url='shop.example.co.uk')
        self.assertEqual(self.sub.runs[-1][0], ['open', 'https://shop.example.co.uk'])
        _, v = self.run_action(action='open_url', url='javascript:alert(1)')
        self.assertIn('Only http(s)', v['dl_status'])
        _, v = self.run_action(action='copy_password', id='../../etc')
        self.assertIn('Unknown item', v['dl_status'])

        # sync, lock, unlock
        self.assertEqual(self.run_action(action='sync')[1]['dl_status'], '✅ Synced · 3 items')
        _, v = self.run_action(action='lock')
        self.assertEqual(v['dl_status'], '🔒 Locked')
        self.assertFalse(os.path.exists(os.path.join(cache, 'vault.json')))
        locked = self.call('filter', 'password', dl_status=v['dl_status'], dl_status_icon=v['dl_status_icon'])
        self.assertEqual(self.titles(locked), ['🔒 Locked', 'Your vault is locked', 'Clear cache', 'Logout'])
        _, v = self.run_action(action='copy_password', id=GITHUB)
        self.assertEqual((v['next'], v['dl_status']), ('rerun', '🔒 Your vault is locked'))
        self.unlock()
        self.assertIn('GitHub', self.titles(self.call('filter', 'password')))

        # locked from the terminal: the cached list disappears at once
        self.state = self.load()
        self.state['locked'] = True
        self.save()
        self.assertEqual(self.titles(self.call('filter', 'password')), ['Your vault is locked', 'Clear cache', 'Logout'])
        self.assertFalse(os.path.exists(os.path.join(cache, 'vault.json')))
        self.unlock()

        # devices
        devices = self.call('filter', 'password', view='devices')
        self.assertEqual(self.titles(devices)[3:], ['iPhone', 'Mac (this Mac)'])
        _, v = self.run_action(action='device_remove', id='PHONE', name='iPhone')
        self.assertEqual((v['dl_status'], v['view']), ('✅ Device removed · iPhone', 'devices'))
        self.assertEqual([d['deviceId'] for d in self.load()['devices']], ['ME'])

        # logout needs a typed "yes"
        _, v = self.run_action('no', action='logout')
        self.assertTrue(self.load()['logged_in'])
        _, v = self.run_action('yes', action='logout')
        self.assertEqual(v['dl_status'], '✅ Logged out · Local data erased')
        self.assertFalse(self.load()['logged_in'])
        self.assertEqual(os.listdir(cache), [])

    def unlock(self):
        self.answers = ([(False, '123456')] if self.totp else []) + [(True, self.state['mp'])]
        _, v = self.run_action(action='unlock')
        self.assertEqual(v['dl_status'], '🔓 Unlocked · 3 items', v)

    def test_wrong_inputs(self):
        self.answers = [(False, TOKEN), (False, '123456'), (True, 'wrong')]
        _, v = self.run_action(action='login')
        self.assertEqual(v['dl_status'], 'Wrong master password')
        self.answers = [(False, None)]
        _, v = self.run_action(action='login')
        self.assertEqual(v['dl_status'], 'Canceled')
        self.login()
        self.run_action(action='lock')
        self.answers = ([(False, '123456')] if self.totp else []) + [(True, 'nope')]
        _, v = self.run_action(action='unlock')
        self.assertEqual(v['dl_status'], 'Wrong master password')

    def test_clear_cache(self):
        self.login()
        cache = os.path.join(self.tmp, 'cache')
        with open(os.path.join(cache, 'github.com.png'), 'wb') as fh:
            fh.write(b'\x89PNG')
        _, v = self.run_action(action='clear_cache')
        self.assertEqual(v['dl_status'], '🧹 Cache cleared · 2 files deleted')
        self.assertEqual(os.listdir(cache), [])
        self.assertIn('GitHub', self.titles(self.call('filter', 'password')))  # rebuilt from dcli

    @unittest.skipUnless(shutil.which('zsh'), 'zsh not installed')
    def test_variables_survive_zsh(self):
        """Alfred runs the scripts with zsh: a variable named like a zsh special parameter
        (`status`, `path`...) comes out as something else, e.g. "0"."""
        import subprocess
        self.login()
        names = set()
        listing = self.call('filter', 'password')
        for item in listing['items']:
            names |= set(item.get('variables', {}))
            for mod in item.get('mods', {}).values():
                names |= set(mod.get('variables', {}))
        names |= set(self.run_action(action='sync')[1])
        names |= set(self.run_action(action='nav', target='devices')[1])
        script = 'for n in %s; do export $n; done; %s -c "import os,json; print(json.dumps(dict(os.environ)))"' % (
            ' '.join(sorted(names)), sys.executable)
        for value in (None, '', 'x'):  # None: unset, then exported by the shell
            env = {'PATH': os.environ['PATH']}
            env.update({n: value for n in names if value is not None})
            seen = json.loads(subprocess.run(['zsh', '-c', script], env=env, capture_output=True,
                                             text=True).stdout)
            self.assertEqual({n: seen.get(n) or '' for n in names}, {n: value or '' for n in names})

    def test_background_refresh_and_no_cache(self):
        self.login()
        path = os.path.join(self.tmp, 'cache', 'vault.json')
        with open(path) as fh:
            data = json.load(fh)
        data['time'] = int(time.time()) - 3600
        with open(path, 'w') as fh:
            json.dump(data, fh)
        self.call('filter', 'password')
        self.assertEqual(self.sub.spawned[-1][-1], 'refresh')
        dl.cmd_refresh()
        with open(path) as fh:
            self.assertGreater(json.load(fh)['time'], data['time'])
        os.environ['cache_bool'] = '0'
        dl.cfg = ui.Config()
        self.assertIn('GitHub', self.titles(self.call('filter', 'password')))
        self.assertFalse(os.path.exists(path))

    def test_cli_missing(self):
        os.environ['dcli_path'] = '/nonexistent/dcli'
        os.environ['PATH'] = '/nonexistent'
        saved, dcli.SEARCH = dcli.SEARCH, ()
        try:
            dl.cfg = ui.Config()
            out = self.call('filter', 'password')
        finally:
            dcli.SEARCH = saved
        self.assertEqual(out['items'][0]['variables']['url'], dl.INSTALL_DOC)


class TotpAtLoginTest(WorkflowTest):
    totp = True


class NotificationTest(WorkflowTest):
    """Notifications on (default): results go to Alfred's Post Notification object."""
    notify = '1'

    def test_full_flow(self):
        self.answers = [(False, TOKEN), (False, '123456'), (True, self.state['mp'])]
        _, v = self.run_action(action='login')
        self.assertEqual((v['next'], v['dl_notify_title'], v['dl_notify_text'], v['dl_status']),
                         ('rerun', '✅ Connected', 'octo@example.com · 3 items', ''))

        listing = self.call('filter', 'password')
        self.assertIs(listing['strictmods'], True)
        self.assertEqual(listing['iconresize'], 'fit')
        github = next(i for i in listing['items'] if i['title'] == 'GitHub')

        # the notification names the item, never the secret
        arg, v = self.run_action(**github['variables'])
        self.assertEqual(arg, 'p@ss "quoted" \\ back ')
        self.assertEqual((v['next'], v['dl_notify_title'], v['dl_notify_text']),
                         ('copy', '📋 Password copied', 'GitHub · cleared in 30 s'))
        arg, v = self.run_action(**github['mods']['ctrl']['variables'])
        self.assertEqual((arg, v['dl_notify_title'], v['dl_notify_text']),
                         ('123456', '📋 OTP copied', 'GitHub · expires in 17 s · cleared in 30 s'))
        arg, v = self.run_action(**github['mods']['cmd']['variables'])
        self.assertEqual((arg, v['dl_notify_text']), ('octo@example.com', 'GitHub'))
        for value in v.values():
            self.assertNotIn('p@ss', value)

        # actions that end the flow vs. those that show the list again
        self.assertEqual(self.run_action(action='sync')[1]['next'], 'rerun')
        _, v = self.run_action(action='clear_cache')
        self.assertEqual((v['next'], v['dl_notify_title']), ('none', '🧹 Cache cleared'))
        _, v = self.run_action(action='lock')
        self.assertEqual((v['next'], v['dl_notify_title']), ('none', '🔒 Locked'))
        _, v = self.run_action(action='copy_password', id=GITHUB, title='GitHub')
        self.assertEqual((v['next'], v['dl_notify_title']), ('rerun', '🔒 Your vault is locked'))

        # navigation resets the notification
        _, v = self.run_action(action='nav', target='devices')
        self.assertEqual(v['dl_notify_title'], '')

    test_wrong_inputs = test_background_refresh_and_no_cache = test_clear_cache = None
    test_cli_missing = test_variables_survive_zsh = None


class Plist(unittest.TestCase):
    def setUp(self):
        import plistlib
        with open(os.path.join(ROOT, 'src', 'info.plist'), 'rb') as fh:
            self.plist = plistlib.load(fh)
        self.objects = {o['uid']: o for o in self.plist['objects']}

    def test_graph_is_consistent(self):
        for src, links in self.plist['connections'].items():
            self.assertIn(src, self.objects)
            for link in links:
                self.assertIn(link['destinationuid'], self.objects)

    def test_notification_never_shows_the_copied_secret(self):
        notes = [o for o in self.objects.values() if o['type'] == 'alfred.workflow.output.notification']
        self.assertEqual(len(notes), 1)
        config = notes[0]['config']
        self.assertEqual((config['title'], config['text']), ('{var:dl_notify_title}', '{var:dl_notify_text}'))
        run = next(u for u, o in self.objects.items() if o['type'] == 'alfred.workflow.action.script')
        reach, todo = set(), [run]
        while todo:
            for link in self.plist['connections'].get(todo.pop(), []):
                if link['destinationuid'] not in reach:
                    reach.add(link['destinationuid'])
                    todo.append(link['destinationuid'])
        self.assertIn(notes[0]['uid'], reach)

    def test_settings(self):
        variables = [c['variable'] for c in self.plist['userconfigurationconfig']]
        self.assertIn('notify', variables)
        self.assertNotIn('sound', variables)
        self.assertEqual(self.plist['version'], '1.7.1')


class Helpers(unittest.TestCase):
    def test_no_binary_bundled(self):
        found = [os.path.join(d, f) for d, _, files in os.walk(os.path.join(ROOT, 'src'))
                 for f in files if f.endswith(('.so', '.dylib')) or f in ('notificator',)]
        self.assertEqual(found, [])

    def test_error_message(self):
        self.assertEqual(dcli.error_message('\x1b[31merror: {"errors":[{"message":"Invalid OTP"}]}\x1b[39m\n'),
                         'Invalid OTP')
        self.assertEqual(dcli.error_message('info: x\nerror: mismatching signatures\n'), 'mismatching signatures')

    def test_text(self):
        self.assertEqual(ui.extract_domain('accounts.example.co.uk/x'), 'accounts.example.co.uk')
        self.assertEqual(ui.extract_domain('https://www.github.com'), 'github.com')
        self.assertEqual(ui.mask('octo@example.com'), 'oc••••o@example.com')
        self.assertEqual(ui.applescript_string('a"b\\c'), '"a\\"b\\\\c"')


if __name__ == '__main__':
    unittest.main()
