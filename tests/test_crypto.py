"""Crypto building blocks against published vectors and reference implementations.

Run: python3 -m unittest discover -s tests   (needs the `cryptography` package)
Set DLW_NODE_MODULES to a folder with @serenity-kit/opaque@1.1.0 to run the
OPAQUE interop test against the library the Dashlane CLI uses.
"""

import base64
import json
import os
import shutil
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from dlw import api, otp, ristretto, vault  # noqa: E402
from dlw.opaque import ClientLogin, OpaqueError, argon2id_ksf, expand_message_xmd  # noqa: E402

FIXTURE = os.path.join(ROOT, 'tests', 'fixtures', 'vault_fixture.json')


class Ristretto(unittest.TestCase):
    def test_small_multiples(self):  # RFC 9496 A.1
        expected = [
            '0000000000000000000000000000000000000000000000000000000000000000',
            'e2f2ae0a6abc4e71a884a961c500515f58e30b6aa582dd8db6a65945e08d2d76',
            '6a493210f7499cd17fecb510ae0cea23a110e8d5b901f8acadd3095c73a3b919',
            '94741f5d5d52755ece4f23f044ee27d5d1ea1e2bd196b462166b16152a9d0259',
            'da80862773358b466ffadfe0b3293ab3d9fd53c5ea6c955358f568322daf6a57',
        ]
        for k, hexval in enumerate(expected):
            self.assertEqual((ristretto.BASE * k).encode().hex(), hexval)
            self.assertEqual(ristretto.Point.decode(bytes.fromhex(hexval)).encode().hex(), hexval)

    def test_bad_encodings(self):  # RFC 9496 A.2 (non-canonical / negative)
        for hexval in ('00ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff',
                       'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f',
                       '0100000000000000000000000000000000000000000000000000000000000000'):
            with self.assertRaises(ValueError):
                ristretto.Point.decode(bytes.fromhex(hexval))

    def test_from_uniform_bytes(self):  # RFC 9496 A.3
        data = bytes.fromhex('5d1be09e3d0c82fc538112490e35701979d99e06ca3e2b5b54bffe8b4dc772c1'
                             '4d98b696a1bbfb5ca32c436cc61c16563790306c79eaca7705668b47dffe5bb6')
        self.assertEqual(ristretto.Point.from_uniform_bytes(data).encode().hex(),
                         '3066f82a1a747d45120d1740f14358531a8f04bbffe6a819f86dfe50f44a0a46')


class ExpandMessage(unittest.TestCase):
    def test_rfc9380_sha512(self):  # RFC 9380 K.3, expand_message_xmd(SHA-512), msg=""
        dst = b'QUUX-V01-CS02-with-expander-SHA512-256'
        self.assertEqual(expand_message_xmd(b'', dst, 32).hex(),
                         '6b9a7312411d92f921c6f68ca0b6380730a1a4d982c507211a90964c394179ba')


class Otp(unittest.TestCase):
    def test_rfc6238(self):
        uri = 'otpauth://totp/x?secret=GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ&digits=8'
        self.assertEqual(otp.generate(uri=uri, now=59)[0], '94287082')
        self.assertEqual(otp.generate(uri=uri, now=1111111109)[0], '07081804')
        self.assertEqual(otp.generate(secret='GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ', now=59), ('287082', 1))

    def test_hotp(self):  # RFC 4226 appendix D
        self.assertEqual(otp.generate(uri='otpauth://hotp/x?secret=GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ&counter=1')[0],
                         '287082')


class Signing(unittest.TestCase):
    # Expected values computed with @dashlane/apiconnect-worker 3.1.9 signRequest()
    def test_app_and_user_signatures(self):
        h = {'content-type': 'application/json', 'user-agent': 'Dashlane CLI v6.2647.2'}
        body = json.dumps({'login': 'jöhn+x@example.com', 'verification': {
            'token': '123456', 'intent': 'login', 'deviceAccessKey': 'abc'}},
            separators=(',', ':'), ensure_ascii=False).encode()
        self.assertEqual(
            api.sign('v1/authentication/PerformTokenVerification', body, h, 1700000000,
                     auth_fields=['AppAccessKey=' + api.APP_ACCESS_KEY]),
            'DL1-HMAC-SHA256 AppAccessKey=HB9JQATDY6Y62JYKT7KXBN4C7FH8HKC5,Timestamp=1700000000,'
            'SignedHeaders=content-type;user-agent,'
            'Signature=d4d8583f3737c41abb81fc35e4d90ce0f8f2d8ba76f5491ebd0711d3e432cd9e')
        self.assertEqual(
            api.sign('v1/devices/ListDevices', b'{}', h, 1700000001,
                     auth_fields=['Login=jöhn+x@example.com', 'AppAccessKey=' + api.APP_ACCESS_KEY,
                                  'DeviceAccessKey=DEVACCESS'], device_secret='deadbeef'),
            'DL1-HMAC-SHA256 Login=jöhn+x@example.com,AppAccessKey=HB9JQATDY6Y62JYKT7KXBN4C7FH8HKC5,'
            'DeviceAccessKey=DEVACCESS,Timestamp=1700000001,SignedHeaders=content-type;user-agent,'
            'Signature=49c0084c7a0a09421249938bf0fa12df4d59dedc7cb9e0d94b24347a1a6baa57')


