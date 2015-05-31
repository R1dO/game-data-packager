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
from ..paths import DATADIR
from ..util import (copy_with_substitutions, mkdir_p)

logger = logging.getLogger('game-data-packager.games.doom-common')

def install_data(from_, to):
    subprocess.check_call(['cp', '--reflink=auto', from_, to])

class DoomGameData(GameData):
    """Special subclass of GameData for games descended from Doom.
    These games install their own icon and .desktop file, and share a
    considerable amount of other data.

    Please do not follow this example for newly-supported games other than
    the Doom family (Doom, Heretic, Hexen, Strife, Hacx, Chex Quest).

    For new games it is probably better to use game-data-packager to ship only
    the non-distributable files, and ship DFSG files (such as icons
    and .desktop files) somewhere else.

    One way is to have the engine package contain the wrapper scripts,
    .desktop files etc. (e.g. src:openjk, src:iortcw). This is the simplest
    thing if the engine is unlikely to be used for other games and alternative
    engine versions are unlikely to be packaged.

    Another approach is to have a package for the engine (like src:ioquake3)
    and a package for the user-visible game (like src:quake, containing
    wrapper scripts, .desktop files etc.). This is more flexible if the engine
    can be used for other user-visible games (e.g. OpenArena, Nexuiz Classic)
    or there could reasonably be multiple packaged engines (e.g. Quakespasm,
    Darkplaces).
    """

    def __init__(self, shortname, data, workdir=None):
        super(DoomGameData, self).__init__(shortname, data,
                workdir=workdir)
        if self.engine is None:
            self.engine = "chocolate-doom | doom-engine"
        if self.genre is None:
            self.genre = 'First-person shooter'

        package_map = {
                'doom-engine': 'doom',
                'boom-engine': 'boom',
                'heretic-engine': 'heretic',
                'hexen-engine': 'hexen',
                'doomsday': 'doomsday-compat',
        }

        for package in self.packages.values():
            engine = package.engine or self.engine
            engine = engine.split('|')[-1].strip()
            package.program = package_map.get(engine, engine)
            if 'main_wads' in self.data['packages'][package.name]:
                package.main_wads = self.data['packages'][package.name]['main_wads']
            else:
                assert package.only_file
                package.main_wads = {package.only_file: {}}
            assert type(package.main_wads) == dict
            for main_wad in package.main_wads.values():
                assert type(main_wad) == dict
            package.data_type = 'PWAD' if (package.expansion_for
                                or package.expansion_for_ext) else 'IWAD'

    def fill_extra_files(self, package, destdir):
        super(DoomGameData, self).fill_extra_files(package, destdir)

        for main_wad, quirks in package.main_wads.items():
            wad_base = os.path.splitext(main_wad)[0]

            pixdir = os.path.join(destdir, 'usr/share/pixmaps')
            mkdir_p(pixdir)
            # FIXME: would be nice if non-Doom games could replace this
            # Cacodemon with something appropriate
            desktop_file = package.name
            if len(package.main_wads) > 1:
                desktop_file += '-' + wad_base

            for basename in (wad_base, package.name, self.shortname, 'doom-common'):
                from_ = os.path.join(DATADIR, basename + '.png')
                if os.path.exists(from_):
                    install_data(from_,
                        os.path.join(pixdir, '%s.png' % desktop_file))
                    break
            else:
                raise AssertionError('doom-common.png should have existed')

            from_ = os.path.splitext(from_)[0] + '.svgz'
            if os.path.exists(from_):
                svgdir = os.path.join(destdir,
                                      'usr/share/icons/hicolor/scalable/apps')
                mkdir_p(svgdir)
                install_data(from_,
                    os.path.join(svgdir, '%s.svgz' % desktop_file))

            docdir = os.path.join(destdir, 'usr/share/doc/%s' % package.name)
            mkdir_p(docdir)

            appdir = os.path.join(destdir, 'usr/share/applications')
            mkdir_p(appdir)

            desktop = configparser.RawConfigParser()
            desktop.optionxform = lambda option: option
            desktop['Desktop Entry'] = {}
            entry = desktop['Desktop Entry']
            entry['Name'] = package.longname or self.longname
            if 'name' in quirks:
                entry['Name'] += ' - ' + quirks['name']
            entry['GenericName'] = self.genre + ' game'
            entry['TryExec'] = package.program
            if 'args' in quirks:
                args = '-file ' + main_wad + ' ' + quirks['args']
            elif package.expansion_for:
                iwad = self.packages[package.expansion_for].only_file
                assert iwad is not None, "Couldn't find %s's IWAD" % main_wad
                args = (  '-iwad /usr/share/games/doom/' + iwad
                       + ' -file /usr/share/games/doom/' + main_wad)
            else:
                args = '-iwad /usr/share/games/doom/' + main_wad
            entry['Exec'] = package.program + ' ' + args
            entry['Icon'] = desktop_file
            entry['Terminal'] = 'false'
            entry['Type'] = 'Application'
            entry['Categories'] = 'Game'
            entry['Keyword'] = wad_base

            with open(os.path.join(appdir, '%s.desktop' % desktop_file),
                      'w', encoding='utf-8') as output:
                 desktop.write(output, space_around_delimiters=False)

            lintiandir = os.path.join(destdir, 'usr/share/lintian/overrides')
            mkdir_p(lintiandir)

            with open(os.path.join(lintiandir, package.name),
                      'a', encoding='utf-8') as o:
                 o.write('%s: desktop-command-not-in-package '
                         'usr/share/applications/%s.desktop %s\n'
                         % (package.name, desktop_file, package.program))

            debdir = os.path.join(destdir, 'DEBIAN')
            mkdir_p(debdir)
            copy_with_substitutions(
                    open(os.path.join(DATADIR, 'doom-common.preinst.in'),
                        encoding='utf-8'),
                    open(os.path.join(debdir, 'preinst'), 'w',
                        encoding='utf-8'),
                    IWAD=main_wad)
            os.chmod(os.path.join(debdir, 'preinst'), 0o755)

GAME_DATA_SUBCLASS = DoomGameData
