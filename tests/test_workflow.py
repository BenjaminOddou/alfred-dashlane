"""End-to-end run of dl.py against a fake Dashlane server (no network, no macOS).

Keychain, dialogs, notifications and subprocesses are replaced by fakes.
"""

import base64
import contextlib
import hashlib
import io
import json
import os
import secrets
import shutil
import sys
import tempfile
import time
import unittest
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from dlw import api, keychain, otp, service, ui  # noqa: E402

FIXTURE = os.path.join(ROOT, 'tests', 'fixtures', 'vault_fixture.json')
UUID = '0f8fad5b-d9cb-469f-a165-70867728950e'
GITHUB = '{11111111-1111-1111-1111-111111111111}'
EMILE = '{22222222-2222-2222-2222-222222222222}'


def encrypt_dashlane(fields, secret, kind='KWAuthentifiant'):
    """Python twin of tests/fixtures/make_vault_fixture.js (argon2d + AES-CBC-HMAC)."""
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.kdf.argon2 import Argon2d
    import hmac as _hmac
    xml = '<root><%s>%s</%s></root>' % (kind, ''.join(
        '<KWDataItem key="%s"><![CDATA[%s]]></KWDataItem>' % kv for kv in fields.items()), kind)
    comp = zlib.compressobj(wbits=-15)
    plain = b'\0\0\0\0\x78\x9c' + comp.compress(xml.encode()) + comp.flush()
    salt = secrets.token_bytes(16)
    key = Argon2d(salt=salt, length=32, iterations=3, lanes=2, memory_cost=32768).derive(secret.encode())
    combined = hashlib.sha512(key).digest()
    iv = secrets.token_bytes(16)
    padder = padding.PKCS7(128).padder()
    enc = Cipher(algorithms.AES(combined[:32]), modes.CBC(iv)).encryptor()
    ct = enc.update(padder.update(plain) + padder.finalize()) + enc.finalize()
    mac = _hmac.new(combined[32:], iv + ct, hashlib.sha256).digest()
    return base64.b64encode(b'$1$argon2d$16$3$32768$2$aes256$cbchmac$16$' + salt + iv + mac + ct).decode()


class FakeDashlane:
    def __init__(self, batches, totp=False, password=None):
        self.batches = batches  # list of transaction lists, served in order
        self.totp = totp
        self.password = password
        self.deactivated = []
        self.calls = []

    def post(self, path, payload, login=None, device=None):
        self.calls.append(path)
        name = path.split('/')[-1]
        if device is not None and device != ('ACCESS1', 'SECRET1'):
            raise api.ApiError('bad device', 'invalid_authentication', 403)
        if name == 'PerformTokenVerification':
            v = payload['verification']
            if v['token'] != '123456':
                raise api.ApiError('Invalid token', 'VERIFICATION_FAILED', 400)
            if v['intent'] == 'token:new_device':
                assert v['tokenRequestId'] == UUID
            else:
                assert v['intent'] == 'login' and v['deviceAccessKey'] == 'ACCESS1'
            return {'authTicket': {'ticket': 'T-' + v['intent']}}
        if name == 'GetAuthenticationMethods':
            remote = [{'type': 'totp', 'requiredOnLogin': True}] if self.totp else \
                [{'type': 'emailToken', 'requiredOnLogin': False}]
            return {'localAuthentications': [{'type': 'masterPassword'}], 'remoteAuthentications': remote}
        if name == 'CompleteDeviceRegistrationWithAuthTicket':
            assert payload['authTicket'] == 'STRONG'
            assert payload['device']['platform'] == 'server_cli'
            out = {'deviceAccessKey': 'ACCESS1', 'deviceSecretKey': 'SECRET1'}
            if self.totp:
                out['serverKey'] = 'SERVERKEY'
            return out
        if name == 'CompleteLoginWithAuthTicket':
            return {'serverKey': 'SERVERKEY'}
        if name == 'GetPremiumStatus':
            return {}
        if name == 'GetLatestContent':
            index = payload['timestamp'] // 100
            batch = self.batches[index] if index < len(self.batches) else []
            return {'transactions': batch, 'timestamp': (min(index, len(self.batches)) + (1 if batch else 0)) * 100}
        if name == 'ListDevices':
            return {'devices': [
                {'deviceId': 'ACCESS1', 'deviceName': 'Alfred - mac', 'creationDateUnix': 1, 'lastActivityDateUnix': 2},
                {'deviceId': 'OTHER', 'deviceName': 'iPhone', 'creationDateUnix': 1, 'lastActivityDateUnix': 3},
            ]}
        if name == 'DeactivateDevices':
            self.deactivated += payload['deviceIds']
            return {}
        raise AssertionError('unexpected call ' + path)


