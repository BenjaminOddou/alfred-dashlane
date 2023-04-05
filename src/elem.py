import os
import re
import sys
sys.path.insert(0, './lib')
from lib import pexpect
from utils import display_notification, get_error

# Get the request from the user choice
request = os.environ['req1']
elem = os.environ['req2']

process = pexpect.spawn(f'dcli {request.split("_")[1]} id={elem}')
try:
    process.expect(pexpect.EOF, timeout=10)
    output = process.before.decode().strip()
    if request == '_otp':
        f_output = re.sub(r'\x1b\[\d+m', '', output.replace('🔢', '').strip())
        display_notification('📋 Copied !', f'{f_output}')
        print(f'{output.replace("🔢 ", "")}')
except Exception as e:
    display_notification('🚨 Error !', f'{e}')

process.terminate()
