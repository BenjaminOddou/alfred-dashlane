import os
import re
import sys
sys.path.insert(0, './lib')
from lib import pexpect
from utils import display_notification

# Get the request from the user choice
request = os.environ['req1']
elem = os.environ['req2']

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
