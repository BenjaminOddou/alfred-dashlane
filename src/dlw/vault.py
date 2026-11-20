"""Decrypt Dashlane vault transactions.

Format "$1$<kdf>$<params>$aes256$cbchmac$16$" + salt + iv + hmac + ciphertext,
see dashlane-cli src/modules/crypto.
"""

import base64
import hashlib
import hmac
import zlib
from xml.etree import ElementTree

KEPT_FIELDS = ('Id', 'Title', 'Url', 'UserSelectedUrl', 'Login', 'Email', 'SecondaryLogin',
               'Password', 'OtpSecret', 'OtpUrl')


class DecryptError(Exception):
    pass


def parse(blob):
    """Split an encrypted blob. Returns (cfg, salt, iv, mac, ciphertext, cache_key)."""
    def take():
        nonlocal pos
        end = blob.index(b'$', pos)
        value = blob[pos:end].decode('ascii')
        pos = end + 1
        return value

    pos = 0
    try:
        if take() != '' or take() != '1':
            raise DecryptError('unsupported payload version')
        cfg = {'algo': take()}
        if cfg['algo'] == 'argon2d':
            cfg.update(salt_len=int(take()), t=int(take()), m=int(take()), p=int(take()))
        elif cfg['algo'] == 'pbkdf2':
            cfg.update(salt_len=int(take()), iterations=int(take()), hash=take())
        elif cfg['algo'] == 'noderivation':
            cfg['salt_len'] = 0
        else:
            raise DecryptError('unknown key derivation ' + cfg['algo'])
        if take() != 'aes256':
            raise DecryptError('unknown cipher')
        cfg['mode'] = take()
        if cfg['mode'] not in ('cbchmac', 'cbchmac64'):
            raise DecryptError('unknown cipher mode')
        iv_len = int(take())
    except (ValueError, UnicodeDecodeError):
        raise DecryptError('malformed payload')
    salt_end = pos + cfg['salt_len']
    salt = blob[pos:salt_end]
    iv = blob[salt_end:salt_end + iv_len]
    mac = blob[salt_end + iv_len:salt_end + iv_len + 32]
    ciphertext = blob[salt_end + iv_len + 32:]
    return cfg, salt, iv, mac, ciphertext, blob[:salt_end]


def derive(cfg, salt, secret):
    """Key derivation from the master password (str)."""
    if cfg['algo'] == 'argon2d':
        from cryptography.hazmat.primitives.kdf.argon2 import Argon2d
        return Argon2d(salt=salt, length=32, iterations=cfg['t'], lanes=cfg['p'],
                       memory_cost=cfg['m']).derive(secret.encode('utf-8'))
    if cfg['algo'] == 'pbkdf2':
        return hashlib.pbkdf2_hmac(cfg['hash'], secret.encode('utf-8'), salt, cfg['iterations'], 32)
    return base64.b64decode(secret)


def decrypt_raw(cipher_key, iv, mac, ciphertext, inflated=False):
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    if inflated:
        if len(cipher_key) != 64:
            raise DecryptError('bad key length')
        combined = cipher_key
    else:
        combined = hashlib.sha512(cipher_key).digest()
    expected = hmac.new(combined[32:], iv + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, mac):
        raise DecryptError('mismatching signatures')
    decryptor = Cipher(algorithms.AES(combined[:32]), modes.CBC(iv)).decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    return unpadder.update(padded) + unpadder.finalize()


def decrypt(content_b64, secret, derivates):
    """Decrypt one transaction content. `derivates` caches keys per KDF header + salt."""
    blob = base64.b64decode(content_b64)
    cfg, salt, iv, mac, ciphertext, cache_key = parse(blob)
    ck = base64.b64encode(cache_key).decode()
    key = derivates.get(ck)
    if key is None:
        key = derive(cfg, salt, secret)
    else:
        key = base64.b64decode(key)
    plain = decrypt_raw(key, iv, mac, ciphertext, cfg['mode'] == 'cbchmac64')
    derivates[ck] = base64.b64encode(key).decode()
    return plain


def parse_item(plain):
    """Inflate + parse the XML of a decrypted transaction. Returns (kind, fields)."""
    try:
        xml = zlib.decompress(plain[6:], -15)
        root = ElementTree.fromstring(xml)
    except (zlib.error, ElementTree.ParseError):
        raise DecryptError('malformed transaction')
    node = root[0] if len(root) else root
    fields = {}
    for child in node:
        if child.tag == 'KWDataItem' and child.get('key') in KEPT_FIELDS and child.text:
            fields[child.get('key')] = child.text
    return node.tag, fields
