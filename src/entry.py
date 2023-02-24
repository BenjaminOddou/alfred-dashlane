#!/usr/bin/env python3

import os
import sys
import json
from lib import pexpect
from lib import tldextract
from utils import cache_folder, data_folder, incognito_mode

# Get the query from the command line arguments
query = sys.argv[1]

# Get the request from the command line arguments passwordǀotp
request = sys.argv[2]

# Function that build json items displayed in alfred search bar
def build_json(item):
    v_url = item.get('url')
    v_email = item.get('email')
    v_login = item.get('login')
    c_login = login = v_email or v_login or 'No login'
    if incognito_mode:
        login = v_email[:2] + '•'*4 + v_email[v_email.index('@')-1:] if v_email else v_login[:2] + '•'*4 + v_login[-1] if v_login else 'No login'
    else:
        login = c_login
    title = item.get('title') or v_url.split('/')[2] if v_url else 'No title'
    password = item.get('password', '')
    domain = tldextract.extract(v_url).registered_domain if v_url else 'No URL'
    if domain != 'No URL' and os.path.exists(os.path.join(f'{cache_folder}', f'{domain}.png')):
        iconPath = f'{cache_folder}/{domain}.png'
    else:
        iconPath = f'icons/letter-{title[:1].lower()}.webp'
    if request == 'otp':
         json_obj = {
            'title': title,
            'subtitle': f'{login} ǀ Press ⏎ to copy otp',
            'arg': f'_otp\t{title} - {c_login}',
            'icon': {
                'path': iconPath,
            },
            'action': {
                'text': f'Title: {title}\nLogin: {c_login}',
            },
            'otpSecret': item.get('otpSecret'),
            'mods': {
                mod: {
                    'valid': False, 
                    'subtitle': f'{login} ǀ Press ⏎ to copy otp',
                } 
                for mod in ['cmd', 'alt', 'ctrl']
            }
         }
    else:
        path = v_url if v_url else ''
        json_obj = {
            'title': title,
            'subtitle': f'{login} ǀ Press ⏎ to copy password',
            'arg': f'_pss\t{password}',
            'icon': {
                'path': iconPath,
            },
            'quicklookurl': f'{path}',
            'action': {
                'text': f'Title: {title}\nLogin: {c_login}\nPassword: {password}\nURL: {v_url}',
            },
            'mods': {
                'cmd': {
                    'subtitle': f'{login} ǀ Press ⏎ to copy login',
                    'arg': f'_login\t{c_login}',
                },
                'alt': {
                    'subtitle': f'{domain} ǀ Press ⏎ to open url',
                    'arg': f'_url\t{path}',
                },
                'ctrl': {
                    'valid': False,
                    'subtitle': f'{login} ǀ Press ⏎ to copy password',
                },
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
        'mods': {
            mod: {
                'valid': False, 
                'subtitle': 'Manually sync your account',
            } 
            for mod in ['cmd', 'alt', 'ctrl']
        }
    },
]
reset = {
    'title': 'Reset local data',
    'subtitle': 'Erase all local stored data',
    'arg': 'reset',
    'icon': {
        'path': 'icons/trash-ics.webp'
    },
    'mods': {
        mod: {
            'valid': False, 
            'subtitle': 'Erase all local stored data',
        } 
        for mod in ['cmd', 'alt', 'ctrl']
    }
}

try:
    # Try to detect if Dashlane account is sync
    process = pexpect.spawn(f'"{data_folder}"/dcli password -o json')
    try:
        index = process.expect(['Please enter your email address:', pexpect.EOF, pexpect.TIMEOUT], timeout=5)
        output = process.before.decode().strip()
        #########
        if output == '?':
            items[0]['arg'] = '_sync\tlogin'
            items.append(reset)
            items.append(
                {
                    'title': 'Get your OTP code by mail',
                    'subtitle': 'Receive your 6 digits OTP code by mail (only if you don\'t use a 2FA app)',
                    'arg': 'get_otp',
                    'icon': {
                        'path': 'icons/otp-ics.webp'
                    },
                    'mods': {
                        mod: {
                            'valid': False, 
                            'subtitle': 'Receive your 6 digits OTP code by mail (only if you don\'t use a 2FA app)',
                        } 
                        for mod in ['cmd', 'alt', 'ctrl']
                    }           
                }
            )
        else:
            items[0]['arg'] = '_sync\trefresh'
            items.append(reset)
            items.append(
                {
                    'title': 'Download favicons',
                    'subtitle': 'For each password element, download correponding favicon if available',
                    'arg': 'icons',
                    'icon': {
                        'path': 'icons/download-ics.webp'
                    },
                    'mods': {
                        mod: {
                            'valid': False, 
                            'subtitle': 'For each password element, download correponding favicon if available',
                        } 
                        for mod in ['cmd', 'alt', 'ctrl']
                    } 
                }
            )
            items.extend([build_json(vault_credential) for vault_credential in json.loads(output) if not (request == 'otp' and not vault_credential.get('otpSecret'))])

        # Filter the items based on the query
        filtered_items = [item for item in items if query.lower() in item['title'].lower() or query.lower() in item['subtitle'].lower()]

        # Create the JSON object with the 'items' property
        output = {
            'items': filtered_items
        }
    except Exception as e:
        output = {
            'items': [
                {
                    'title': 'Something went wrong !',
                    'subtitle': f'{e} ǀ Press ⏎ to create an issue in GitHub',
                    'arg': '_url\thttps://github.com/BenjaminOddou/alfred-dashlane/issues/new',
                    'quicklookurl': 'https://github.com/BenjaminOddou/alfred-dashlane/issues/new',
                    'icon': {
                        'path': 'icons/error-ics.webp'
                    },
                    'mods': {
                        mod: {
                            'valid': False, 
                            'subtitle': f'{e} ǀ Press ⏎ to create an issue in GitHub',
                        } 
                        for mod in ['cmd', 'alt', 'ctrl']
                    }
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
                'mods': {
                    mod: {
                        'valid': False, 
                        'subtitle': 'Press ⏎ to check the documentation on GitHub',
                    } 
                    for mod in ['cmd', 'alt', 'ctrl']
                }
            }
        ]
    }

# Print the JSON object
print(json.dumps(output))
process.close()