#!/usr/bin/env python3

import json
import pexpect
import requests
import tldextract
from utils import data_folder, display_notification

def download_favicon(url):
    '''
    Downloads the favicon of size 128 from the given domain (extracted with tldextract) using the Google icon API.
    Returns True if the download was successful, False otherwise.
    Icons are located in this folder : ~/Library/Application Support/Alfred/Workflow Data/com.benjamino.dashlane
    '''
    domain = tldextract.extract(url).registered_domain
    api_url = f'https://www.google.com/s2/favicons?domain={domain}&sz=128'

    response = requests.get(api_url)
    if response.status_code != 200:
        return False

    filename = f'{domain}.png'
    with open(f'{data_folder}/{filename}', 'wb') as f:
        f.write(response.content)
    return True

process = pexpect.spawn('dcli/dcli password -o json')
process.expect(pexpect.EOF)
output = process.before.decode().strip()
display_notification('⏳ Please wait !', 'Downloading favicons...')
for item in json.loads(output):
    if item.get('url'):
        download_favicon(item.get('url'))
display_notification('👀 Finished !', 'All icons are located in the workflow data folder.')