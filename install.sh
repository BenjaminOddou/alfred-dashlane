#!/bin/bash

# Link to last release : https://api.github.com/repos/Dashlane/dashlane-cli/releases/latest
cd "$(dirname "$(find ~/Library/Application\ Support/Alfred/Alfred.alfredpreferences/workflows -name 'com.benjamino.dashlane' -type f)")"
brew install --build-from-source dashlane-cli.rb