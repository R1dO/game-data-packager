#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2015-2016 Alexandre Detiste <alexandre@detiste.be>
#             2016 Simon McVittie <smcv@debian.org>
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
from ..data import (Package)
from ..paths import DATADIR
from ..util import (mkdir_p)

logger = logging.getLogger(__name__)

def install_data(from_, to):
    subprocess.check_call(['cp', '--reflink=auto', from_, to])

class EcwolfGameData(GameData):
    """Special subclass of GameData for games playable with ecwolf:
    - Blake Stone I&II
    - Super 3D Noah's Ark
    the .desktop file provided by the engine's package would
    default to Wolfenstein3D
    """

    def __init__(self, shortname, data):
        super(EcwolfGameData, self).__init__(shortname, data)
        if self.engine is None:
            self.engine = 'ecwolf'
        if self.genre is None:
            self.genre = 'First-person shooter'

    def construct_package(self, binary, data):
        return EcwolfPackage(binary, data)

    def construct_task(self, **kwargs):
        return EcwolfTask(self, **kwargs)

class EcwolfPackage(Package):
    def __init__(self, binary, data):
        super(EcwolfPackage, self).__init__(binary, data)

        if 'quirks' in data:
            self.quirks = ' ' + data['quirks']
        else:
            self.quirks = ''

class EcwolfTask(PackagingTask):
    def fill_extra_files(self, package, destdir):
        super(EcwolfTask, self).fill_extra_files(package, destdir)

        pixdir = os.path.join(destdir, 'usr/share/pixmaps')
        mkdir_p(pixdir)

        to_ = os.path.join(pixdir, '%s.png' % package.name)
        if not os.path.isfile(to_):
            for from_ in (self.locate_steam_icon(package),
                          os.path.join(DATADIR, package.name + '.png'),
                          os.path.join(DATADIR, self.game.shortname + '.png'),
                          os.path.join('/usr/share/pixmaps', package.name + '.png'),
                          os.path.join(DATADIR, 'wolf-common.png')):
                if from_ and os.path.exists(from_):
                    install_data(from_, to_)
                    break
            else:
                raise AssertionError('wolf-common.png should have existed')

            from_ = os.path.splitext(from_)[0] + '.svgz'
            if os.path.exists(from_):
                svgdir = os.path.join(destdir, 'usr/share/icons/hicolor/scalable/apps')
                mkdir_p(svgdir)
                install_data(from_, os.path.join(svgdir, '%s.svgz' % package.name))

        install_to = self.packaging.substitute(package.install_to,
                package.name)

        desktop = configparser.RawConfigParser()
        desktop.optionxform = lambda option: option
        desktop['Desktop Entry'] = {}
        entry = desktop['Desktop Entry']
        entry['Name'] = package.longname or self.game.longname
        entry['GenericName'] = self.game.genre + ' game'
        entry['TryExec'] = 'ecwolf'
        entry['Exec'] = 'ecwolf' + package.quirks
        entry['Path'] = os.path.join('/', install_to)
        entry['Icon'] = package.name
        entry['Terminal'] = 'false'
        entry['Type'] = 'Application'
        entry['Categories'] = 'Game;'

        appdir = os.path.join(destdir, 'usr/share/applications')
        mkdir_p(appdir)
        with open(os.path.join(appdir, '%s.desktop' % package.name),
                  'w', encoding='utf-8') as output:
             desktop.write(output, space_around_delimiters=False)

        self.packaging.override_lintian(destdir, package.name,
                'desktop-command-not-in-package',
                'usr/share/applications/%s.desktop ecwolf' % package.name)

GAME_DATA_SUBCLASS = EcwolfGameData
