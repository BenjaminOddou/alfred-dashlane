import sys
sys.path.insert(0, './lib')
from lib import pexpect
from utils import user_mail, display_notification, get_error

# Run the dcli sync command, wait for the email prompt and enter the email address
process = pexpect.spawn('dcli sync')
process.expect('Please enter your email address:')
process.sendline(user_mail)

# Wait for the output message
try:
    index = process.expect(['Please enter the code you received by email:', 'Please enter your OTP code:'], timeout=10)
    if index == 0:
        display_notification('✅ Success !', f'A mail has been sent to {user_mail}.')
    elif index == 1:
        display_notification('⚠️ Warning !', 'Your account is already linked to a 2FA app.')
except pexpect.EOF:
    get_error(process.before.decode())
except pexpect.TIMEOUT:
    display_notification('⌛ Timeout !', 'The command didn\'t finished properly.')

process.terminate()