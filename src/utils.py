import os
import json
from urllib.parse import urlparse
import datetime

# Env variables
user_mail = os.environ['user_mail']
sound = os.environ['sound']
incognito_mode =  True if os.environ['incognito_mode'] == '1' else False
cache_bool =  True if os.environ['cache_bool'] == '1' else False
cache_folder = os.environ['alfred_workflow_cache'] #  ~/Library/Caches/com.runningwithcrayons.Alfred/Workflow Data/com.benjamino.dashlane

# Notification builder
def display_notification(title, message):
    os.system(f'\'{os.getcwd()}/notificator\' --message \'{message}\' --title \'{title}\' --sound \'{sound}\'')

from urllib.parse import urlparse

def extract_domain(url):
    parsed_url = urlparse(url)
    dot_count = parsed_url.netloc.count('.')
    if 1 <= dot_count <= 2:
        return '.'.join(parsed_url.netloc.split('.')[-2:])
    else:
        return parsed_url.netloc

def parse_time(unix_timestamp: int):
    try:
        date = datetime.datetime.fromtimestamp(unix_timestamp).strftime('%d-%m-%Y %H:%M:%S')
        return date
    except:
        return None
    
def get_error(ouput: str):
    e = ouput.split('ERROR: ')[1].strip()
    try:
        e = json.loads(e[e.find('{'):e.rfind('}') + 1])['errors'][0]['message']
    except:
        pass
    display_notification('🚨 Error !', f'{e}')