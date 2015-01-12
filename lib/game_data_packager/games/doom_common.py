#!/usr/bin/python3
# vim:set fenc=utf-8:
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
import subprocess

from .. import GameData, GameDataPackage
from ..paths import DATADIR
from ..util import TemporaryUmask, mkdir_p

logger = logging.getLogger('game-data-packager.games.doom-common')

def install_data(from_, to):
    subprocess.check_call(['cp', '--reflink=auto', from_, to])

def subst(from_, to, **kwargs):
    for line in from_:
        for k, v in kwargs.items():
            line = line.replace(k, v)
        to.write(line)

class WadPackage(GameDataPackage):
    @property
    def main_wad(self):
        for f in self.install:
            if f == 'voices.wad':
                # ignore Strife voices
                continue

            if f.endswith('.wad'):
                return f
        else:
            raise AssertionError('Wad packages must install one .wad file')

class DoomGameData(GameData):
    def __init__(self, shortname, yaml_data, workdir=None):
        super(DoomGameData, self).__init__(shortname, yaml_data,
                workdir=workdir)

        self.engine = self.yaml.get('doom_engine', 'doom')

        for package in self.packages.values():
            assert package.main_wad is not None

    def construct_package(self, binary):
        return WadPackage(binary)

    def get_control_template(self, package):
        for name in (package.name, self.shortname, 'doom-common'):
            path = os.path.join(DATADIR, '%s.control.in' % name)
            if os.path.exists(path):
                return path
        else:
            raise AssertionError('doom-common.control.in should exist')

    def modify_control_template(self, control, package, destdir):
        super(DoomGameData, self).modify_control_template(control, package,
                destdir)

        wad_base = os.path.splitext(package.main_wad)[0]

        desc = control['Description']
        desc = desc.replace('ENGINE', self.engine)
        desc = desc.replace('GAME', wad_base)
        desc = desc.replace('LONG', (package.longname or self.longname))
        control['Description'] = desc

    def fill_docs(self, package, docdir):
        main_wad = package.main_wad

        subst(
                open(os.path.join(DATADIR, 'doom-common.README.Debian.in')),
                open(os.path.join(docdir, 'README.Debian'), 'w'),
                PACKAGE=package.name,
                GAME=(package.longname or self.longname))
        subst(
                open(os.path.join(DATADIR, 'doom-common.copyright.in')),
                open(os.path.join(docdir, 'copyright'), 'w'),
                PACKAGE=package.name,
                IWAD=main_wad)

    def fill_extra_files(self, package, destdir):
        super(DoomGameData, self).fill_extra_files(package, destdir)

        main_wad = package.main_wad
        wad_base = os.path.splitext(main_wad)[0]

        with TemporaryUmask(0o022):
            pixdir = os.path.join(destdir, 'usr/share/pixmaps')
            mkdir_p(pixdir)
            # FIXME: would be nice if non-Doom games could replace this
            # Cacodemon with something appropriate
            install_data(os.path.join(DATADIR, 'doom2.xpm'),
                    os.path.join(pixdir, '%s.xpm' % wad_base))

            docdir = os.path.join(destdir, 'usr/share/doc/%s' % package.name)
            mkdir_p(docdir)

            appdir = os.path.join(destdir, 'usr/share/applications')
            mkdir_p(appdir)
            for basename in (package.name, 'doom-common'):
                from_ = os.path.join(DATADIR, basename + '.desktop.in')
                if os.path.exists(from_):
                    subst(open(from_),
                            open(os.path.join(appdir, '%s.desktop' % package.name),
                                'w'),
                            GAME=wad_base,
                            LONG=(package.longname or self.longname),
                            ENGINE=self.engine)
                    break
            else:
                raise AssertionError('doom-common.desktop.in should have existed')

            debdir = os.path.join(destdir, 'DEBIAN')
            mkdir_p(debdir)
            subst(
                    open(os.path.join(DATADIR, 'doom-common.preinst.in')),
                    open(os.path.join(debdir, 'preinst'), 'w'),
                    IWAD=main_wad)
            os.chmod(os.path.join(debdir, 'preinst'), 0o755)

GAME_DATA_SUBCLASS = DoomGameData
