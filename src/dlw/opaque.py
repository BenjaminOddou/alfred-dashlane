"""OPAQUE client login (RFC 9807), suite ristretto255-SHA512 + 3DH.

Wire compatible with opaque-ke 4 / @serenity-kit/opaque 1.x, which is what
Dashlane uses to check the master password without ever sending it.
"""

import hashlib
import hmac
import secrets

from .ristretto import BASE, L, Point, scalar_to_bytes

NN = 32  # nonce length
NH = 64  # SHA-512 output
NPK = 32  # ristretto255 element

_OPRF_CONTEXT = b'OPRFV1-\x00-ristretto255-SHA512'


class OpaqueError(Exception):
    pass


def _sha512(*parts):
    h = hashlib.sha512()
    for part in parts:
        h.update(part)
    return h.digest()


def _i2osp(value, length):
    return value.to_bytes(length, 'big')


def expand_message_xmd(msg, dst, length):
    """RFC 9380 expand_message_xmd with SHA-512."""
    ell = -(-length // 64)
    if ell > 255 or length > 65535 or len(dst) > 255:
        raise OpaqueError('expand_message_xmd: bad length')
    dst_prime = dst + _i2osp(len(dst), 1)
    b0 = _sha512(b'\x00' * 128, msg, _i2osp(length, 2), b'\x00', dst_prime)
    out = b_prev = _sha512(b0, b'\x01', dst_prime)
    for i in range(2, ell + 1):
        b_prev = _sha512(bytes(x ^ y for x, y in zip(b0, b_prev)), _i2osp(i, 1), dst_prime)
        out += b_prev
    return out[:length]


def hash_to_group(msg):
    return Point.from_uniform_bytes(expand_message_xmd(msg, b'HashToGroup-' + _OPRF_CONTEXT, 64))


def hash_to_scalar(msg, dst):
    return int.from_bytes(expand_message_xmd(msg, dst, 64), 'little') % L


def derive_key_pair(seed, info):
    """RFC 9497 DeriveKeyPair (OPRF mode)."""
    derive_input = seed + _i2osp(len(info), 2) + info
    for counter in range(256):
        sk = hash_to_scalar(derive_input + _i2osp(counter, 1), b'DeriveKeyPair' + _OPRF_CONTEXT)
        if sk:
            return sk, BASE * sk
    raise OpaqueError('DeriveKeyPair failed')


def _hmac(key, *parts):
    h = hmac.new(key, digestmod=hashlib.sha512)
    for part in parts:
        h.update(part)
    return h.digest()


def hkdf_extract(salt, ikm):
    return _hmac(salt or b'\x00' * NH, ikm)


def hkdf_expand(prk, info, length):
    out, block, counter = b'', b'', 1
    while len(out) < length:
        block = _hmac(prk, block, info, bytes([counter]))
        out += block
        counter += 1
    return out[:length]


def _expand_label(secret, label, context, length=NH):
    full = b'OPAQUE-' + label
    info = _i2osp(length, 2) + _i2osp(len(full), 1) + full + _i2osp(len(context), 1) + context
    return hkdf_expand(secret, info, length)


def _random_scalar():
    return secrets.randbelow(L - 1) + 1


def _with_len(data):
    return _i2osp(len(data), 2) + data


class ClientLogin:
    """One login attempt. Call start(), send the request, then finish()."""

    def __init__(self, password):
        if isinstance(password, str):
            password = password.encode('utf-8')
        self._password = password
        self._blind = _random_scalar()
        element = hash_to_group(password)
        if element.is_identity():
            raise OpaqueError('invalid input')
        self._blinded = (element * self._blind).encode()
        self._client_nonce = secrets.token_bytes(NN)
        self._e_sk = _random_scalar()
        self._e_pk = (BASE * self._e_sk).encode()

    def start(self):
        """KE1 message: blinded element || client nonce || client keyshare."""
        return self._blinded + self._client_nonce + self._e_pk

    def finish(self, response, ksf, server_identity=None, client_identity=None, context=b''):
        """Process KE2. Returns dict(finish_request, session_key, export_key, server_public_key).

        Raises OpaqueError when the password is wrong or the response is invalid.
        """
        if len(response) != NPK + NN + NPK + NN + NH + NN + NPK + NH:
            raise OpaqueError('invalid server response length')
        evaluated = response[:32]
        masking_nonce = response[32:64]
        masked_response = response[64:192]
        server_nonce = response[192:224]
        server_e_pk_bytes = response[224:256]
        server_mac = response[256:320]

        if hmac.compare_digest(evaluated, self._blinded):
            raise OpaqueError('reflected value')

        # OPRF finalize
        try:
            unblinded = (Point.decode(evaluated) * pow(self._blind, -1, L)).encode()
        except ValueError as exc:
            raise OpaqueError(str(exc))
        oprf_output = _sha512(_with_len(self._password), _with_len(unblinded), b'Finalize')

        stretched = ksf(oprf_output)
        randomized_password = hkdf_extract(b'', oprf_output + stretched)

        masking_key = hkdf_expand(randomized_password, b'MaskingKey', NH)
        pad = hkdf_expand(masking_key, masking_nonce + b'CredentialResponsePad', NPK + NN + NH)
        clear = bytes(x ^ y for x, y in zip(pad, masked_response))
        server_pk_bytes, env_nonce, env_tag = clear[:32], clear[32:64], clear[64:]

        # Recover client keys from the envelope
        seed = hkdf_expand(randomized_password, env_nonce + b'PrivateKey', 32)
        client_sk, client_pk = derive_key_pair(seed, b'OPAQUE-DeriveDiffieHellmanKeyPair')
        client_pk_bytes = client_pk.encode()
        auth_key = hkdf_expand(randomized_password, env_nonce + b'AuthKey', NH)
        export_key = hkdf_expand(randomized_password, env_nonce + b'ExportKey', NH)
        server_id = server_identity if server_identity is not None else server_pk_bytes
        client_id = client_identity if client_identity is not None else client_pk_bytes
        cleartext = server_pk_bytes + _with_len(server_id) + _with_len(client_id)
        if not hmac.compare_digest(_hmac(auth_key, env_nonce, cleartext), env_tag):
            raise OpaqueError('wrong password')

        try:
            server_pk = Point.decode(server_pk_bytes)
            server_e_pk = Point.decode(server_e_pk_bytes)
        except ValueError as exc:
            raise OpaqueError(str(exc))
        if server_pk.is_identity() or server_e_pk.is_identity():
            raise OpaqueError('invalid server key')

        # 3DH
        preamble = b''.join([
            b'OPAQUEv1-', _with_len(context),
            _with_len(client_id), self.start(),
            _with_len(server_id), evaluated, masking_nonce, masked_response,
            server_nonce, server_e_pk_bytes,
        ])
        ikm = (server_e_pk * self._e_sk).encode() + (server_pk * self._e_sk).encode() \
            + (server_e_pk * client_sk).encode()
        prk = hkdf_extract(b'', ikm)
        transcript = _sha512(preamble)
        handshake_secret = _expand_label(prk, b'HandshakeSecret', transcript)
        session_key = _expand_label(prk, b'SessionKey', transcript)
        km2 = _expand_label(handshake_secret, b'ServerMAC', b'')
        km3 = _expand_label(handshake_secret, b'ClientMAC', b'')
        if not hmac.compare_digest(_hmac(km2, transcript), server_mac):
            raise OpaqueError('server authentication failed')
        client_mac = _hmac(km3, _sha512(preamble, server_mac))

        return {
            'finish_request': client_mac,
            'session_key': session_key,
            'export_key': export_key,
            'server_public_key': server_pk_bytes,
        }


def argon2id_ksf(iterations, memory, parallelism):
    """Key stretching used by @serenity-kit/opaque: Argon2id, 16 zero bytes salt."""
    from cryptography.hazmat.primitives.kdf.argon2 import Argon2id

    def ksf(data):
        return Argon2id(salt=b'\x00' * 16, length=len(data), iterations=iterations,
                        lanes=parallelism, memory_cost=memory).derive(data)
    return ksf


__all__ = ['ClientLogin', 'OpaqueError', 'argon2id_ksf', 'scalar_to_bytes']
