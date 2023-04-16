import os
import json
import sys
sys.path.insert(0, './lib')
from lib import pexpect
from lib import requests
from utils import cache_folder, display_notification, extract_domain

def download_favicon(url):
    '''
    Downloads the favicon of size 128 from the given domain using the Google icon API.
    Returns True if the download was successful, False otherwise.
    Icons are located in the cache folder : ~/Library/Caches/com.runningwithcrayons.Alfred/Workflow Data/com.benjamino.dashlane
    '''
    domain = extract_domain(url)
    api_url = f'https://www.google.com/s2/favicons?domain={domain}&sz=128'

    response = requests.get(api_url)
    if response.status_code != 200:
        return False

    filename = f'{domain}.png'
    with open(f'{cache_folder}/{filename}', 'wb') as f:
        f.write(response.content)
    return True

process = pexpect.spawn('dcli password -o json')
process.expect(pexpect.EOF)
output = process.before.decode().strip()
for filename in os.listdir(cache_folder):
    file_path = os.path.join(cache_folder, filename)
    try:
        if os.path.isfile(file_path) and os.path.splitext(filename)[1] == '.json':
            os.remove(file_path)
    except Exception as e:
        display_notification('🚨 Error !', f'{e}')
display_notification('⏳ Please wait !', 'Downloading favicons...')
for item in json.loads(output):
    if item.get('url'):
        download_favicon(item.get('url'))
display_notification('👀 Finished !', 'All icons are located in the workflow cache folder.')