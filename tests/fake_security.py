#!/usr/bin/env python3
"""Stand-in for /usr/bin/security: dcli's keychain item exists while unlocked."""

import json
import os
import sys

with open(os.environ['FAKE_DCLI_STATE']) as fh:
    state = json.load(fh)
args = sys.argv[1:]
account = args[args.index('-a') + 1]
ok = args[0] == 'find-generic-password' and state['logged_in'] and not state['locked'] \
    and state.get('login') == account and '-w' not in args
sys.exit(0 if ok else 44)
