#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2015 Simon McVittie <smcv@debian.org>
#             2015 Alexandre Detiste <alexandre@detiste.be>
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
from ..paths import DATADIR
from ..util import (TemporaryUmask, copy_with_substitutions, mkdir_p)

logger = logging.getLogger('game-data-packager.games.residualvm-common')

class ResidualvmGameData(GameData):
    def __init__(self, shortname, yaml_data, workdir=None):
        super(ResidualvmGameData, self).__init__(shortname, yaml_data,
                workdir=workdir)

        self.gameid = self.yaml['gameid']

    def fill_extra_files(self, package, destdir):
        super(ResidualvmGameData, self).fill_extra_files(package, destdir)

        with TemporaryUmask(0o022):
            appdir = os.path.join(destdir, 'usr/share/applications')
            mkdir_p(appdir)
            from_ = os.path.join(DATADIR, 'residualvm-common.desktop.in')
            copy_with_substitutions(open(from_,
                    encoding='utf-8'),
                        open(os.path.join(appdir, '%s.desktop' % package.name),
                            'w', encoding='utf-8'),
                        GAME=self.gameid,
                        PATH=package.install_to,
                        LONG=(package.longname or self.longname))

GAME_DATA_SUBCLASS = ResidualvmGameData
