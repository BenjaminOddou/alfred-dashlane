#!/usr/bin/env python3

import os
import subprocess

# Env variables
user_mail = os.environ['user_mail']
incognito_mode = bool(os.environ['incognito_mode'])
sound = os.environ['sound']

# Alfred const
data_folder = os.environ['alfred_workflow_data'] # ~/Library/Application Support/Alfred/Workflow Data/com.benjamino.dashlane
cache_folder = os.environ['alfred_workflow_cache'] #  ~/Library/Caches/com.runningwithcrayons.Alfred/Workflow Data/com.benjamino.dashlane

# Notification builder
notif_app = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'alfred_dashlane_notification.app')
def display_notification(title, message):
    cmd = ['open', '-ga', notif_app, '--args', message, title]
    if sound:
        cmd.append(sound)
    subprocess.run(cmd)