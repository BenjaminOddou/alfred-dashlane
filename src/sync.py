#!/usr/bin/env python3

import os
import re
import sys
import pexpect
from utils import data_folder, user_mail, display_notification

# Get the otp code from the user
otp_code = sys.argv[1]

# Get the request from the context
request = os.environ['req2']

# start CLI process
cli = pexpect.spawn(f'"{data_folder}"/dcli/dcli sync')
if request == 'refresh':
    try:
        cli.expect(pexpect.EOF, timeout=5)
        if cli.before:
            e = cli.before.decode().split('RequestError: ')[1].split('\n')[0]
            display_notification('🚨 Error !', f'{e}')
        elif os.environ['req2'] == 'refresh':
            display_notification('✅ Sucess !', f'Local data has been refreshed for your account {user_mail}.')
    except Exception as e:
        display_notification('🚨 Error !', f'{e}')

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
            cli.expect(prompt)
        except pexpect.EOF:
            e = cli.before.decode().split('DashlaneApiError: ')[1].split('\n')[0]
            display_notification('🚨 Error !', f'{e}')
            break

        # enter the appropriate input for each prompt
        if prompt == 'Please enter your email address:':
            cli.sendline(user_mail)
        elif prompt == ['Please enter the code you received by email:', 'Please enter your OTP code:']:
            cli.sendline(otp_code)
        elif prompt == 'Please enter your master password:':
            cli.sendline(user_password)
            try:
                cli.expect('The master password you provided is incorrect, would you like to retry?')
                cli.sendline('No')
                display_notification('⚠️ Warning !', 'The master password you provided is incorrect.')
            except:
                display_notification('✅ Sucess !', f'You\'re connected as {user_mail}.')

cli.close()