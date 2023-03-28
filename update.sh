#!/bin/bash

mkdir -p lib
# Install platform agnostic version of requests python dependency
pip3 install requests -t lib --platform macosx-10.9-x86_64 --only-binary=:all: --upgrade
pip3 install pexpect -t lib