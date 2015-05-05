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

import configparser
import logging
import os

from .. import GameData
from ..paths import DATADIR
from ..util import (TemporaryUmask, PACKAGE_CACHE, mkdir_p)

logger = logging.getLogger('game-data-packager.games.z_code')

class ZCodeGameData(GameData):
    def __init__(self, shortname, data, workdir=None):
        super(ZCodeGameData, self).__init__(shortname, data,
                workdir=workdir)

        if self.engine is None:
            self.engine = 'gargoyle-free | frotz'
        if self.genre is None:
            self.genre = 'Adventure'

    def fill_extra_files(self, package, destdir):
        super(ZCodeGameData, self).fill_extra_files(package, destdir)

        with TemporaryUmask(0o022):
            appdir = os.path.join(destdir, 'usr/share/applications')
            mkdir_p(appdir)
            from_ = os.path.join(DATADIR, 'z_code.desktop.in')
            desktop = configparser.RawConfigParser()
            desktop.optionxform = lambda option: option
            desktop.read(from_, encoding='utf-8')

            entry = desktop['Desktop Entry']
            entry['Name'] = package.longname or self.longname
            if (PACKAGE_CACHE.is_installed('frotz') and
                    not PACKAGE_CACHE.is_installed('gargoyle-free')):
                engine = 'frotz'
                entry['Terminal'] = 'true'
            else:
                engine = 'gargoyle-free'
                entry['Terminal'] = 'false'
            entry['TryExec'] = engine
            arg = '/' + package.install_to + '/' + list(package.install)[0]
            entry['Exec'] = engine + ' ' + arg

            pixdir = os.path.join(destdir, 'usr/share/pixmaps')
            if os.path.exists(os.path.join(pixdir, '%s.png' % self.shortname)):
                entry['Icon'] = self.shortname

            if package.aliases:
                entry['Keywords'] = ';'.join(package.aliases)

            with open(os.path.join(appdir, '%s.desktop' % package.name),
                      'w', encoding='utf-8') as output:
                 desktop.write(output, space_around_delimiters=False)

            lintiandir = os.path.join(destdir, 'usr/share/lintian/overrides')
            mkdir_p(lintiandir)
            with open(os.path.join(lintiandir, package.name),
                      'a', encoding='utf-8') as o:
                 o.write('%s: desktop-command-not-in-package '
                         'usr/share/applications/%s.desktop %s\n'
                         % (package.name, package.name, engine))

            if engine == 'frotz':
                bindir = os.path.join(destdir, 'usr/games')
                mkdir_p(bindir)
                pgm = package.name[0:len(package.name)-len('-data')]
                path = os.path.join(bindir, pgm)
                with open(path, 'w') as f:
                     f.write('#!/bin/sh\n')
                     f.write('test -x /usr/games/frotz && exec frotz $@ %s\n' % arg)
                     f.write('echo "You need to install some engine '
                                   'like frotz to play this game"\n')
                os.chmod(path, 0o755)

GAME_DATA_SUBCLASS = ZCodeGameData
