import os
import re
import sys
sys.path.insert(0, './lib')
from lib import pexpect
from utils import user_mail, display_notification, get_error, cache_folder

# Get the otp code from the user
otp_code = sys.argv[1]

# Get the request from the context
request = os.environ['req2']

# start CLI process
process = pexpect.spawn('dcli sync')
if request == 'refresh':
    process.expect(pexpect.EOF, timeout=10)
    if process.before.decode().strip() == 'Successfully synced':
        for filename in os.listdir(cache_folder):
            file_path = os.path.join(cache_folder, filename)
            try:
                if os.path.isfile(file_path) and os.path.splitext(filename)[1] == '.json':
                    os.remove(file_path)
            except Exception as e:
                display_notification('🚨 Error !', f'{e}')
        display_notification('✅ Sucess !', f'Local data has been refreshed for your account {user_mail}.')
    else:
        get_error(process.before.decode())

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
            get_error(process.before.decode())
            break

        # enter the appropriate input for each prompt
        if prompt == 'Please enter your email address:':
            process.sendline(user_mail)
        elif prompt == ['Please enter the code you received by email:', 'Please enter your OTP code:']:
            process.sendline(otp_code)
        elif prompt == 'Please enter your master password:':
            process.sendline(user_password)
            try:
                index = process.expect(['The master password you provided is incorrect, would you like to retry?', pexpect.EOF, pexpect.TIMEOUT], timeout=10)
                if index == 0:
                    process.sendline('No')
                    display_notification('⚠️ Warning !', 'The master password you provided is incorrect, please retry.')
                    new_process = pexpect.spawn('dcli reset')
                    index = new_process.expect('Do you really want to delete all local data from this app?')
                    new_process.sendline('Yes')
                else:
                    display_notification('✅ Sucess !', f'You\'re connected as {user_mail}.')
            except pexpect.exceptions.TIMEOUT:
                display_notification('⌛ Timeout !', 'The connection was not established.')