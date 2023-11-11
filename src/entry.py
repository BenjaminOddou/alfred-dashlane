import re
import os
import sys
sys.path.insert(0, './lib')
import json
from lib import pexpect
from utils import cache_folder, incognito_mode, extract_domain, cache_bool, user_mail, parse_time

# Get the query from the command line arguments
query = sys.argv[1]

# Get the request from the command line arguments passwordǀotp
request = sys.argv[2]

level = int(os.getenv('req2', 0))
special = os.getenv('req4')

# Function that build json items displayed in alfred search bar
def build_vault(item):
    v_title, v_url, v_email, v_login, v_id = item.get('title'), item.get('url', ''), item.get('email'), item.get('login'), item.get('id')[1:-1]
    c_login = v_email if v_email else (v_login if v_login else 'No login')
    if incognito_mode:
        login = v_email[:2] + '•' * 4 + v_email[v_email.index('@')-1:] if v_email else (v_login[:2] + '•' * 4 + v_login[-1] if v_login else 'No login')
    else:
        login = c_login
    if v_url != '':
        domain = extract_domain(v_url)
        title = v_title if v_title else domain
    else:
        domain = 'No URL'
        title = v_title if v_title else 'No title'
    if domain != 'No URL' and os.path.isfile(os.path.join(cache_folder, f'{domain}.png')):
        iconPath = f'{cache_folder}/{domain}.png'
    else:
        letter = re.search(r"[^\W\d_]", title.lower())
        iconPath = f'icons/letter-{letter.group(0)}.webp' if letter else f'icons/question-ics.webp'
    json_obj = {
        'title': title,
        'subtitle': f'{login} ǀ Press ⏎ to copy {request}',
        'arg': f'_{request}\t{v_id}\t{title}',
        'icon': {
            'path': iconPath,
        },
        'mods': {
            'cmd': {
                'subtitle': f'{login} ǀ Press ⏎ to copy login',
                'arg': f'_login\t{c_login}',
            },
            'alt': {
                'subtitle': f'{domain} ǀ Press ⏎ to open url',
                'arg': f'_url\t{v_url}' if v_url != '' and domain != 'No URL' else '',
            },
            'shift': {
                'subtitle': f'{login} ǀ Press ⏎ to inject credentials to frontmost app',
                'arg': f'_credentials\t{v_id}\t{c_login}',
            },
        }
    }
    return json_obj

def build_devices(item):
    d_id, d_name, d_current, d_createT, d_accessT = item.get('deviceId'), item.get('deviceName'), item.get('isCurrentDevice'), item.get('creationDateUnix'), item.get('lastActivityDateUnix')
    title = f'{d_name} (Current)' if d_current else d_name
    json_obj = {
        'title': title,
        'subtitle': f'Created : {parse_time(d_createT)} ǀ Last Accessed : {parse_time(d_accessT)}',
        'valid': False,
        'icon': {
            'path': 'icons/devices-ics.webp',
        },
        'mods': {
            'cmd': {
                'subtitle': 'Press ⏎ to remove the device',
                'arg': 'logout' if d_current else f'_device\t{d_id}\t{d_name}',
                'icon': {
                    'path': 'icons/delete-ics.webp',
                },
            }
        }
    }
    return json_obj

# Define common objects
items = [
    {
        'title': 'Sync your Dashlane account',
        'subtitle': 'Manually sync your account',
        'arg': '',
        'icon': {
            'path': 'icons/sync-ics.webp'
        },
    },
]
download_favicons = {
    'title': 'Download favicons',
    'subtitle': 'For each password element, download correponding favicon if available',
    'arg': 'icons',
    'icon': {
        'path': 'icons/download-ics.webp'
    },
}
reset = {
    'title': 'Logout',
    'subtitle': 'Erase all local stored data',
    'arg': 'logout',
    'icon': {
        'path': 'icons/delete-ics.webp'
    },
}
get_otp = {
    'title': 'Get your OTP code by mail',
    'subtitle': 'Receive your 6 digits OTP code by mail (only if you don\'t use a 2FA app)',
    'arg': 'get_otp',
    'icon': {
        'path': 'icons/otp-ics.webp'
    },          
}
devices = {
    'title': 'Devices',
    'subtitle': 'Manage devices connected to your account',
    'arg': f'_rerun\t1\t{request}\tdevices',
    'icon': {
        'path': 'icons/devices-ics.webp'
    },          
}

