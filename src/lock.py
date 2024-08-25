import os
import sys
sys.path.insert(0, './lib')
import json
from lib import pexpect
from utils import cache_folder, display_notification

request = os.environ['req2']

try:
    if request == 'lock':
        process = pexpect.spawn('dcli lock')
        process.expect(pexpect.EOF, timeout=5)
        for filename in os.listdir(cache_folder):
            file_path = os.path.join(cache_folder, filename)
            if os.path.isfile(file_path) and os.path.splitext(filename)[1] == '.json':
                with open(file_path, 'r') as file:
                    data = json.load(file)
                data['info']['lock'] = True
                with open(file_path, 'w') as file:
                    json.dump(data, file, ensure_ascii=False, indent=4)
        display_notification('✅ Success !', 'Your Dashlane account have been locked.')
    elif request == 'unlock':
        user_password = os.environ['user_password']
        process = pexpect.spawn('dcli sync')
        process.expect('Please enter your master password:')
        process.sendline(user_password)
        process.expect(pexpect.EOF, timeout=5)
        display_notification('✅ Sucess !', 'You unlock your Dashlane account.')
        print(f'_rerun\t0\t{os.environ['req3']}', end='')
except Exception as e:
    display_notification('🚨 Error !', f'{e}')
