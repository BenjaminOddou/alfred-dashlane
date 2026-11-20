"""Encrypted local storage.

state.json   non-secret metadata + vault key wrapped with Argon2id(master password)
index.bin    AES-256-GCM: titles / logins / urls shown in Alfred (no passwords)
secrets.bin  AES-256-GCM: passwords, OTP secrets, device keys, sync cursor

The random vault key only sits in the login keychain while the vault is
unlocked; locking (manually or by timeout) deletes it.
"""

import base64
import json
import os
import secrets
import time

from . import keychain

VERSION = 2
KDF = {'alg': 'argon2id', 't': 3, 'm': 65536, 'p': 4}
SESSION = 'session'


class WrongPassword(Exception):
    pass


def _b64(data):
    return base64.b64encode(data).decode()


def _unb64(text):
    return base64.b64decode(text)


def write_private(path, data):
    tmp = '%s.%d.tmp' % (path, os.getpid())
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, 'wb') as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def kek(secret, kdf):
    from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
    return Argon2id(salt=_unb64(kdf['salt']), length=32, iterations=kdf['t'], lanes=kdf['p'],
                    memory_cost=kdf['m']).derive(secret.encode('utf-8'))


def seal(key, data, aad):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = secrets.token_bytes(12)
    return b'DLW2' + nonce + AESGCM(key).encrypt(nonce, data, aad)


def unseal(key, blob, aad):
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if blob[:4] != b'DLW2':
        raise ValueError('unknown file format')
    try:
        return AESGCM(key).decrypt(blob[4:16], blob[16:], aad)
    except InvalidTag:
        raise WrongPassword('decryption failed')


class Store:
    def __init__(self, data_dir, autolock_minutes=60):
        self.dir = data_dir
        self.autolock = autolock_minutes
        self.state_path = os.path.join(data_dir, 'state.json')
        self.activity_path = os.path.join(data_dir, '.activity')
        self.lock_path = os.path.join(data_dir, '.sync.lock')
        self._state = None

    # -- files ---------------------------------------------------------------
    def _ensure_dir(self):
        os.makedirs(self.dir, mode=0o700, exist_ok=True)
        os.chmod(self.dir, 0o700)

    def _path(self, name):
        return os.path.join(self.dir, name + '.bin')

    def _aad(self, name):
        return ('dlw|%s|%s' % (name, self.state['login'])).encode('utf-8')

    def exists(self):
        return os.path.isfile(self.state_path)

    @property
    def state(self):
        if self._state is None:
            with open(self.state_path, 'r', encoding='utf-8') as fh:
                self._state = json.load(fh)
        return self._state

    def save_state(self):
        self._ensure_dir()
        write_private(self.state_path, json.dumps(self.state, indent=1).encode())

    def read(self, name, vk):
        with open(self._path(name), 'rb') as fh:
            return json.loads(unseal(vk, fh.read(), self._aad(name)).decode('utf-8'))

    def write(self, name, vk, obj):
        self._ensure_dir()
        data = json.dumps(obj, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
        write_private(self._path(name), seal(vk, data, self._aad(name)))

    # -- lifecycle -----------------------------------------------------------
    def create(self, login, secret, auth_mode, access_key):
        """New local vault. Returns the vault key (session is opened)."""
        vk = secrets.token_bytes(32)
        kdf = dict(KDF, salt=_b64(secrets.token_bytes(16)))
        self._state = {
            'version': VERSION,
            'login': login,
            'auth_mode': auth_mode,
            'access_key': access_key,
            'kdf': kdf,
            'last_sync': 0,
        }
        self._state['wrapped_key'] = _b64(seal(kek(secret, kdf), vk, self._aad('key')))
        self.save_state()
        self.open_session(vk)
        return vk

    def unwrap(self, secret):
        return unseal(kek(secret, self.state['kdf']), _unb64(self.state['wrapped_key']), self._aad('key'))

    def wipe(self):
        self.lock()
        if os.path.isdir(self.dir):
            for name in os.listdir(self.dir):
                path = os.path.join(self.dir, name)
                if os.path.isfile(path) and not os.path.islink(path):
                    os.unlink(path)
        self._state = None

    # -- session -------------------------------------------------------------
    def open_session(self, vk):
        keychain.put(SESSION, vk.hex())
        self._ensure_dir()
        write_private(self.activity_path, b'')

    def lock(self):
        try:
            os.unlink(self.activity_path)
        except OSError:
            pass
        keychain.delete(SESSION)

    def session_key(self, touch=True):
        """Vault key if unlocked and not timed out, else None (and lock)."""
        try:
            last = os.stat(self.activity_path).st_mtime
        except OSError:
            return None
        if self.autolock and time.time() - last > self.autolock * 60:
            self.lock()
            return None
        value = keychain.get(SESSION)
        if not value:
            return None
        try:
            vk = bytes.fromhex(value)
        except ValueError:
            return None
        if touch:
            os.utime(self.activity_path, None)
        return vk
