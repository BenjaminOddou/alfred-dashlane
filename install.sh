#!/bin/bash

# Link to last release : https://api.github.com/repos/Dashlane/dashlane-cli/releases/latest
# Prefer known version to prevent bugs and breaking changes
curl -LJO -H 'Accept: application/octet-stream' \
`curl -s https://api.github.com/repos/Dashlane/dashlane-cli/releases/tags/v1.0.0 \
| python3 -c 'import sys, json; print([asset["browser_download_url"] for asset in json.load(sys.stdin)["assets"] if "dcli-macos" in asset["name"]][0])'` \
&& mv dcli-macos dcli \
&& chmod +x dcli

dirpath=$(dirname $(find /Users/benjaminoddou/Library/Application\ Support/Alfred/Alfred.alfredpreferences/workflows -name 'com.benjamino.dashlane' -type f))
dirname=$(basename "$dirpath")

if [ -z "$dirpath" ]; then
    destination="$HOME/Downloads"
    mv dcli "$destination"
    echo "🚨 Error ! Dashlane workflow not found, dcli was moved to Downloads folder"
else
    destination="/Users/benjaminoddou/Library/Application Support/Alfred/Alfred.alfredpreferences/workflows/$dirname/dcli"
    mkdir -p "$destination"
    mv dcli "$destination"
    echo "✅ Success ! Dashlane CLI is installed correctly"
fi

