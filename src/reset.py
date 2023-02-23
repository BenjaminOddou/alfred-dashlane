#!/usr/bin/env python3

import os
import sys
import pexpect
from utils import data_folder, display_notification

# Get the confirmation value from user input, yes to confirm
confirm_value = sys.argv[1]

if confirm_value.lower() != 'yes':
    display_notification('⚠️ Warning !', 'Action canceled by the user.')
else:
    process = pexpect.spawn('dcli/dcli reset')
    try:
        index = process.expect(['Do you really want to delete all local data from this app?', pexpect.EOF, pexpect.TIMEOUT], timeout=5)
        if index == 0:
            # Send 'Yes' if a prompt is detected
            process.sendline('Yes')
            process.expect(pexpect.EOF, timeout=5)
            for filename in os.listdir(data_folder):
                file_path = os.path.join(data_folder, filename)
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

process.close()
