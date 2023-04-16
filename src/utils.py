import os
import json
from urllib.parse import urlparse

# Env variables
user_mail = os.environ['user_mail']
incognito_mode = bool(os.environ['incognito_mode'])
sound = os.environ['sound']
cache_bool =  True if os.environ['cache_bool'] == '1' else False
cache_folder = os.environ['alfred_workflow_cache'] #  ~/Library/Caches/com.runningwithcrayons.Alfred/Workflow Data/com.benjamino.dashlane

# Notification builder
def display_notification(title, message):
    os.system(f'\'{os.getcwd()}/notificator\' --message \'{message}\' --title \'{title}\' --sound \'{sound}\'')

# extract domain from url
def extract_domain(url):
    parsed_url = urlparse(url)
    domain = parsed_url.netloc.split('.')[-2] + '.' + parsed_url.netloc.split('.')[-1]
    return domain

def get_error(ouput: str):
    e = ouput.split('ERROR: ')[1].strip()
    try:
        e = json.loads(e[e.find('{'):e.rfind('}') + 1])['errors'][0]['message']
    except:
        pass
    display_notification('🚨 Error !', f'{e}')