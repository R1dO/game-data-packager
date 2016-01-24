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

logger = logging.getLogger(__name__)

class UnrealTask(PackagingTask):
    def fill_extra_files(self, package, destdir):
        super(UnrealTask, self).fill_extra_files(package, destdir)

        if package.name == 'unreal-data':
            with TemporaryUmask(0o022):
                self.__convert_logo(destdir, package, 'skaarj_logo.jpg')

        if package.name in ('unreal-gold', 'unreal-classic'):
            with TemporaryUmask(0o022):
                self.__add_manifest(package, destdir)

                self.packaging.override_lintian(destdir, package.name,
                        'binary-has-unneeded-section',
                        'usr/lib/unreal*/System/* *')
                self.packaging.override_lintian(destdir, package.name,
                        'binary-or-shlib-defines-rpath',
                        'usr/lib/unreal*/System/* .')
                self.packaging.override_lintian(destdir, package.name,
                        'embedded-library',
                        'usr/lib/unreal*/System/*.bin: zlib')
                self.packaging.override_lintian(destdir, package.name,
                        'hardening-no-fortify-functions',
                        'usr/lib/unreal*/System/*')
                self.packaging.override_lintian(destdir, package.name,
                        'spelling-error-in-binary',
                        'usr/lib/unreal*/System/* * *')
                self.packaging.override_lintian(destdir, package.name,
                        'shlib-with-non-pic-code',
                        'usr/lib/unreal*/System/*.so')

        if package.name == 'unreal-libmikmod2':
            with TemporaryUmask(0o022):
                self.packaging.override_lintian(destdir, package.name,
                        'embedded-library',
                        'usr/lib/unreal/libmikmod.so.2.0.4: libmikmod')

        if package.name == 'unreal-libfmod':
            with TemporaryUmask(0o022):
                self.packaging.override_lintian(destdir, package.name,
                        'hardening-no-relro',
                        'usr/lib/unreal/libfmod-3.75.so')
                self.packaging.override_lintian(destdir, package.name,
                        'binary-has-unneeded-section',
                        'usr/lib/unreal/libfmod-3.75.so .comment')
                self.packaging.override_lintian(destdir, package.name,
                        'hardening-no-fortify-functions',
                        'usr/lib/unreal/libfmod-3.75.so')

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
            else:
                groups = (('Unreal', package.name, package.version),)
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
