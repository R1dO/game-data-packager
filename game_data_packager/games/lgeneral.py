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

import logging
import os
import shutil
import subprocess

from .. import (GameData)
from ..build import (PackagingTask, NoPackagesPossible)
from ..util import (mkdir_p, which)

logger = logging.getLogger(__name__)

class LGeneralGameData(GameData):
    def add_parser(self, parsers, base_parser):
        parser = super(LGeneralGameData, self).add_parser(parsers, base_parser)
        parser.add_argument('-f', dest='download', action='store_false',
                help='Require pg-data.tar.gz on the command line')
        parser.add_argument('-w', dest='download', action='store_true',
                help='Download pg-data.tar.gz (done automatically ' +
                    'if necessary)')
        return parser

    def construct_task(self, **kwargs):
        return LGeneralTask(self, **kwargs)

class LGeneralTask(PackagingTask):
    def prepare_packages(self, packages, build_demos=False, download=True,
                    search=True, log_immediately=True):
        # don't bother even trying if it isn't going to work
        if which('lgc-pg') is None:
            logger.error('The "lgc-pg" tool is required for this package.')
            raise NoPackagesPossible()

        if 'DISPLAY' not in os.environ and 'WAYLAND_DISPLAY' not in os.environ:
            logger.error('The "lgc-pg" tool requires '
                         'to run in some graphical environment.')
            raise NoPackagesPossible()

        ready = super(LGeneralTask, self).prepare_packages(packages,
                build_demos=build_demos, download=download)

        # would have raised an exception if not
        assert self.game.packages['lgeneral-data-nonfree'] in ready
        return ready

    def fill_dest_dir(self, package, destdir):
        assert package.name == 'lgeneral-data-nonfree'
        if not super(LGeneralTask, self).fill_dest_dir(package, destdir):
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
