#!/usr/bin/python3
# vim:set fenc=utf-8:
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

import logging
import os
import shutil
import subprocess

from .. import (GameData, NoPackagesPossible)
from ..util import (mkdir_p, which)

logger = logging.getLogger('game-data-packager.games.lgeneral')

class LGeneralGameData(GameData):
    def add_parser(self, parsers, base_parser):
        parser = super(LGeneralGameData, self).add_parser(parsers, base_parser)
        parser.add_argument('-f', action='append', dest='paths',
                metavar='pg-data.tar.gz', help='Path to pg-data.tar.gz')
        parser.add_argument('-w', dest='download', action='store_true',
                help='Download pg-data.tar.gz (done automatically ' +
                    'if necessary)')
        return parser

    def prepare_packages(self, packages, build_demos=False):
        # don't bother even trying if it isn't going to work
        if which('lgc-pg') is None:
            logger.error('The "lgc-pg" tool is required for this package.')
            raise NoPackagesPossible()

        ready = super(LGeneralGameData, self).prepare_packages(packages,
                build_demos=build_demos)

        # would have raised an exception if not
        assert self.packages['lgeneral-data-nonfree'] in ready
        return ready

    def fill_dest_dir(self, package, destdir):
        assert package.name == 'lgeneral-data-nonfree'
        if not super(LGeneralGameData, self).fill_dest_dir(package, destdir):
            return False

        installdir = os.path.join(destdir, 'usr/share/games/lgeneral')
        unpackdir = os.path.join(self.get_workdir(), 'tmp', 'pg-data.tar.gz.d')

        for d in ('gfx/flags', 'gfx/terrain', 'gfx/units', 'maps/pg',
                'nations', 'scenarios/pg', 'sounds/pg', 'units'):
            mkdir_p(os.path.join(installdir, d))

        shutil.unpack_archive(
                os.path.join(installdir, 'pg-data.tar.gz'),
                unpackdir,
                'gztar')

        subprocess.check_call(['lgc-pg', '-s', unpackdir + '/pg-data/',
            '-d', installdir + '/'])

        return True

GAME_DATA_SUBCLASS = LGeneralGameData
