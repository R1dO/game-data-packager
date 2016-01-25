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
from game_data_packager.packaging.rpm import (RpmPackaging)

class RpmTestCase(unittest.TestCase):
    def setUp(self):
        pass

    def test_relation(self):
        # a random distribution that we don't actually support
        rp = RpmPackaging('caldera')

        def t(in_, out):
            self.assertEqual(
                    sorted(rp.format_relations(map(PackageRelation, in_))),
                    out)

        t(['libc.so.6'], ['libc.so.6'])
        t(['libc.so.6 (>= 2.19)'], ['libc.so.6 >= 2.19'])
        t(['libjpeg.so.62'], ['libjpeg.so.62'])
        t(['libc.so.6', 'libopenal.so.1'], ['libc.so.6', 'libopenal.so.1'])
        t([dict(deb='foo', rpm='bar')], ['bar'])
        t([dict(deb='foo', rpm='bar', generic='baz')], ['bar'])
        t([dict(deb='foo', generic='baz')], ['baz'])
        t([dict(deb='foo')], [])
        t([dict(rpm='foo', caldera='bar', fedora='baz')], ['bar'])

        with self.assertRaises(AssertionError):
            rp.format_relation(
                    PackageRelation('libopenal.so.1 | bundled-openal'))

    def tearDown(self):
        pass

if __name__ == '__main__':
    unittest.main(verbosity=2)
