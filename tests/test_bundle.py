"""The bundled packages are complete, for the right CPUs, and found at runtime."""

import os
import platform
import re
import struct
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'src'))

import vendor  # noqa: E402
from dlw import deps  # noqa: E402

CPU = {0x0100000C: 'arm64', 0x01000007: 'x86_64'}


def macho_archs(path):
    with open(path, 'rb') as fh:
        head = fh.read(8 + 20 * 4)
    magic = head[:4]
    if magic == b'\xca\xfe\xba\xbe':  # fat, big endian
        count = struct.unpack('>I', head[4:8])[0]
        return sorted(CPU.get(struct.unpack('>I', head[8 + 20 * i:12 + 20 * i])[0], '?') for i in range(count))
    if magic == b'\xcf\xfa\xed\xfe':  # thin 64-bit, little endian
        return [CPU.get(struct.unpack('<I', head[4:8])[0], '?')]
    return []


class Bundle(unittest.TestCase):
    def test_complete(self):
        vendor.check()

    def test_cpus(self):
        rust = os.path.join(vendor.LIB, 'cryptography', 'hazmat', 'bindings', '_rust.abi3.so')
        self.assertEqual(macho_archs(rust), ['arm64', 'x86_64'])
        for arch in ('arm64', 'x86_64'):
            folder = os.path.join(vendor.LIB, '_cffi', arch)
            names = sorted(os.listdir(folder))
            self.assertEqual([re.search(r'cpython-(\d+)-darwin', n).group(1) for n in names],
                             ['310', '311', '312', '313', '314', '315', '39'])
            for name in names:
                self.assertEqual(macho_archs(os.path.join(folder, name)), [arch], name)

    def test_activate_on_mac(self):
        saved = sys.path[:], sys.platform, platform.machine
        try:
            sys.platform = 'darwin'
            platform.machine = lambda: 'arm64'
            deps.activate()
            self.assertEqual(sys.path[:2], [os.path.join(deps.LIB, '_cffi', 'arm64'), deps.LIB])
        finally:
            sys.path[:], sys.platform, platform.machine = saved

    def test_nothing_downloaded_at_runtime(self):
        for folder, _, files in os.walk(os.path.join(ROOT, 'src')):
            if os.path.join('src', 'lib') in folder:
                continue
            for name in files:
                if name.endswith('.py'):
                    with open(os.path.join(folder, name), encoding='utf-8') as fh:
                        code = fh.read()
                    self.assertNotRegex(code, r"'pip'|pypi\.org|pythonhosted", name)


if __name__ == '__main__':
    unittest.main()
