#!/usr/bin/python3
# encoding=utf-8
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
from ..build import (PackagingTask)
from ..paths import DATADIR
from ..util import TemporaryUmask, mkdir_p

logger = logging.getLogger(__name__)

class QuakeTask(PackagingTask):
    """With hindsight, it would have been better to make the TryExec
    in quake point to a symlink to the quake executable, or something;
    but with a name like hipnotic-tryexec.sh it would seem silly for it
    not to be a shell script.
    """

    def get_control_template(self, package):
        for name in (package.name, 'quake-common'):
            path = os.path.join(DATADIR, '%s.control.in' % name)
            if os.path.exists(path):
                return path
        else:
            raise AssertionError('quake-common.control.in should exist')

    def modify_control_template(self, control, package, destdir):
        super(QuakeTask, self).modify_control_template(control, package,
                destdir)

        desc = control['Description']
        desc = desc.replace('LONG', (package.longname or self.game.longname))
        control['Description'] = desc

    def fill_extra_files(self, package, destdir):
        super(QuakeTask, self).fill_extra_files(package, destdir)

        for path in package.install:
            if path.startswith('hipnotic'):
                detector = 'hipnotic-tryexec.sh'
                break
            elif path.startswith('rogue'):
                detector = 'rogue-tryexec.sh'
                break
        else:
            return

        with TemporaryUmask(0o022):
            quakedir = os.path.join(destdir, 'usr/share/games/quake')
            mkdir_p(quakedir)
            path = os.path.join(quakedir, detector)
            with open(path, 'w') as f:
                f.write('#!/bin/sh\nexit 0\n')
            os.chmod(path, 0o755)

class QuakeGameData(GameData):
    def construct_task(self, **kwargs):
        return QuakeTask(self, **kwargs)

    def add_parser(self, parsers, base_parser):
        parser = super(QuakeGameData, self).add_parser(parsers, base_parser,
                conflict_handler='resolve')
        parser.add_argument('-m', '-d', dest='packages', action='append_const',
                const='quake-registered',
                help='Equivalent to --package=quake-registered')
        parser.add_argument('-s', dest='packages', action='append_const',
                const='quake-shareware',
                help='Equivalent to --package=quake-shareware')
        parser.add_argument('--mp1', '-mp1', dest='packages',
                action='append_const', const='quake-armagon',
                help='Equivalent to --package=quake-armagon')
        parser.add_argument('--mp2', '-mp2', dest='packages',
                action='append_const', const='quake-dissolution',
                help='Equivalent to --package=quake-dissolution')
        parser.add_argument('--music', dest='packages',
                action='append_const', const='quake-music',
                help='Equivalent to --package=quake-music')
        parser.add_argument('--mp1-music', dest='packages',
                action='append_const', const='quake-armagon-music',
                help='Equivalent to --package=quake-armagon-music')
        parser.add_argument('--mp2-music', dest='packages',
                action='append_const', const='quake-dissolution-music',
                help='Equivalent to --package=quake-dissolution-music')
        return parser

GAME_DATA_SUBCLASS = QuakeGameData
