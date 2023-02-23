#!/bin/bash

# Link to last release : https://api.github.com/repos/Dashlane/dashlane-cli/releases/latest
# Prefer known version to prevent bugs and breaking changes
curl -LJO -H 'Accept: application/octet-stream' \
`curl -s https://api.github.com/repos/Dashlane/dashlane-cli/releases/tags/v1.0.0 \
| python3 -c 'import sys, json; print([asset["browser_download_url"] for asset in json.load(sys.stdin)["assets"] if "dcli-macos" in asset["name"]][0])'` \
&& mv dcli-macos dcli \
&& chmod +x dcli

workflow_data_folder=~/Library/Application\ Support/Alfred/Workflow\ Data/com.benjamino.dashlane

if [ -z "$workflow_data_folder" ]; then
    mv dcli "$HOME/Downloads"
    echo "🚨 Error ! Dashlane workflow not found, dcli was moved to Downloads folder"
else
    mkdir -p "$workflow_data_folder/dcli"
    mv dcli "$workflow_data_folder/dcli"
    sudo xattr -r -d com.apple.quarantine "$(dirname "$(find ~/Library/Application\ Support/Alfred/Alfred.alfredpreferences/workflows -name 'com.benjamino.dashlane' -type f)")/alfred_dashlane_notification.app"
    echo "✅ Success ! Dashlane CLI is installed correctly"
fi