#!/usr/bin/env python3

import os
import re
import sys
from lib import pexpect
from utils import data_folder, user_mail, display_notification

# Get the otp code from the user
otp_code = sys.argv[1]

# Get the request from the context
request = os.environ['req2']

# start CLI process
process = pexpect.spawn(f'"{data_folder}"/dcli sync')
if request == 'refresh':
    process.expect(pexpect.EOF, timeout=5)
    if process.before:
        e = process.before.decode().split('RequestError: ')[1].split('\n')[0]
        display_notification('🚨 Error !', f'{e}')
    else:
        display_notification('✅ Sucess !', f'Local data has been refreshed for your account {user_mail}.')

elif request == 'login':
    # Get the user password from the user
    user_password = os.environ['user_password']

    if not re.match(r'^\d{6}$', otp_code):
        display_notification('⚠️ Warning !', 'The OTP should be a 6 digits code.')
        exit()
    
    # List all prompts
    expect_prompts = [
        'Please enter your email address:', 
        ['Please enter the code you received by email:', 'Please enter your OTP code:'], 
        'Please enter your master password:'
        ]
    display_notification('⏳ Please wait !', f'Trying to connect to Dashlane account : {user_mail}...')
    for prompt in expect_prompts:
        try:
            process.expect(prompt)
        except pexpect.EOF:
            e = process.before.decode().split('DashlaneApiError: ')[1].split('\n')[0]
            display_notification('🚨 Error !', f'{e}')
            break

        # enter the appropriate input for each prompt
        if prompt == 'Please enter your email address:':
            process.sendline(user_mail)
        elif prompt == ['Please enter the code you received by email:', 'Please enter your OTP code:']:
            process.sendline(otp_code)
        elif prompt == 'Please enter your master password:':
            process.sendline(user_password)
            try:
                process.expect('The master password you provided is incorrect, would you like to retry?')
                process.sendline('No')
                display_notification('⚠️ Warning !', 'The master password you provided is incorrect.')
            except:
                display_notification('✅ Sucess !', f'You\'re connected as {user_mail}.')

process.terminate()