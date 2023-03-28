import re
import os
import sys
sys.path.insert(0, './lib')
import json
from lib import pexpect
from utils import cache_folder, incognito_mode, extract_domain

# Get the query from the command line arguments
query = sys.argv[1]

# Get the request from the command line arguments passwordǀotp
request = sys.argv[2]

# Function that build json items displayed in alfred search bar
def build_json(item):
    v_title, v_url, v_email, v_login = item.get('title'), item.get('url'), item.get('email'), item.get('login')
    c_login = v_email if v_email else (v_login if v_login else 'No login')
    if incognito_mode:
        login = v_email[:2] + '•'*4 + v_email[v_email.index('@')-1:] if v_email else (v_login[:2] + '•'*4 + v_login[-1] if v_login else 'No login')
    else:
        login = c_login
    if v_url:
        domain = extract_domain(v_url)
        title = v_title if v_title else domain
    else:
        domain = 'No URL'
        title = 'No title'
    password = item.get('password', '')
    if domain != 'No URL' and os.path.isfile(os.path.join(cache_folder, f'{domain}.png')):
        iconPath = f'{cache_folder}/{domain}.png'
    else:
        letter = re.search(r"[^\W\d_]", title.lower())
        iconPath = f'icons/letter-{letter.group(0)}.webp' if letter else f'icons/question-ics.webp'
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
reset = {
    'title': 'Reset local data',
    'subtitle': 'Erase all local stored data',
    'arg': 'reset',
    'icon': {
        'path': 'icons/trash-ics.webp'
    },
}

try:
    # Try to detect if Dashlane account is sync
    process = pexpect.spawn('dcli password -o json')
    try:
        index = process.expect(['Please enter your email address:', pexpect.EOF, pexpect.TIMEOUT], timeout=10)
        output = process.before.decode().strip()
        if index == 0:
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
                }
            )
            items.extend([build_json(vault_credential) for vault_credential in json.loads(output) if not (request == 'otp' and not vault_credential.get('otpSecret'))])

        # Create the JSON object with the 'items' property
        output = {
            'items': items
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

# Print the JSON object
print(json.dumps(output))
process.terminate()