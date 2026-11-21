#!/usr/bin/env python3
"""Stand-in for the Dashlane CLI, driven through a pty like the real one.

State lives in the JSON file named by $FAKE_DCLI_STATE. Prompts and messages
copy dcli 6.x (inquirer prompts, "error: ..." lines, exit code 1 on error).
Answered prompts are redrawn with a "✔" prefix, as inquirer does.
"""

import json
import os
import sys

STATE = os.environ['FAKE_DCLI_STATE']
TOKEN = '0f8fad5b-d9cb-469f-a165-70867728950e'


def load():
    with open(STATE) as fh:
        return json.load(fh)


def save(state):
    with open(STATE, 'w') as fh:
        json.dump(state, fh)


def log(state, entry):
    state.setdefault('log', []).append(entry)
    save(state)


def ask(message, secret=False):
    sys.stdout.write('? %s ' % message)
    sys.stdout.flush()
    answer = sys.stdin.readline().rstrip('\n')
    shown = '*' * len(answer) if secret else answer
    sys.stdout.write('\r\x1b[2K\x1b[32m✔\x1b[39m %s %s\n' % (message, shown))  # redraw
    sys.stdout.flush()
    return answer


def fail(message):
    sys.stderr.write('\x1b[31merror: %s\x1b[39m\n' % message)
    sys.exit(1)


def unlock(state):
    if state.get('totp'):
        if ask('Please enter your OTP code:') != '123456':
            fail('{"errors":[{"type":"business_error","code":"VERIFICATION_FAILED","message":"Invalid OTP"}]}')
    if ask('Please enter your master password:', secret=True) != state['mp']:
        fail('mismatching signatures')
    state['locked'] = False
    save(state)


def prepare(state):
    """connectAndPrepare: register when logged out, unlock when locked."""
    if not state['logged_in']:
        email = ask('Please enter your email address:')
        print('info: Please open the following URL in your browser: '
              'https://www.dashlane.com/cli-device-registration?login=%s' % email.replace('@', '%40'))
        if ask('Please enter the token given in the browser:') != TOKEN:
            fail('Token request ID is invalid')
        if ask('Please enter the code you received by email or the one from your authenticator if you set up '
               '2FA on your account:') != '123456':
            fail('Invalid token')
        if ask('Please enter your master password:', secret=True) != state['mp']:
            fail('Error while verifying the master password, wrong master password')
        state.update(logged_in=True, locked=False, login=email)
        save(state)
    elif state['locked']:
        unlock(state)


def find(state, path):
    item_id = path[5:].split('/')[0].split('?')[0]
    for item in state['items']:
        if item['id'].strip('{}') == item_id:
            return item
    fail('No matching item found for "%s"' % item_id)


def main(args):
    state = load()
    log(state, args)
    cmd = args[0]
    if cmd == 'lock':
        prepare(state)
        state['locked'] = True
        save(state)
        return
    if cmd == 'logout':
        if ask('Do you really want to logout and delete all local data from this app? (y/N)').lower() != 'y':
            return
        if state['logged_in']:
            prepare(state)
        state.update(logged_in=False, locked=False)
        save(state)
        print('✔ The local Dashlane local storage has been reset and you have been logged out.')
        return
    prepare(state)
    state = load()
    if cmd == 'sync':
        print('\x1b[32m✔\x1b[39m Successfully synced')
    elif cmd == 'password':
        print(json.dumps(state['items']))
    elif cmd == 'read':
        path = args[1]
        item = find(state, path)
        if path.endswith('?otp+expiry') or path.endswith('?otp_uri+expiry'):
            print('123456 17')
        elif path.count('/') == 3:
            print(item[path.split('/')[3]])
        else:
            print(json.dumps(item))
    elif cmd == 'devices' and args[1] == 'list':
        print(json.dumps(state['devices']))
    elif cmd == 'devices' and args[1] == 'remove':
        if args[2] == '--all':
            if ask('Do you really want to logout and delete all local data from this app? (y/N)').lower() != 'y':
                return
            state.update(devices=[], logged_in=False)
        elif args[2] == '--others':
            state['devices'] = [d for d in state['devices'] if d['isCurrentDevice']]
        else:
            state['devices'] = [d for d in state['devices'] if d['deviceId'] != args[2]]
        save(state)
    else:
        fail('unknown command')


if __name__ == '__main__':
    main(sys.argv[1:])
