#!/usr/bin/python3
# vim:set fenc=utf-8:
#
# Copyright © 2015 Simon McVittie <smcv@debian.org>
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

import logging
import os

from .. import GameData
from ..util import TemporaryUmask, mkdir_p

logger = logging.getLogger('game-data-packager.games.quake')

class QuakeGameData(GameData):
    """With hindsight, it would have been better to make the TryExec
    in quake point to a symlink to the quake executable, or something;
    but with a name like hipnotic-tryexec.sh it would seem silly for it
    not to be a shell script.
    """

    def fill_extra_files(self, package, destdir):
        super(QuakeGameData, self).fill_extra_files(package, destdir)

        for path in package.install:
            if path.startswith('hipnotic'):
                detector = 'hipnotic-tryexec.sh'
            elif path.startswith('rogue'):
                detector = 'rogue-tryexec.sh'
            else:
                return

        with TemporaryUmask(0o022):
            quakedir = os.path.join(destdir, 'usr/share/games/quake')
            mkdir_p(quakedir)
            path = os.path.join(quakedir, detector)
            with open(os.path.join(quakedir, detector), 'w') as f:
                f.write('#!/bin/sh\nexit 0\n')
            os.chmod(path, 0o755)

GAME_DATA_SUBCLASS = QuakeGameData
