#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2016 Simon McVittie <smcv@debian.org>
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

from .. import (GameData)
from ..build import (PackagingTask)
from ..util import (TemporaryUmask, mkdir_p)

logger = logging.getLogger('game-data-packager.games.unreal')

class UnrealTask(PackagingTask):
    def fill_extra_files(self, package, destdir):
        super(UnrealTask, self).fill_extra_files(package, destdir)

        if package.name == 'unreal-data':
            with TemporaryUmask(0o022):
                self.__convert_logo(destdir, package, 'skaarj_logo.jpg')

        if package.name == 'ut99-data':
            with TemporaryUmask(0o022):
                self.__convert_logo(destdir, package, 'ut99.gif')

        if package.name in ('unreal-gold', 'unreal-classic', 'ut99'):
            with TemporaryUmask(0o022):
                self.__add_manifest(package, destdir)

    def __add_manifest(self, package, destdir):
        # A real Manifest.ini is much larger than this, but this is
        # enough to identify the version.

        install_to = self.packaging.substitute(package.install_to,
                package.name).lstrip('/')
        mkdir_p(os.path.join(destdir, install_to, 'System'))

        with open(os.path.join(destdir, install_to, 'System',
                'Manifest.ini'), 'w') as writer:
            if package.name == 'unreal-gold':
                groups = (('UnrealGold', package.name, package.version),
                        ('Unreal Gold', package.name, package.version))
                sample_file = 'System\\UnrealLinux.ini'
            elif package.name == 'ut99':
                groups = (('UnrealTournament', package.name, package.version),
                        ('UTBonusPack', 'Unreal Tournament Bonus Pack', '100'),
                        ('DEMutators', 'DEMutators', '101'),
                        ('UTInoxxPack', 'Unreal Tournament Inoxx Pack', '100'),
                        ('UTBonusPack4', 'Unreal Tournament Bonus Pack 4',
                            '100'))
                sample_file = 'System\\UnrealTournament.ini'
            else:
                groups = (('Unreal', package.name, package.version))
                sample_file = 'System\\UnrealLinux.ini'

            lines = ['[Setup]', 'MasterProduct=' + groups[0][0]]

            for g in groups:
                lines.append('Group=' + g[0])

            for g in groups:
                lines.append('')
                lines.append('[' + g[0] + ']')
                lines.append('Caption=' + g[1])
                lines.append('Version=' + g[2])
                lines.append('File=' + sample_file)

            lines += ['', '[RefCounts]',
                    'File:%s=%d' % (sample_file, len(groups)), '']

            for line in lines:
                writer.write(line + '\r\n')

    def __convert_logo(self, destdir, package, logo_name):
        source_logo = os.path.join(destdir,
                self.packaging.substitute(package.install_to, package.name),
                logo_name)

        try:
            import gi
            gi.require_version('GdkPixbuf', '2.0')
            from gi.repository import GdkPixbuf
        except:
            logger.warning('Unable to load GdkPixbuf bindings. %s icon '
                    'will not be resized or converted' % self.game.longname)
            return

        mkdir_p(os.path.join(destdir, 'usr', 'share', 'icons',
                'hicolor', '48x48', 'apps'))
        mkdir_p(os.path.join(destdir, 'usr', 'share', 'icons',
                'hicolor', '256x256', 'apps'))

        pixbuf = GdkPixbuf.Pixbuf.new_from_file(source_logo)
        pixbuf.savev(os.path.join(destdir, 'usr', 'share', 'icons',
                    'hicolor', '256x256', 'apps', self.game.shortname + '.png'),
                'png', [], [])

        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(source_logo, 48, 48)
        pixbuf.savev(os.path.join(destdir, 'usr', 'share', 'icons',
                    'hicolor', '48x48', 'apps', self.game.shortname + '.png'),
                'png', [], [])

class UnrealGameData(GameData):
    def construct_task(self, **kwargs):
        return UnrealTask(self, **kwargs)

GAME_DATA_SUBCLASS = UnrealGameData