if level == 0:
    output = ''
    if not os.path.exists(f'{cache_folder}'):
        os.mkdir(f'{cache_folder}')
    cache_data = os.path.join(cache_folder, f'{request}_{user_mail}.json')
    if cache_bool and os.path.isfile(cache_data) and os.path.getsize(cache_data) != 0:
        with open(cache_data, 'r') as file:
            output = json.load(file)
        if output['info']['incognito_mode'] != incognito_mode:
            output = ''
    if output == '':
        try:
            process = pexpect.spawn('dcli password -o json')
            try:
                index = process.expect(['Please enter your email address:', pexpect.EOF, pexpect.TIMEOUT], timeout=10)
                output = process.before.decode().strip()
                if index == 0:
                    items[0]['arg'] = '_sync\tlogin'
                    items += [reset, get_otp]
                    output = {'items': items}
                else:
                    items[0]['arg'] = '_sync\trefresh'
                    items += [reset, download_favicons, devices]
                    process2 = pexpect.spawn('dcli password -o json')
                    process2.expect(pexpect.EOF, timeout=10)
                    resp = process2.before.decode().strip()
                    items.extend([build_vault(vault_credential) for vault_credential in json.loads(resp) if not (request == 'otp' and not vault_credential.get('otpSecret'))])
                    output = { 'info': { 'incognito_mode': incognito_mode }, 'items': items }
                    if os.path.isfile(cache_data):                    
                        os.remove(cache_data)
                    if cache_bool:
                        with open(cache_data, 'w') as file:
                            json.dump(output, file, indent=4)
            except Exception as e:
                output = {
                    'items': [
                        {
                            'title': 'Something went wrong !',
                            'subtitle': f'{e} ǀ Press ⏎ to create an issue in GitHub',
                            'arg': '_url\thttps://github.com/BenjaminOddou/alfred-dashlane/issues/new',
                            'quicklookurl': 'https://github.com/BenjaminOddou/alfred-dashlane/issues/new',
                            'icon': {
                                'path': 'icons/info-ics.webp'
                            },
                        },
                        reset
                    ]
                }
        except Exception as e:
            output = {
                'items': [
                    {
                        'title': 'Dashlane CLI is not detected',
                        'subtitle': 'Press ⏎ to check the documentation on GitHub',
                        'arg': '_url\thttps://github.com/BenjaminOddou/alfred-dashlane',
                        'quicklookurl': 'https://github.com/BenjaminOddou/alfred-dashlane',
                        'icon': {
                            'path': 'icons/info-ics.webp'
                        },
                    }
                ]
            }
else:
    items = [
        {
            'title': 'Return',
            'subtitle': 'Back to previous state',
            'arg': f'_rerun\t{level - 1}\t{request}',
            'icon': {
                'path': 'icons/return-ics.webp',
            },
        }
    ]
    if level == 1 and special == 'devices':
        items += [
            {
                'title': 'Delete All',
                'subtitle': 'Remove all devices (including current) from your vault',
                'arg': '_deviceconfirm\t--all',
                'icon': {
                    'path': 'icons/delete-ics.webp'
                },
            },
            {
                'title': 'Delete Others',
                'subtitle': 'Remove all devices (excepting current) from your vault',
                'arg': '_deviceconfirm\t--others',
                'icon': {
                    'path': 'icons/delete-ics.webp'
                },
            }
        ]
        devices = pexpect.spawn('dcli devices list --json')
        devices.expect(pexpect.EOF, timeout=10)
        resp = devices.before.decode().strip()
        items.extend([build_devices(device) for device in json.loads(resp)])
    output = {'items': items}


# Print the JSON object
print(json.dumps(output))