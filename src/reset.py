import os
import sys
sys.path.insert(0, './lib')
from lib import pexpect
from utils import cache_folder, display_notification

# Get the confirmation value from user input, yes to confirm
confirm_value = sys.argv[1]

if confirm_value.lower() != 'yes':
    display_notification('⚠️ Warning !', 'Action canceled by the user.')
else:
    process = pexpect.spawn('dcli reset')
    try:
        index = process.expect(['Do you really want to delete all local data from this app?', pexpect.EOF, pexpect.TIMEOUT], timeout=10)
        if index == 0:
            # Send 'Yes' if a prompt is detected
            process.sendline('Yes')
            process.expect(pexpect.EOF, timeout=10)
            for filename in os.listdir(cache_folder):
                file_path = os.path.join(cache_folder, filename)
                try:
                    if os.path.isfile(file_path):
                        os.remove(file_path)
                except Exception as e:
                    display_notification('🚨 Error !', f'{e}')
            display_notification('✅ Success !', 'Local data have been reset correctly.')
        else:
            display_notification('🚨 Error !', 'Something went wrong.')
    except Exception as e:
        display_notification('🚨 Error !', f'{e}')

process.terminate()
