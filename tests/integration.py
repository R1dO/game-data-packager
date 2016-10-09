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

import os
import subprocess
import unittest
from tempfile import (TemporaryDirectory)

try:
    from gi.repository import GLib
except:
    GLib = None

class IntegrationTestCase(unittest.TestCase):
    '''
    Test some cherry picked games that:
    - are freely downloadable (either demo or full version)
    - test various codepaths:
      - alternatives
      - archive recursion (zip in zip)
      - lha
      - id-shr-extract
    - doom_commo.py plugin
    - are not too big
    '''

    def setUp(self):
        if 'GDP_MIRROR' in os.environ:
            self.downloads = None
        else:
            if GLib is None:
                self.skipTest('GLib g-i bindings not available')

            self.downloads = GLib.get_user_special_dir(
                    GLib.UserDirectory.DIRECTORY_DOWNLOAD)
            if (self.downloads is None or
                    not os.path.isdir(self.downloads)):
                self.skipTest('XDG download directory "{}" not found'.format(
                    self.downloads))

            os.environ['GDP_MIRROR'] = 'file://' + self.downloads

    def _test_one(self, game, files):
        if 'GDP_MIRROR' not in os.environ:
            for filename in files:
                if not os.path.exists(os.path.join(self.downloads, filename)):
                    self.skipTest('download {} into {}'.format(filename,
                        self.downloads))

        with TemporaryDirectory(prefix='gdptest.') as tmp:
            if 'GDP_UNINSTALLED' in os.environ:
                argv = ['./run']
            else:
                argv = ['game-data-packager']

            argv = argv + [
                '-d', tmp,
                '--no-compress',
                game,
                '--no-search',
            ]
            subprocess.check_call(argv)
            if 'GDP_TEST_ALL_FORMATS' in os.environ:
                for f in 'arch deb rpm'.split():
                    subprocess.check_call(argv + ['--target-format', f])

    def test_heretic(self):
        self._test_one('heretic', 'htic_v12.zip'.split())

    def test_rott(self):
        self._test_one('rott', '1rott13.zip'.split())

    def test_spear(self):
        self._test_one('spear-of-destiny', 'sodemo.zip destiny.zip'.split())

    def test_wolf3d(self):
        self._test_one('wolf3d', '1wolf14.zip'.split())

    def tearDown(self):
        pass

if __name__ == '__main__':
    unittest.main(verbosity=2)
