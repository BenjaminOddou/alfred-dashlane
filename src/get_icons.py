#!/usr/bin/env python3

import os
import json
from lib import pexpect
from lib import requests
from lib import tldextract
from utils import cache_folder, data_folder, display_notification

def download_favicon(url):
    '''
    Downloads the favicon of size 128 from the given domain (extracted with tldextract) using the Google icon API.
    Returns True if the download was successful, False otherwise.
    Icons are located in the cache folder :  ~/Library/Caches/com.runningwithcrayons.Alfred/Workflow Data/com.benjamino.dashlane
    '''
    domain = tldextract.extract(url).registered_domain
    api_url = f'https://www.google.com/s2/favicons?domain={domain}&sz=128'

    response = requests.get(api_url)
    if response.status_code != 200:
        return False

    filename = f'{domain}.png'
    with open(f'{cache_folder}/{filename}', 'wb') as f:
        f.write(response.content)
    return True

process = pexpect.spawn(f'"{data_folder}"/dcli password -o json')
process.expect(pexpect.EOF)
output = process.before.decode().strip()
display_notification('⏳ Please wait !', 'Downloading favicons...')
if not os.path.exists(f'{cache_folder}'):
    os.mkdir(f'{cache_folder}')
for item in json.loads(output):
    if item.get('url'):
        download_favicon(item.get('url'))
display_notification('👀 Finished !', 'All icons are located in the workflow cache folder.')