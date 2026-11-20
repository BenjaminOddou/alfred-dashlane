"""Small text helpers shared by the index builder and the Script Filter."""

import re
import unicodedata
from urllib.parse import urlsplit

_HOST = re.compile(r'^[a-z0-9.-]+$')


def plain(text):
    """Lowercase, accent-free form used for sorting, letter icons and matching."""
    decomposed = unicodedata.normalize('NFKD', text.casefold())
    return ''.join(c for c in decomposed if not unicodedata.combining(c))


def extract_domain(url):
    """'https://accounts.example.com/x' -> 'example.com' (same rule as v1)."""
    if not url:
        return ''
    if '://' not in url:
        url = 'https://' + url
    try:
        host = (urlsplit(url).hostname or '').strip('.').lower()
    except ValueError:
        return ''
    if not _HOST.match(host):
        return ''
    parts = host.split('.')
    if 2 <= len(parts) <= 3 and not host.replace('.', '').isdigit():
        return '.'.join(parts[-2:])
    return host
