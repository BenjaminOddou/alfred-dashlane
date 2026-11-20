"""TOTP / HOTP codes (RFC 6238 / RFC 4226)."""

import base64
import hashlib
import hmac
import struct
import time
from urllib.parse import parse_qs, unquote, urlparse

_ALGOS = {'SHA1': hashlib.sha1, 'SHA256': hashlib.sha256, 'SHA512': hashlib.sha512}


def _b32(secret):
    secret = ''.join(unquote(secret).split()).replace('-', '').upper().rstrip('=')
    return base64.b32decode(secret + '=' * (-len(secret) % 8))


def hotp(key, counter, digits=6, algo='SHA1'):
    digest = hmac.new(key, struct.pack('>Q', counter), _ALGOS[algo]).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(code % 10 ** digits).zfill(digits)


def generate(secret=None, uri=None, now=None):
    """Return (code, seconds_left or None)."""
    now = time.time() if now is None else now
    kind, digits, period, algo, counter = 'totp', 6, 30, 'SHA1', 0
    if uri:
        parsed = urlparse(uri)
        query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        kind = (parsed.netloc or 'totp').lower()
        secret = query.get('secret', secret)
        digits = int(query.get('digits') or 6)
        period = int(query.get('period') or 30)
        algo = (query.get('algorithm') or 'SHA1').upper()
        counter = int(query.get('counter') or 0)
        if algo not in _ALGOS or kind not in ('totp', 'hotp'):
            raise ValueError('unsupported OTP parameters')
    if not secret:
        raise ValueError('no OTP secret')
    key = _b32(secret)
    if kind == 'hotp':
        return hotp(key, counter, digits, algo), None
    step = int(now // period)
    return hotp(key, step, digits, algo), int(period - now % period)
