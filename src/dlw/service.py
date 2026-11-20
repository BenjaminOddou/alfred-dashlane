"""Dashlane account operations: device registration, unlock, sync, devices."""

import base64

from . import api, vault
from .opaque import ClientLogin, OpaqueError, argon2id_ksf

# Dashlane OPAQUE server identity and pinned static key (dashlane-cli constants).
OPAQUE_SERVER_ID = b'api.dashlane.com'
OPAQUE_SERVER_PK = 'rjMOj0DcV7XqxiaS2vbw9s1ri4MwcbooW-ztusqFFmk'
OPAQUE_KSF = (3, 65536, 4)


class ServiceError(Exception):
    pass


class WrongMasterPassword(ServiceError):
    pass


class Cancelled(ServiceError):
    pass


def _b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def _unb64url(text):
    return base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))


def remote_mode(methods):
    remote = methods.get('remoteAuthentications') or []
    totp = [m for m in remote if m.get('type') == 'totp']
    if totp:
        return 'totp_login' if totp[0].get('requiredOnLogin') else 'totp_new_device'
    if any(m.get('type') == 'securityKey' for m in remote):
        return 'security_key'
    if any(m.get('type') == 'emailToken' for m in remote):
        return 'email_token'
    raise ServiceError('This account uses an unsupported 2FA method')


def opaque_login(client, login, password, auth_ticket):
    """Prove the master password with OPAQUE. Returns a strong auth ticket."""
    attempt = ClientLogin(password)
    try:
        started = api.request_opaque_login(client, login, auth_ticket, _b64url(attempt.start()))
    except api.ApiError as exc:
        if exc.code == 'OPAQUE_MASTER_PASSWORD_NOT_REGISTERED':
            raise ServiceError('Log in once with another Dashlane app (extension, mobile) first')
        raise
    try:
        result = attempt.finish(_unb64url(started['loginResponse']), argon2id_ksf(*OPAQUE_KSF),
                                server_identity=OPAQUE_SERVER_ID)
    except OpaqueError:
        raise WrongMasterPassword('Wrong master password')
    if _b64url(result['server_public_key']) != OPAQUE_SERVER_PK:
        raise ServiceError('Unexpected Dashlane server key, login aborted')
    try:
        done = api.complete_opaque_login(client, login, auth_ticket, _b64url(result['finish_request']),
                                         started['opaqueMPLoginFlowId'])
    except api.ApiError as exc:
        if exc.code == 'OPAQUE_LOGIN_FAILED':
            raise WrongMasterPassword('Wrong master password')
        raise
    return done['authTicket']['ticket']


def register_device(client, login, token_request_id, token, ask_password):
    """Register this Mac as a Dashlane device.

    ask_password(attempt) returns the master password or None to cancel.
    Returns dict(access_key, secret_key, secret, auth_mode).
    """
    try:
        ticket = api.perform_token_verification(client, login, {
            'tokenRequestId': token_request_id, 'token': token, 'intent': 'token:new_device',
        })['authTicket']['ticket']
    except api.ApiError as exc:
        raise ServiceError('Code rejected: %s' % exc)
    methods = api.get_authentication_methods(client, login, auth_ticket=ticket)
    local = [m.get('type') for m in methods.get('localAuthentications') or []]
    if 'sso' in local:
        raise ServiceError('SSO accounts are not supported')
    if 'masterPassword' not in local:
        raise ServiceError('Only master password accounts are supported')
    mode = remote_mode(methods)

    strong = password = None
    for attempt in range(3):
        password = ask_password(attempt)
        if password is None:
            raise Cancelled('Login cancelled')
        try:
            strong = opaque_login(client, login, password, ticket)
            break
        except WrongMasterPassword:
            if attempt == 2:
                raise
    reg = api.complete_device_registration(client, login, strong, api.device_name())
    if reg.get('ssoServerKey'):
        raise ServiceError('SSO accounts are not supported')
    secret = password
    if mode == 'totp_login':
        if not reg.get('serverKey'):
            raise ServiceError('Missing server key for 2FA account')
        secret = reg['serverKey'] + password
    return {'access_key': reg['deviceAccessKey'], 'secret_key': reg['deviceSecretKey'],
            'secret': secret, 'auth_mode': mode}


def server_key_for_unlock(client, login, access_key, otp):
    """Accounts with 2FA at each login: trade an OTP for the server key."""
    try:
        ticket = api.perform_token_verification(client, login, {
            'token': otp, 'intent': 'login', 'deviceAccessKey': access_key,
        })['authTicket']['ticket']
    except api.ApiError as exc:
        raise ServiceError('Code rejected: %s' % exc)
    key = api.complete_login(client, login, ticket, access_key).get('serverKey')
    if not key:
        raise ServiceError('Dashlane did not return the server key')
    return key


def check_team_2fa(client, login, device, mode):
    status = api.get_premium_status(client, login, device)
    team = ((status.get('b2bStatus') or {}).get('currentTeam') or {}).get('teamInfo') or {}
    if team.get('twoFAEnforced') in ('newDevice', 'login') and mode == 'email_token':
        raise ServiceError('Your team enforces 2FA: set it up in Dashlane first')


def sync(client, login, device, secret, data):
    """Fetch and apply new transactions. `data` is the decrypted secrets dict (mutated).

    Returns the number of credential changes.
    """
    content = api.get_latest_content(client, login, device, int(data.get('ts') or 0))
    items = data.setdefault('items', {})
    derivates = data.setdefault('derivates', {})
    changes = failures = credentials = 0
    for tr in content.get('transactions') or []:
        ident, kind, action = tr.get('identifier'), tr.get('type'), tr.get('action')
        if action == 'BACKUP_REMOVE':
            if items.pop(ident, None) is not None:
                changes += 1
            continue
        # Only credentials are kept; SETTINGS_userId is decrypted to check the master password.
        check = ident == 'SETTINGS_userId'
        if action != 'BACKUP_EDIT' or (kind != 'AUTHENTIFIANT' and not check):
            continue
        try:
            plain = vault.decrypt(tr['content'], secret, derivates)
        except (vault.DecryptError, ValueError, KeyError):
            if check:
                raise WrongMasterPassword('Vault cannot be decrypted (master password changed?) - log in again')
            failures += 1
            continue
        if kind == 'AUTHENTIFIANT':
            credentials += 1
            try:
                _, fields = vault.parse_item(plain)
            except vault.DecryptError:
                failures += 1
                continue
            items[ident] = fields
            changes += 1
    if failures and not credentials:
        raise WrongMasterPassword('Vault cannot be decrypted (master password changed?) - log in again')
    data['ts'] = int(content.get('timestamp') or data.get('ts') or 0)
    return changes


def build_index(items):
    """What the Script Filter shows: no password, no OTP secret. Pre-sorted, domains pre-parsed."""
    from .text import extract_domain, plain
    out = []
    for ident, f in items.items():
        domain = extract_domain(f.get('Url') or f.get('UserSelectedUrl') or '')
        title = f.get('Title') or domain or 'No title'
        out.append({
            'id': ident,
            'title': title,
            'key': plain(title),
            'domain': domain,
            'login': f.get('Email') or f.get('Login') or f.get('SecondaryLogin') or '',
            'otp': bool(f.get('OtpSecret') or f.get('OtpUrl')),
        })
    out.sort(key=lambda e: e['key'])
    return out
