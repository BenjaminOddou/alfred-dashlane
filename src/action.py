import os
import sys
import subprocess
sys.path.insert(0, './lib')
from lib import pexpect
from utils import display_notification, cache_folder

confirm_value = sys.argv[1]

# Get the request from the user choice
request, elem, extra = os.getenv('req1'), os.getenv('req2'), os.getenv('req3')

if request in ['_credentials', '_password', '_otp']:
    convert = {'_credentials': {'query' : 'password'}, '_password': {'query' : 'password', 'name': 'Password'}, '_otp': {'query': 'otpSecret?otp+expiry', 'name': 'OTP'}}
    process = pexpect.spawn(f'dcli read "dl://{elem}/{convert[request]["query"]}"')
    try:
        process.expect(pexpect.EOF, timeout=10)
        output = process.before.decode().strip()
        if request == '_credentials':
            script = f'''
                tell application "System Events"
                    keystroke "{extra}"
                    key code 48 -- Tab key
                    keystroke "{output}"
                end tell
            '''
            subprocess.run(['osascript', '-e', script])
        else:
            more = ''
            if request == '_otp':
                more = f' (expires in {output.split(" ")[1]} seconds)'
            print(output.split(' ')[0], end='')
            display_notification('📋 Copied !', f'{convert[request]["name"]} for "{extra}" copied to clipboard{more}')
    except Exception as e:
        display_notification('🚨 Error !', f'{e}')
elif '_device' in request:
    if request == '_deviceconfirm' and confirm_value.lower() != 'yes':
        display_notification('⚠️ Warning !', 'Action canceled by the user')
        exit()
    process = pexpect.spawn(f'dcli devices remove {elem}')
    try:
        if elem == '--all':
            index = process.expect(['Do you really want to logout and delete all local data from this app?'])
            if index == 0:
                process.sendline('Yes')
                process.expect(pexpect.EOF, timeout=10)
                for filename in os.listdir(cache_folder):
                    file_path = os.path.join(cache_folder, filename)
                    if os.path.isfile(file_path) and os.path.splitext(filename)[1] == '.json':
                        os.remove(file_path)
                display_notification('✅ Success !', 'All devices were removed')
        elif elem == '--others':
            process.expect(pexpect.EOF, timeout=10)
            display_notification('✅ Success !', 'All devices except the current one were removed')
        else:
            process.expect(pexpect.EOF, timeout=10)
            display_notification('✅ Success !', f'The device {extra} was removed')
    except Exception as e:
        display_notification('🚨 Error !', f'{e}')