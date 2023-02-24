#!/usr/bin/env python3

import os
import re
from lib import pexpect
from utils import data_folder, display_notification

# Get the request from the user choice
request = os.environ['req2']

# Ask to grab the OTP
process = pexpect.spawn(f'"{data_folder}"/dcli otp {request}')

try:
    index = process.expect(['There are multiple results for your query, pick one:', pexpect.EOF])
    if index == 0:
        display_notification('⚠️ Warning !', 'Can\'t retrieve duplicate elements. Please change names.')
        process.terminate()
    else:
        output = process.before.decode().strip()
        title = re.search(r'^([\w.-]+)', request).group(1)
        otp_code = re.search(r'\d{6}', output).group(0)
        expire_time = re.search(r'\(expires in (\d+) seconds\)', output).group(1)
        print(otp_code, end='')
        display_notification('📋 Copied !', f'The otp code {otp_code} is copied for {title}. (expires in {expire_time} seconds).')
except Exception as e:
    display_notification('🚨 Error !', f'{e}')

process.close()