class FakeProc:
    def __init__(self):
        self.stdin = io.BytesIO()
        self.returncode = 0


class FakeSubprocess:
    DEVNULL = PIPE = -1

    def __init__(self):
        self.runs, self.spawned = [], []

    def run(self, cmd, **kw):
        self.runs.append(cmd)
        return FakeProc()

    def Popen(self, cmd, **kw):
        self.spawned.append(cmd)
        return FakeProc()


class WorkflowTest(unittest.TestCase):
    totp = False

    def setUp(self):
        with open(FIXTURE) as fh:
            self.fx = json.load(fh)
        self.tmp = tempfile.mkdtemp()
        self.env = {
            'alfred_workflow_data': os.path.join(self.tmp, 'data'),
            'alfred_workflow_cache': os.path.join(self.tmp, 'cache'),
            'user_mail': 'Octo@Example.com', 'incognito_mode': '1', 'autolock': '60',
            'clipboard_clear': '30', 'autosync': '60', 'sound': '',
        }
        self._old_env = dict(os.environ)
        os.environ.update(self.env)
        self.server = FakeDashlane([self.fx['first'], self.fx['second']], totp=self.totp)
        self.keys = {}
        self.answers = []
        self.notes = []
        patches = {
            (api.Client, 'post'): lambda c, *a, **k: self.server.post(*a, **k),
            (keychain, 'get'): lambda account: self.keys.get(account),
            (keychain, 'put'): lambda account, value: self.keys.__setitem__(account, value),
            (keychain, 'delete'): lambda account: self.keys.pop(account, None),
            (ui, 'ask'): self.fake_ask,
            (ui, 'notify'): lambda title, message, sound: self.notes.append((title, message)),
            (service, 'opaque_login'): self.fake_opaque,
        }
        self._saved = [(obj, name, getattr(obj, name)) for obj, name in patches]
        for (obj, name), value in patches.items():
            setattr(obj, name, value)
        import dl
        self.dl = dl
        dl.cfg = ui.Config()
        self.sub = FakeSubprocess()
        self._saved.append((dl, 'subprocess', dl.subprocess))
        dl.subprocess = self.sub

    def tearDown(self):
        for obj, name, value in self._saved:
            setattr(obj, name, value)
        os.environ.clear()
        os.environ.update(self._old_env)
        shutil.rmtree(self.tmp)

    def fake_ask(self, prompt, hidden=False, title='Dashlane'):
        self.assertTrue(self.answers, 'unexpected dialog: ' + prompt)
        expect_hidden, answer = self.answers.pop(0)
        self.assertEqual(hidden, expect_hidden, prompt)
        return answer

    def fake_opaque(self, client, login, password, ticket):
        assert ticket == 'T-token:new_device'
        if password != self.fx['password']:
            raise service.WrongMasterPassword('Wrong master password')
        return 'STRONG'

    def call(self, *args, **variables):
        old = dict(os.environ)
        for key in ('action', 'id', 'view', 'target', 'kind'):
            os.environ.pop(key, None)
        os.environ.update(variables)
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                self.dl.main(['dl.py'] + list(args))
        finally:
            os.environ.clear()
            os.environ.update(old)
        out = buf.getvalue()
        return json.loads(out) if out else None

    def titles(self, result):
        return [i['title'] for i in result['items']]

    def login(self):
        self.answers = [(False, UUID.upper()), (False, '12345'), (False, '123456'),
                        (True, 'wrong'), (True, self.fx['password'])]
        out = self.call('run', '', action='login', kind='password')
        self.assertEqual(out['alfredworkflow']['variables']['next'], 'rerun', self.notes)
        self.assertFalse(self.answers)

    def test_full_flow(self):
        dl, data_dir = self.dl, self.env['alfred_workflow_data']
        # v1 leftovers: plaintext backbone + domain-named favicon
        os.makedirs(self.env['alfred_workflow_cache'])
        for name in ('password_octo@example.com.json', 'github.com.png'):
            with open(os.path.join(self.env['alfred_workflow_cache'], name), 'wb') as fh:
                fh.write(b'\x89PNG' if name.endswith('png') else b'{"items": []}')

        self.assertEqual(self.titles(self.call('filter', 'password', '')), ['Login to Dashlane'])
        self.assertEqual(sorted(os.listdir(self.env['alfred_workflow_cache'])), ['favicons'])
        self.login()
        self.assertIn('session', self.keys)
        self.assertIn(dl.favicon_name('github.com'), os.listdir(dl.favicon_dir()))

        listing = self.call('filter', 'password', '')
        raw = json.dumps(listing, ensure_ascii=False)
        for secret in ('p@ss', 'ünïcødé', 'legacy-pbkdf2', 'JBSWY3DP', 'octo@example.com'):
            self.assertNotIn(secret, raw)  # incognito: no passwords, no clear logins
        titles = self.titles(listing)
        self.assertEqual(titles[:5], ['Sync', 'Lock', 'Devices', 'Download favicons', 'Logout'])
        self.assertEqual(titles[5:], ['Émile & Co', 'GitHub', 'google.com'])
        github = next(i for i in listing['items'] if i['title'] == 'GitHub')
        self.assertTrue(github['icon']['path'].endswith(dl.favicon_name('github.com')))
        self.assertEqual(github['subtitle'], 'oc••••o@example.com ǀ ⏎ copy password')
        self.assertIn('ctrl', github['mods'])
        self.assertEqual(self.titles(self.call('filter', 'otp', ''))[5:], ['GitHub', 'google.com'])

        # nothing readable at rest
        for name in os.listdir(data_dir):
            path = os.path.join(data_dir, name)
            if os.path.isfile(path):
                blob = open(path, 'rb').read()
                for secret in (b'p@ss', b'GitHub', b'octocat', b'legacy', self.fx['password'].encode()):
                    self.assertNotIn(secret, blob, name)
                self.assertEqual(os.stat(path).st_mode & 0o077, 0, name)

        out = self.call('run', '', action='copy_password', id=GITHUB)
        self.assertEqual(out['alfredworkflow'], {'arg': 'p@ss "quoted" \\ back', 'variables': {'next': 'copy'}})
        self.assertEqual(self.sub.spawned[-1][-1], 'clearclip')
        out = self.call('run', '', action='copy_otp', id=GITHUB)
        self.assertEqual(out['alfredworkflow']['arg'], otp.generate('JBSWY3DPEHPK3PXP')[0])
        out = self.call('run', '', action='copy_login', id=GITHUB)
        self.assertEqual(out['alfredworkflow']['arg'], 'octo@example.com')
        self.call('run', '', action='open_url', id=EMILE)
        self.assertEqual(self.sub.runs[-1], ['open', 'https://shop.example.co.uk'])
        self.call('run', '', action='inject', id=GITHUB)
        self.assertEqual(self.sub.runs[-1], ['osascript'])

        # incremental sync: GitHub rotated, Émile removed
        out = self.call('run', '', action='sync')
        self.assertEqual(out['alfredworkflow']['variables']['next'], 'rerun', self.notes)
        self.assertEqual(self.titles(self.call('filter', 'password', ''))[5:], ['GitHub', 'google.com'])
        out = self.call('run', '', action='copy_password', id=GITHUB)
        self.assertEqual(out['alfredworkflow']['arg'], 'rotated-password')

        # lock / unlock
        self.call('run', '', action='lock')
        self.assertNotIn('session', self.keys)
        self.assertEqual(self.titles(self.call('filter', 'password', '')), ['Your vault is locked', 'Logout'])
        out = self.call('run', '', action='copy_password', id=GITHUB)
        self.assertEqual(self.notes[-1][0], '🔒 Locked')
        self.unlock()
        self.assertIn('GitHub', self.titles(self.call('filter', 'password', '')))

        # idle auto-lock
        old = time.time() - 61 * 60
        os.utime(os.path.join(data_dir, '.activity'), (old, old))
        self.assertEqual(self.titles(self.call('filter', 'password', ''))[0], 'Your vault is locked')
        self.assertNotIn('session', self.keys)
        self.unlock()

        # devices
        devices = self.call('filter', 'password', '', view='devices')
        self.assertEqual(self.titles(devices)[-2:], ['iPhone', 'Alfred - mac (this Mac)'])
        out = self.call('run', 'yes', action='devices_remove_others')
        self.assertEqual(self.server.deactivated, ['OTHER'])

        # logout needs a typed "yes"
        self.call('run', 'no', action='logout')
        self.assertTrue(os.path.exists(os.path.join(data_dir, 'state.json')))
        self.call('run', 'yes', action='logout')
        self.assertEqual(self.server.deactivated, ['OTHER', 'ACCESS1'])
        self.assertFalse([n for n in os.listdir(data_dir) if os.path.isfile(os.path.join(data_dir, n))
                          and n != '.v2'])
        self.assertEqual(self.keys, {})

    def unlock(self):
        self.answers = [(True, 'nope'), (True, self.fx['password'])]
        out = self.call('run', '', action='unlock')
        self.assertEqual(out['alfredworkflow']['variables']['next'], 'rerun', self.notes)

    def test_wrong_code_and_cancel(self):
        self.answers = [(False, UUID), (False, '000000'), (True, self.fx['password'])]
        self.call('run', '', action='login')
        self.assertEqual(self.notes[-1][0], '🚨 Error')
        self.assertIn('Code rejected', self.notes[-1][1])
        self.answers = [(False, None)]
        self.call('run', '', action='login')
        self.assertEqual(self.notes[-1], ('⚠️ Canceled', 'Login canceled'))
        self.assertFalse(os.path.exists(os.path.join(self.env['alfred_workflow_data'], 'state.json')))

    def test_background_sync_is_spawned_when_stale(self):
        self.login()
        store = self.dl.get_store()
        store.state['last_sync'] = 0
        store.save_state()
        self.call('filter', 'password', '')
        self.assertEqual(self.sub.spawned[-1][-1], 'bgsync')
        self.dl.cmd_bgsync()
        self.assertGreater(self.dl.get_store().state['last_sync'], 0)


