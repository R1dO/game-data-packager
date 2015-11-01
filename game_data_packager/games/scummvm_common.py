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
import subprocess

from .. import GameData
from ..build import (PackagingTask)
from ..paths import DATADIR
from ..util import mkdir_p
from ..version import (FORMAT, BINDIR)

logger = logging.getLogger('game-data-packager.games.scummvm-common')

def install_data(from_, to):
    subprocess.check_call(['cp', '--reflink=auto', from_, to])

class ScummvmGameData(GameData):
    def __init__(self, shortname, data):
        super(ScummvmGameData, self).__init__(shortname, data)

        self.wikibase = 'http://wiki.scummvm.org/index.php/'
        assert self.wiki

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

    def construct_task(self, **kwargs):
        return ScummvmTask(self, **kwargs)

class ScummvmTask(PackagingTask):
    def iter_extra_paths(self, packages):
        super(ScummvmTask, self).iter_extra_paths(packages)

        gameids = set()
        for p in packages:
            gameid = p.gameid or self.game.gameid
            if gameid == 'agi-fanmade':
                continue
            gameids.add(gameid.split('-')[0])
        if not gameids:
            return

        # http://wiki.scummvm.org/index.php/User_Manual/Configuring_ScummVM
        rcfile = os.path.expanduser('~/.scummvmrc')
        if not os.path.isfile(rcfile):
            return

        config = configparser.ConfigParser(strict=False)
        config.read(rcfile, encoding='utf-8')
        for section in config.sections():
            for gameid in gameids:
                if section.split('-')[0] == gameid:
                    if 'path' not in config[section]:
                        # invalid .scummvmrc
                        continue
                    path = config[section]['path']
                    if os.path.isdir(path):
                        yield path

    def fill_extra_files(self, package, destdir):
        super(ScummvmTask, self).fill_extra_files(package, destdir)
        if package.type == 'expansion':
            return

        icon = package.name
        for from_ in (self.locate_steam_icon(package),
                      os.path.join(DATADIR, package.name + '.png'),
                      os.path.join(DATADIR, self.game.shortname + '.png'),
                      os.path.join('/usr/share/pixmaps', icon + '.png'),
                      os.path.join(DATADIR,
                          self.game.shortname.strip('1234567890') + '.png')):
            if from_ and os.path.exists(from_):
                pixdir = os.path.join(destdir, 'usr/share/pixmaps')
                mkdir_p(pixdir)
                install_data(from_, os.path.join(pixdir, '%s.png' % icon))
                break
        else:
            icon = 'scummvm'

        from_ = os.path.splitext(from_)[0] + '.svgz'
        if os.path.exists(from_):
            svgdir = os.path.join(destdir, 'usr/share/icons/hicolor/scalable/apps')
            mkdir_p(svgdir)
            install_data(from_, os.path.join(svgdir, '%s.svgz' % icon))

        appdir = os.path.join(destdir, 'usr/share/applications')
        mkdir_p(appdir)

        desktop = configparser.RawConfigParser()
        desktop.optionxform = lambda option: option
        desktop['Desktop Entry'] = {}
        entry = desktop['Desktop Entry']
        entry['Name'] = package.longname or self.game.longname
        entry['GenericName'] = self.game.genre + ' Game'
        entry['TryExec'] = 'scummvm'
        entry['Icon'] = icon
        entry['Terminal'] = 'false'
        entry['Type'] = 'Application'
        entry['Categories'] = 'Game;%sGame' % self.game.genre.replace(' ','')
        gameid = package.gameid or self.game.gameid
        if len(package.langs) == 1:
            entry['Exec'] = 'scummvm -p /%s %s' % (package.install_to, gameid)
            if FORMAT == 'deb':
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
            bindir = os.path.join(destdir, BINDIR)
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
                    f.write('[ "$lang" = "%s" ] && echo $lang && break\n' % lang)
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
