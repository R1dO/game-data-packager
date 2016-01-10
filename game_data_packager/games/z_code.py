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
import re

from .. import GameData
from ..build import (PackagingTask)
from ..util import (TemporaryUmask,
                    which,
                    mkdir_p)

logger = logging.getLogger('game-data-packager.games.z_code')

class ZCodeGameData(GameData):
    def __init__(self, shortname, data):
        super(ZCodeGameData, self).__init__(shortname, data)
        one_z_file = False
        for package in self.packages.values():
            for install in package.install:
                if re.match('^.z[12345678]$', os.path.splitext(install)[1]):
                    one_z_file = not one_z_file
        assert one_z_file

        if self.engine is None:
            self.engine = 'gargoyle-free | frotz'
        if self.genre is None:
            self.genre = 'Adventure'

    def construct_task(self, **kwargs):
        return ZCodeTask(self, **kwargs)

class ZCodeTask(PackagingTask):
    def fill_extra_files(self, package, destdir):
        super(ZCodeTask, self).fill_extra_files(package, destdir)

        install_to = self.packaging.substitute(package.install_to,
                package.name).lstrip('/')

        with TemporaryUmask(0o022):
            appdir = os.path.join(destdir, 'usr/share/applications')
            mkdir_p(appdir)
            desktop = configparser.RawConfigParser()
            desktop.optionxform = lambda option: option
            desktop['Desktop Entry'] = {}
            entry = desktop['Desktop Entry']
            entry['Type'] = 'Application'
            entry['Categories'] = 'Game;'
            entry['GenericName'] = self.game.genre + ' Game'
            entry['Name'] = package.longname or self.game.longname
            engine = 'gargoyle-free'
            entry['Terminal'] = 'false'
            if not self.packaging.is_installed('gargoyle-free'):
                for try_engine in ('frotz', 'nfrotz', 'fizmo'):
                    if which(try_engine):
                        engine = try_engine
                        entry['Terminal'] = 'true'
                        break
            entry['TryExec'] = engine
            for wanted in package.install_files:
                if re.match('^.z[12345678]$', os.path.splitext(wanted.name)[1]):
                    arg = '/' + install_to + '/' + wanted.name
            entry['Exec'] = engine + ' ' + arg

            pixdir = os.path.join(destdir, 'usr/share/pixmaps')
            if os.path.exists(os.path.join(pixdir, '%s.png' % self.game.shortname)):
                entry['Icon'] = self.game.shortname
            else:
                entry['Icon'] = 'utilities-terminal'

            if package.aliases:
                entry['Keywords'] = ';'.join(package.aliases) + ';'

            with open(os.path.join(appdir, '%s.desktop' % package.name),
                      'w', encoding='utf-8') as output:
                 desktop.write(output, space_around_delimiters=False)

            self.packaging.override_lintian(destdir, package.name,
                    'desktop-command-not-in-package',
                    'usr/share/applications/%s.desktop %s'
                     % (package.name, engine))

            if engine != 'gargoyle-free':
                engine = which(engine)
                bindir = os.path.join(destdir, self.packaging.BINDIR)
                mkdir_p(bindir)
                pgm = package.name[0:len(package.name)-len('-data')]
                path = os.path.join(bindir, pgm)
                with open(path, 'w') as f:
                     f.write('#!/bin/sh\n')
                     f.write('test -x %s && exec %s $@ %s\n' %
                             (engine, engine, arg))
                     f.write('echo "You need to install some engine '
                                   'like frotz to play this game"\n')
                os.chmod(path, 0o755)

GAME_DATA_SUBCLASS = ZCodeGameData
