#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2015 Simon McVittie <smcv@debian.org>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License version 2
# as published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
#
# You can find the GPL license text on a Debian system under
# /usr/share/common-licenses/GPL-2.

import glob
import logging
import os
import subprocess
import tarfile

from .. import (GameData)
from ..build import (PackagingTask)

logger = logging.getLogger(__name__)

class Quake2GameData(GameData):
    def construct_task(self, **kwargs):
        return Quake2Task(self, **kwargs)

class Quake2Task(PackagingTask):
    def fill_dest_dir(self, package, destdir):
        if not super(Quake2Task, self).fill_dest_dir(package, destdir):
            return False

        if package.name not in ('quake2-reckoning-data',
                                'quake2-groundzero-data'):
            return True

        subdir = {
            'quake2-groundzero-data': 'rogue',
            'quake2-reckoning-data': 'xatrix',
        }[package.name]

        installdir = os.path.join(destdir, 'usr', 'share', 'games', 'quake2')
        unpackdir = os.path.join(self.get_workdir(), 'tmp',
                package.name + '.build.d')

        tars = list(glob.glob(os.path.join(installdir, '*.tar.xz')))
        assert len(tars) == 1, tars
        expect_dir = os.path.basename(tars[0])
        expect_dir = expect_dir[:len(expect_dir) - 7]

        with tarfile.open(tars[0], mode='r:xz') as tar:
            tar.extractall(unpackdir)

        subprocess.check_call(['make', '-C',
            os.path.join(unpackdir, expect_dir), '-s', '-j5'])
        subprocess.check_call(['install', '-s', '-m644',
            os.path.join(unpackdir, expect_dir, 'release', 'game.so'),
            os.path.join(installdir, subdir, 'game.so')])

        return True

GAME_DATA_SUBCLASS = Quake2GameData
