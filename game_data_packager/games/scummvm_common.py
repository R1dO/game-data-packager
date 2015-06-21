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
from ..util import mkdir_p

logger = logging.getLogger('game-data-packager.games.scummvm-common')

class ScummvmGameData(GameData):
    def __init__(self, shortname, data, workdir=None):
        super(ScummvmGameData, self).__init__(shortname, data,
                workdir=workdir)

        if 'gameid' in self.data:
            self.gameid = self.data['gameid']
            assert self.gameid != shortname, 'extraneous gameid for ' + shortname
            self.aliases.add(self.gameid)
        else:
            self.gameid = shortname

        if self.engine is None:
            self.engine = 'scummvm'
        if self.genre is None:
            self.genre = 'Adventure'

    def _populate_package(self, package, d):
        super(ScummvmGameData, self)._populate_package(package, d)
        package.gameid = d.get('gameid')
        package.langs = d.get('langs',['en'])
        assert type(package.langs) is list

    def fill_extra_files(self, package, destdir):
        super(ScummvmGameData, self).fill_extra_files(package, destdir)
        if package.type == 'expansion':
            return

        appdir = os.path.join(destdir, 'usr/share/applications')
        mkdir_p(appdir)

        desktop = configparser.RawConfigParser()
        desktop.optionxform = lambda option: option
        desktop['Desktop Entry'] = {}
        entry = desktop['Desktop Entry']
        entry['Name'] = package.longname or self.longname
        entry['GenericName'] = self.genre + ' game'
        entry['TryExec'] = 'scummvm'
        entry['Icon'] = 'scummvm'
        entry['Terminal'] = 'false'
        entry['Categories'] = 'game'
        gameid = package.gameid or self.gameid
        if package.langs == ['en']:
            entry['Exec'] = 'scummvm -p /%s %s' % (package.install_to, gameid)
            lintiandir = os.path.join(destdir, 'usr/share/lintian/overrides')
            mkdir_p(lintiandir)
            with open(os.path.join(lintiandir, package.name),
                      'a', encoding='utf-8') as o:
                 o.write('%s: desktop-command-not-in-package '
                         'usr/share/applications/%s.desktop scummvm\n'
                         % (package.name, package.name))
        else:
            pgm = package.name[0:len(package.name)-len('-data')]
            entry['Exec'] = pgm
            bindir = os.path.join(destdir, 'usr/games')
            mkdir_p(bindir)
            path = os.path.join(bindir, pgm)
            if 'en' not in package.langs:
                package.langs.append('en')
            with open(path, 'w') as f:
                f.write('#!/bin/sh\n')
                f.write('GAME_LANG=$(\n')
                f.write("echo $LANGUAGE $LANG en | tr ': ' '\\n' | cut -c1-2 | while read lang\n")
                f.write('do\n')
                for lang in package.langs:
                    f.write('[ "$lang" = "%s" ] && echo $lang && return\n' % lang)
                f.write('done\n')
                f.write(')\n')
                f.write('if [ "$GAME_LANG" = "en" ]; then\n')
                f.write('  scummvm -p /%s %s\n' % (package.install_to, gameid))
                f.write('else\n')
                f.write('  scummvm -q $GAME_LANG -p /%s %s\n' % (package.install_to, gameid))
                f.write('fi\n')
            os.chmod(path, 0o755)

        with open(os.path.join(appdir, '%s.desktop' % package.name),
                  'w', encoding='utf-8') as output:
             desktop.write(output, space_around_delimiters=False)

GAME_DATA_SUBCLASS = ScummvmGameData
