#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2016 Simon McVittie <smcv@debian.org>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
#
# You can find the GPL license text on a Debian system under
# /usr/share/common-licenses/GPL-2.

import hashlib
import sys
import unittest

from game_data_packager.command_line import (TerminalProgress)
from game_data_packager.data import (HashedFile)

class ZeroReader:
    def __init__(self, total):
        self.done = 0
        self.total = total

    def read(self, max_bytes):
        ret = min(max_bytes, self.total - self.done)
        self.total -= ret
        return b'\x00' * ret

SIZE = 30 * 1024 * 1024

class HashedFileTestCase(unittest.TestCase):
    def setUp(self):
        hasher = hashlib.new('md5')
        hasher.update(b'hello')
        self.HELLO_MD5 = hasher.hexdigest()
        hasher.update(b', world!')
        self.HELLO_WORLD_MD5 = hasher.hexdigest()

        hasher = hashlib.new('sha1')
        hasher.update(b'hello')
        self.HELLO_SHA1 = hasher.hexdigest()
        hasher.update(b', world!')
        self.HELLO_WORLD_SHA1 = hasher.hexdigest()

        hasher = hashlib.new('sha256')
        hasher.update(b'hello')
        self.HELLO_SHA256 = hasher.hexdigest()
        hasher.update(b', world!')
        self.HELLO_WORLD_SHA256 = hasher.hexdigest()

    def test_attrs(self):
        hf = HashedFile('hello.txt')
        self.assertIs(hf.have_hashes, False)

        hf.md5 = self.HELLO_MD5
        self.assertIs(hf.have_hashes, True)
        self.assertEqual(hf.md5, self.HELLO_MD5)

        with self.assertRaises(AssertionError):
            hf.md5 = None

        hf.sha1 = self.HELLO_SHA1
        self.assertIs(hf.have_hashes, True)
        self.assertEqual(hf.sha1, self.HELLO_SHA1)

        hf.sha256 = self.HELLO_SHA256
        self.assertIs(hf.have_hashes, True)
        self.assertEqual(hf.sha256, self.HELLO_SHA256)

    def test_matches(self):
        first = HashedFile('hello.txt')
        first.md5 = self.HELLO_MD5

        second = HashedFile('hello.txt')
        second.sha1 = self.HELLO_SHA1

        with self.assertRaises(ValueError):
            first.matches(second)

        with self.assertRaises(ValueError):
            second.matches(first)

        second.md5 = self.HELLO_MD5
        self.assertIs(first.matches(second), True)
        self.assertIs(second.matches(first), True)

        second = HashedFile('hello_world.txt')
        second.md5 = self.HELLO_WORLD_MD5
        self.assertIs(first.matches(second), False)
        self.assertIs(second.matches(first), False)

    def test_progress(self):
        print('', file=sys.stderr)
        HashedFile.from_file('progress.bin', ZeroReader(SIZE),
                size=SIZE,
                progress=TerminalProgress(interval=0.1))
        print('', file=sys.stderr)
        HashedFile.from_file('progress.bin', ZeroReader(SIZE),
                progress=TerminalProgress(interval=0.1))
        print('', file=sys.stderr)

        HashedFile.from_file('progress.bin', ZeroReader(SIZE),
                size=SIZE)
        HashedFile.from_file('progress.bin', ZeroReader(SIZE))

        print('', file=sys.stderr)
        HashedFile.from_concatenated_files('concatenated.bin',
                [ZeroReader(SIZE), ZeroReader(SIZE)],
                size=2 * SIZE,
                progress=TerminalProgress(interval=0.1))
        print('', file=sys.stderr)
        HashedFile.from_concatenated_files('concatenated.bin',
                [ZeroReader(SIZE), ZeroReader(SIZE)],
                progress=TerminalProgress(interval=0.1))
        print('', file=sys.stderr)

        HashedFile.from_concatenated_files('concatenated.bin',
                [ZeroReader(SIZE), ZeroReader(SIZE)],
                size=2 * SIZE)
        HashedFile.from_concatenated_files('concatenated.bin',
                [ZeroReader(SIZE), ZeroReader(SIZE)])

    def tearDown(self):
        pass

if __name__ == '__main__':
    unittest.main(verbosity=2)
