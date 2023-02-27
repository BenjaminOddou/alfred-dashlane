#!/usr/bin/env python3

from lib import pexpect
from utils import data_folder, user_mail, display_notification

# Run the dcli sync command, wait for the email prompt and enter the email address
process = pexpect.spawn(f'"{data_folder}"/dcli sync')
process.expect('Please enter your email address:')
process.sendline(user_mail)

# Wait for the output message
try:
    index = process.expect(['Please enter the code you received by email:', 'Please enter your OTP code:'], timeout=5)
    if index == 0:
        display_notification('✅ Success !', f'A mail has been sent to {user_mail}.')
    elif index == 1:
        display_notification('⚠️ Warning !', 'Your account is already linked to a 2FA app.')
except pexpect.EOF:
    e = process.before.decode('utf-8').split('DashlaneApiError: ')[1].split('\n')[0]
    display_notification('🚨 Error !', f'{e}')
except pexpect.TIMEOUT:
    display_notification('⌛ Timeout !', 'The command didn\'t finished properly.')

process.terminate()