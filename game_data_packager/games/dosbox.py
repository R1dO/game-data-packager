#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2016 Alexandre Detiste <alexandre@detiste.be>
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

# this is just a proof-of-concept,
# please don't start packaging 10.000 DOS games

import configparser
import logging
import os

from .. import GameData
from ..build import (PackagingTask)
from ..util import (mkdir_p)

logger = logging.getLogger(__name__)

class DosboxGameData(GameData):
    """Special subclass of GameData for DOS games.

    These games will need the "dosgame" runtime
    provided by src:game-data-packager.
    """

    def __init__(self, shortname, data):
        super(DosboxGameData, self).__init__(shortname, data)
        self.binary_executables = 'all'

        for p in self.packages.values():
            p.install_to = '$assets/dosbox/' + p.name[:len(p.name)-5]
            p.depends = 'dosgame'
            p.main_exe = None
            if 'main_exe' in self.data['packages'][p.name]:
                p.main_exe = self.data['packages'][p.name]['main_exe']
            else:
                for wanted in p.install:
                    filename, ext = os.path.splitext(wanted)
                    if (filename not in ('config', 'install', 'setup')
                        and ext in ('.com','.exe')):
                        assert p.main_exe is None
                        p.main_exe = filename
            assert p.main_exe

    def construct_task(self, **kwargs):
        return DosboxTask(self, **kwargs)

class DosboxTask(PackagingTask):
    def fill_extra_files(self, package, destdir):
        super(DosboxTask, self).fill_extra_files(package, destdir)

        pgm = package.name[:len(package.name)-5]
        mkdir_p(os.path.join(destdir, self.packaging.BINDIR))
        os.symlink('dosgame',
                   os.path.join(destdir, self.packaging.BINDIR, pgm))

        appdir = os.path.join(destdir, 'usr/share/applications')
        mkdir_p(appdir)

        desktop = configparser.RawConfigParser()
        desktop.optionxform = lambda option: option
        desktop['Desktop Entry'] = {}
        entry = desktop['Desktop Entry']
        entry['Name'] = package.longname or self.game.longname
        entry['Icon'] = 'dosbox'
        entry['GenericName'] = self.game.genre + ' game'
        entry['Exec'] = pgm
        entry['Terminal'] = 'false'
        entry['Type'] = 'Application'
        entry['Categories'] = 'Game;'

        with open(os.path.join(appdir, '%s.desktop' % package.name),
                  'w', encoding='utf-8') as output:
             desktop.write(output, space_around_delimiters=False)


        # minimal information needed by the runtime
        dosgame = configparser.RawConfigParser()
        dosgame.optionxform = lambda option: option
        dosgame['Dos Game'] = {}
        entry = dosgame['Dos Game']
        entry['Dir'] = package.main_exe
        entry['Exe'] = package.main_exe

        install_to = self.packaging.substitute(package.install_to,
                       package.name).lstrip('/')
        with open(os.path.join(destdir, install_to, 'dosgame.inf'),
                  'w', encoding='utf-8') as output:
             dosgame.write(output, space_around_delimiters=False)

GAME_DATA_SUBCLASS = DosboxGameData
