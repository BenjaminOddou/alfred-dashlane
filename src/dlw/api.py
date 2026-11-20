"""Signed calls to the Dashlane server API (DL1-HMAC-SHA256), stdlib only.

Same protocol and public app keys as the open-source Dashlane CLI
(https://github.com/Dashlane/dashlane-cli, Apache-2.0).
"""

import hashlib
import hmac
import http.client
import json
import os
import platform
import ssl
import time

HOST = 'api.dashlane.com'
CLI_VERSION = '6.2647.2'
APP_ACCESS_KEY = 'HB9JQATDY6Y62JYKT7KXBN4C7FH8HKC5'
APP_SECRET_KEY = 'boUtXxmDgLUtNFaigCMQ3+u+LAx0tg1ePAUE13nkR7dto+Zwq1naOHZTwbxxM7iL'
USER_AGENT = 'Dashlane CLI v' + CLI_VERSION
ALGORITHM = 'DL1-HMAC-SHA256'
TIMEOUT = 20


class ApiError(Exception):
    def __init__(self, message, code='', status=0):
        Exception.__init__(self, message)
        self.code = code
        self.status = status


def _sha256_hex(data):
    return hashlib.sha256(data).hexdigest()


def sign(path, body, headers, timestamp, app_secret=APP_SECRET_KEY, auth_fields=(), device_secret=None):
    """Return the Authorization header value for a POST on `path` (no leading slash)."""
    signed = sorted((k.lower(), ' '.join(str(v).strip().split())) for k, v in headers.items()
                    if k.lower() in ('content-type', 'user-agent'))
    canonical = '\n'.join([
        'POST',
        '/' + path,
        '',
        ''.join('%s:%s\n' % kv for kv in signed),
        ';'.join(k for k, _ in signed),
        _sha256_hex(body),
    ])
    string_to_sign = '\n'.join([ALGORITHM, str(timestamp), _sha256_hex(canonical.encode())])
    key = app_secret if device_secret is None else app_secret + '\n' + device_secret
    signature = hmac.new(key.encode(), string_to_sign.encode(), hashlib.sha256).hexdigest()
    fields = list(auth_fields) + [
        'Timestamp=%d' % timestamp,
        'SignedHeaders=' + ';'.join(k for k, _ in signed),
        'Signature=' + signature,
    ]
    return ALGORITHM + ' ' + ','.join(fields)


def _ssl_context():
    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    try:  # python.org builds ship without system roots: add certifi's bundle
        import certifi
        ctx.load_verify_locations(certifi.where())
    except Exception:
        pass
    return ctx


class Client:
    """Keeps one TLS connection open for all calls of a run."""

    def __init__(self, host=HOST, context=None):
        self.host = host
        self._context = context
        self._conn = None
        self._agent = json.dumps({
            'version': CLI_VERSION,
            'platform': 'server_cli',
            'osversion': 'darwin-' + (platform.machine() or 'unknown'),
            'partner': 'dashlane',
        }, separators=(',', ':'))

    def _connection(self):
        if self._conn is None:
            if self._context is None:
                self._context = _ssl_context()
            self._conn = http.client.HTTPSConnection(self.host, timeout=TIMEOUT, context=self._context)
        return self._conn

    def close(self):
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def post(self, path, payload, login=None, device=None):
        """POST to /v1/<path>. `device` = (access_key, secret_key) for user calls."""
        path = 'v1/' + path
        body = json.dumps(payload, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
        headers = {'content-type': 'application/json', 'user-agent': USER_AGENT}
        if device:
            fields = ['Login=' + login, 'AppAccessKey=' + APP_ACCESS_KEY, 'DeviceAccessKey=' + device[0]]
            secret = device[1]
        else:
            fields, secret = ['AppAccessKey=' + APP_ACCESS_KEY], None
        for attempt in range(3):
            send = dict(headers)
            send['Authorization'] = sign(path, body, headers, int(time.time()), auth_fields=fields,
                                         device_secret=secret)
            send['dashlane-client-agent'] = self._agent
            send['Host'] = self.host
            try:
                conn = self._connection()
                conn.request('POST', '/' + path, body=body, headers=send)
                resp = conn.getresponse()
                raw = resp.read()
                status = resp.status
                break
            except (OSError, http.client.HTTPException) as exc:
                self.close()
                if attempt == 2 or isinstance(exc, ssl.SSLCertVerificationError):
                    raise ApiError('Network error: %s' % (exc.__class__.__name__ if not str(exc) else exc))
                time.sleep(0.4 * (attempt + 1))
        try:
            data = json.loads(raw.decode('utf-8'))
        except ValueError:
            raise ApiError('Unexpected server answer (HTTP %d)' % status, status=status)
        if status != 200 or 'errors' in data:
            err = (data.get('errors') or [{}])[0]
            raise ApiError(err.get('message') or 'HTTP %d' % status, err.get('code', ''), status)
        return data.get('data', {})


# --- Endpoints --------------------------------------------------------------

def perform_token_verification(c, login, verification):
    return c.post('authentication/PerformTokenVerification', {'login': login, 'verification': verification})


def get_authentication_methods(c, login, auth_ticket=None, device_access_key=None):
    payload = {'login': login}
    if auth_ticket:
        payload['authTicket'] = auth_ticket
    else:
        payload['deviceAccessKey'] = device_access_key
    return c.post('authentication/GetAuthenticationMethods', payload)


def request_opaque_login(c, login, auth_ticket, login_request):
    return c.post('authentication/RequestOpaqueMPLoginWithAuthTicket',
                  {'authTicket': auth_ticket, 'login': login, 'loginRequest': login_request})


def complete_opaque_login(c, login, auth_ticket, finish_request, flow_id):
    return c.post('authentication/CompleteOpaqueMPLoginWithAuthTicket',
                  {'authTicket': auth_ticket, 'login': login, 'finishLoginRequest': finish_request,
                   'opaqueMPLoginFlowId': flow_id})


def complete_device_registration(c, login, auth_ticket, device_name):
    return c.post('authentication/CompleteDeviceRegistrationWithAuthTicket', {
        'device': {
            'deviceName': device_name,
            'appVersion': CLI_VERSION,
            'platform': 'server_cli',
            'osCountry': 'en_US',
            'osLanguage': 'en_US',
            'temporary': False,
        },
        'login': login,
        'authTicket': auth_ticket,
    })


def complete_login(c, login, auth_ticket, device_access_key):
    return c.post('authentication/CompleteLoginWithAuthTicket',
                  {'login': login, 'authTicket': auth_ticket, 'deviceAccessKey': device_access_key})


def get_latest_content(c, login, device, timestamp):
    return c.post('sync/GetLatestContent',
                  {'timestamp': timestamp, 'needsKeys': False, 'teamAdminGroups': False, 'transactions': []},
                  login, device)


def get_premium_status(c, login, device):
    return c.post('premium/GetPremiumStatus', {}, login, device)


def list_devices(c, login, device):
    return c.post('devices/ListDevices', {}, login, device)


def deactivate_devices(c, login, device, device_ids):
    return c.post('devices/DeactivateDevices', {'deviceIds': device_ids}, login, device)


def device_name():
    name = (os.uname().nodename or 'Mac').split('.')[0]
    return 'Alfred - %s' % name