class TotpAtLoginTest(WorkflowTest):
    """Accounts with 2FA at every login: vault key = serverKey + master password."""
    totp = True

    def setUp(self):
        WorkflowTest.setUp(self)
        secret = 'SERVERKEY' + self.fx['password']
        first = [
            {'identifier': 'SETTINGS_userId', 'type': 'SETTINGS', 'action': 'BACKUP_EDIT',
             'content': encrypt_dashlane({'x': 'y'}, secret, 'KWSettingsManagerApp')},
            {'identifier': GITHUB, 'type': 'AUTHENTIFIANT', 'action': 'BACKUP_EDIT', 'content': encrypt_dashlane(
                {'Title': 'GitHub', 'Url': 'https://github.com', 'Email': 'octo@example.com',
                 'Password': 'totp-account', 'OtpSecret': 'JBSWY3DPEHPK3PXP'}, secret)},
        ]
        self.server.batches = [first]

    def unlock(self):
        self.answers = [(False, '123456'), (True, self.fx['password'])]
        out = self.call('run', '', action='unlock')
        self.assertEqual(out['alfredworkflow']['variables']['next'], 'rerun', self.notes)

    def test_full_flow(self):
        self.login()
        self.assertEqual(self.dl.get_store().state['auth_mode'], 'totp_login')
        out = self.call('run', '', action='copy_password', id=GITHUB)
        self.assertEqual(out['alfredworkflow']['arg'], 'totp-account')
        self.call('run', '', action='lock')
        self.answers = [(False, '123456'), (True, self.fx['password'])]
        self.call('run', '', action='unlock')
        self.assertIn('session', self.keys)
        self.assertIn('authentication/CompleteLoginWithAuthTicket', ' '.join(self.server.calls))


if __name__ == '__main__':
    unittest.main()
