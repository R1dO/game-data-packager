#!/usr/bin/python

import io
import struct
import unittest

from game_data_packager.unpack.umod import Umod

HELLO_TXT = b'Hello, world!\n'

MANIFEST_INT = b'''[Setup]\r
LocalProduct=Example Mod\r
ReadMe=Help\\Hello.txt\r
ProductURL=http://example.com/\r
VersionURL=http://example.com/example100/\r
Developer=Game Data Packager\r
DeveloperURL=https://tracker.debian.org/pkg/game-data-packager\r
Logo=Help\\Logo.bmp'''

MANIFEST_INI = ('''[Setup]\r
Product=ExampleMod\r
Version=100\r
Requires=DebianRequirement\r
SrcPath=C:\\temp\r
Group=SetupGroup\r
Group=HelpGroup\r
\r
[DebianRequirement]\r
Product=Debian\r
Version=8\r
\r
[SetupGroup]\r
Copy=(Src=System\\Manifest.ini,Master=System\\Manifest.ini,Size=1234,Flags=3)\r
Copy=(Src=System\\Manifest.int,Master=System\\Manifest.int,Size=%d,Flags=3)\r
\r
[HelpGroup]\r
File=(Src=Help\\Hello.txt,Size=%d)\r
\r
''' % (len(MANIFEST_INT), len(HELLO_TXT))).encode('ascii')

def get_sample_umod():
    def sized_string(b):
        return bytes([len(b) + 1]) + b + b'\0'

    ret = []
    offset = 0
    ret.append(MANIFEST_INI)
    ret.append(MANIFEST_INT)
    ret.append(HELLO_TXT)
    ret.append(b'\x03')
    ret.append(sized_string(b'System\\Manifest.ini'))
    ret.append(struct.pack('<III', offset, len(MANIFEST_INI), 3))
    offset += len(MANIFEST_INI)
    ret.append(sized_string(b'System\\Manifest.int'))
    ret.append(struct.pack('<III', offset, len(MANIFEST_INT), 3))
    offset += len(MANIFEST_INT)
    ret.append(sized_string(b'Help\\Hello.txt'))
    ret.append(struct.pack('<III', offset, len(HELLO_TXT), 3))
    offset += len(HELLO_TXT)

    ret = [b''.join(ret)]

    ret.append(struct.pack('<IIIII',
        0x9fe3c5a3,         # magic number
        offset,             # offset of table-of-contents
        len(ret[0]) + 20,   # total file length
        1,                  # flags, seem to be 1 in real umods
        0xdeadbeef))        # checksum, not checked at the moment
    return b''.join(ret)

SAMPLE_UMOD = get_sample_umod()

class UmodTestCase(unittest.TestCase):
    def setUp(self):
        self.umod = Umod(io.BytesIO(SAMPLE_UMOD))

    def test_basics(self):
        self.assertEqual(self.umod.product, 'ExampleMod')
        self.assertEqual(self.umod.version, '100')
        self.assertEqual(sorted(self.umod.requirements.keys()),
                ['DebianRequirement'])
        self.assertEqual([s.name for s in self.umod.sections],
                ['DebianRequirement', 'SetupGroup', 'HelpGroup'])
        self.assertEqual(sorted(self.umod.groups.keys()),
                ['HelpGroup', 'SetupGroup'])
        self.assertEqual(self.umod.entry_order,
                ['System/Manifest.ini', 'System/Manifest.int',
                    'Help/Hello.txt'])
        self.assertEqual(sorted(self.umod.entries.keys()),
                ['Help/Hello.txt', 'System/Manifest.ini',
                    'System/Manifest.int'])
        self.assertEqual(list(self.umod.unparsed),
                [('SrcPath', 'C:\\temp')])

        with self.umod.open('Help/Hello.txt') as hello:
            self.assertEqual(hello.read(5), HELLO_TXT[:5])
            self.assertEqual(hello.read(), HELLO_TXT[5:])

    def tearDown(self):
        del self.umod

if __name__ == '__main__':
    unittest.main(verbosity=2)