class Vault(unittest.TestCase):
    def test_node_fixture(self):
        with open(FIXTURE) as fh:
            fx = json.load(fh)
        derivates = {}
        got = {}
        for tr in fx['first']:
            kind, fields = vault.parse_item(vault.decrypt(tr['content'], fx['password'], derivates))
            got[tr['identifier']] = (kind, fields)
        self.assertEqual(len(derivates), 3)  # two argon2d salts + one pbkdf2
        kind, gh = got['{11111111-1111-1111-1111-111111111111}']
        self.assertEqual(kind, 'KWAuthentifiant')
        self.assertEqual(gh['Password'], 'p@ss "quoted" \\ back')
        self.assertNotIn('Note', gh)
        self.assertEqual(got['{22222222-2222-2222-2222-222222222222}'][1]['Password'], 'ünïcødé-пароль')
        self.assertEqual(got['{33333333-3333-3333-3333-333333333333}'][1]['Password'], 'legacy-pbkdf2')
        self.assertEqual(got['{44444444-4444-4444-4444-444444444444}'][0], 'KWSecureNote')

    def test_wrong_password_and_tamper(self):
        with open(FIXTURE) as fh:
            fx = json.load(fh)
        tr = fx['first'][1]
        with self.assertRaises(vault.DecryptError):
            vault.decrypt(tr['content'], 'wrong', {})
        blob = bytearray(base64.b64decode(tr['content']))
        blob[-1] ^= 1
        with self.assertRaises(vault.DecryptError):
            vault.decrypt(base64.b64encode(bytes(blob)).decode(), fx['password'], {})


NODE_MODULES = os.environ.get('DLW_NODE_MODULES')


@unittest.skipUnless(NODE_MODULES and shutil.which('node'), 'set DLW_NODE_MODULES for the OPAQUE interop test')
class OpaqueInterop(unittest.TestCase):
    SERVER = os.path.join(ROOT, 'tests', 'fixtures', 'opaque_server.js')

    def login(self, registered, attempt):
        b64e = lambda b: base64.urlsafe_b64encode(b).rstrip(b'=').decode()  # noqa: E731
        b64d = lambda s: base64.urlsafe_b64decode(s + '=' * (-len(s) % 4))  # noqa: E731
        proc = subprocess.Popen(['node', self.SERVER, registered], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                text=True, env=dict(os.environ, NODE_PATH=NODE_MODULES))
        try:
            info = json.loads(proc.stdout.readline())
            client = ClientLogin(attempt)
            proc.stdin.write(b64e(client.start()) + '\n')
            proc.stdin.flush()
            response = b64d(proc.stdout.readline().strip())
            result = client.finish(response, argon2id_ksf(3, 65536, 4), server_identity=b'api.dashlane.com')
            proc.stdin.write(b64e(result['finish_request']) + '\n')
            proc.stdin.flush()
            server = json.loads(proc.stdout.readline())
            return info, result, server, b64e
        finally:
            proc.stdin.close()
            proc.stdout.close()
            proc.kill()
            proc.wait(timeout=30)

    def test_login_matches_serenity_server(self):
        info, result, server, b64e = self.login('correct horse ✓', 'correct horse ✓')
        self.assertEqual(server.get('sessionKey'), b64e(result['session_key']))
        self.assertEqual(info['exportKey'], b64e(result['export_key']))
        self.assertEqual(info['serverStaticPublicKey'], b64e(result['server_public_key']))

    def test_wrong_password(self):
        with self.assertRaises(OpaqueError):
            self.login('correct horse', 'wrong')


if __name__ == '__main__':
    unittest.main()
