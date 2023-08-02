import os
import re
import sys
sys.path.insert(0, './lib')
from lib import pexpect
from utils import display_notification, cache_folder

confirm_value = sys.argv[1]

# Get the request from the user choice
request, elem, extra = os.getenv('req1'), os.getenv('req2'), os.getenv('req3')

if request in ['_password', '_otp']:
    process = pexpect.spawn(f'dcli {request.split("_")[1]} id={elem}')
    try:
        process.expect(pexpect.EOF, timeout=10)
        output = process.before.decode().strip()
        f_output = re.sub(r'\x1b\[\d+m', '', output.replace('🔓 ', '').replace('🔢 ', '').strip())
        if request == '_otp':
            display_notification('📋 Copied !', f_output)
        elif request == '_password':
            display_notification('📋 Copied !', f_output)
    except Exception as e:
        display_notification('🚨 Error !', f'{e}')
elif '_device' in request:
    if request == '_deviceconfirm' and confirm_value.lower() != 'yes':
        display_notification('⚠️ Warning !', 'Action canceled by the user.')
        exit()
    process = pexpect.spawn(f'dcli devices remove {elem}')
    print(f'dcli devices remove {elem}')
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