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

import unittest

from game_data_packager.data import (PackageRelation)
from game_data_packager.packaging.deb import (DebPackaging)

class DebTestCase(unittest.TestCase):
    def setUp(self):
        pass

    def test_rename_package(self):
        dp = DebPackaging()

        def t(in_, out):
            self.assertEqual(dp.rename_package(in_), out)

        # generic
        t('libc.so.6', 'libc6')
        t('libalut.so.0', 'libalut0')
        t('libXxf86dga.so.1', 'libxxf86dga1')
        t('libopenal.so.1', 'libopenal1')
        t('libstdc++.so.6', 'libstdc++6')
        t('libdbus-1.so.3', 'libdbus-1-3')

        # special cases
        t('libSDL-1.2.so.0', 'libsdl1.2debian')
        t('libgcc_s.so.1', 'libgcc1')
        t('libjpeg.so.62', 'libjpeg62-turbo | libjpeg62')

    def test_relation(self):
        dp = DebPackaging()

        def t(in_, out):
            self.assertEqual(
                    sorted(dp.format_relations(map(PackageRelation, in_))),
                    out)

        t(['libc.so.6'], ['libc6'])
        t(['libc.so.6 (>= 2.19)'], ['libc6 (>= 2.19)'])
        t(['libjpeg.so.62'], ['libjpeg62-turbo | libjpeg62'])
        t(['libopenal.so.1 | bundled-openal'], ['libopenal1 | bundled-openal'])
        t(['libc.so.6', 'libopenal.so.1'], ['libc6', 'libopenal1'])
        t([dict(deb='foo', rpm='bar')], ['foo'])
        t([dict(deb='foo', rpm='bar', generic='baz')], ['foo'])
        t([dict(rpm='bar', generic='baz')], ['baz'])
        t([dict(rpm='bar')], [])

    def tearDown(self):
        pass

if __name__ == '__main__':
    unittest.main(verbosity=2)
