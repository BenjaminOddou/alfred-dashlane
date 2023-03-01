#!/usr/bin/env python3

import os

# Env variables
user_mail = os.environ['user_mail']
incognito_mode = bool(os.environ['incognito_mode'])
sound = os.environ['sound']

# Alfred const
data_folder = os.environ['alfred_workflow_data'] # ~/Library/Application Support/Alfred/Workflow Data/com.benjamino.dashlane
cache_folder = os.environ['alfred_workflow_cache'] #  ~/Library/Caches/com.runningwithcrayons.Alfred/Workflow Data/com.benjamino.dashlane

# Notification builder
def display_notification(title, message):
    os.system(f'\'{os.getcwd()}/notificator\' --message \'{message}\' --title \'{title}\' --sound \'{sound}\'')