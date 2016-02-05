#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2015-2016 Simon McVittie <smcv@debian.org>
#             2015-2016 Alexandre Detiste <alexandre@detiste.be>
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
from ..util import (copy_with_substitutions, mkdir_p)
from ..version import (FORMAT)

logger = logging.getLogger(__name__)

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

    def __init__(self, shortname, data):
        super(DoomGameData, self).__init__(shortname, data)

        self.wikibase = 'http://doomwiki.org/wiki/'
        assert self.wiki

        if self.engine is None:
            self.engine = {
                    'deb': "chocolate-doom | doom-engine",
                    'generic': 'chocolate-doom'
                    }

        if self.genre is None:
            self.genre = 'First-person shooter'

        for package in self.packages.values():
            package.install_to = '$assets/doom'

            if 'main_wads' in self.data['packages'][package.name]:
                package.main_wads = self.data['packages'][package.name]['main_wads']
            else:
                assert package.only_file
                package.main_wads = {package.only_file: {}}
            assert type(package.main_wads) == dict
            for main_wad in package.main_wads.values():
                assert type(main_wad) == dict
                if 'args' in main_wad:
                    main_wad['args'] % 'deadbeef'
                elif package.expansion_for:
                    assert self.packages[package.expansion_for].only_file
            package.data_type = 'PWAD' if (package.expansion_for
                                or package.expansion_for_ext) else 'IWAD'

    def construct_task(self, **kwargs):
        return DoomTask(self, **kwargs)

class DoomTask(PackagingTask):
    def fill_extra_files(self, package, destdir):
        super(DoomTask, self).fill_extra_files(package, destdir)

        for main_wad, quirks in package.main_wads.items():
            engine = self.packaging.substitute(package.engine or self.game.engine,
                    package.name)
            engine = engine.split('|')[-1].strip()
            program = self.packaging.tool_for_package(engine)

            wad_base = os.path.splitext(main_wad)[0]

            pixdir = os.path.join(destdir, 'usr/share/pixmaps')
            mkdir_p(pixdir)
            # FIXME: would be nice if non-Doom games could replace this
            # Cacodemon with something appropriate
            desktop_file = package.name
            if len(package.main_wads) > 1:
                desktop_file += '-' + wad_base

            for basename in (quirks.get('icon', wad_base), package.name,
                    self.game.shortname, 'doom-common'):
                from_ = os.path.join(DATADIR, basename + '.png')
                if os.path.exists(from_):
                    install_data(from_,
                        os.path.join(pixdir, '%s.png' % desktop_file))
                    break
            else:
                raise AssertionError('doom-common.png should have existed')

            for ext in ('.svgz', '.svg'):
                from_ = os.path.splitext(from_)[0] + ext
                if os.path.exists(from_):
                    svgdir = os.path.join(destdir,
                                      'usr/share/icons/hicolor/scalable/apps')
                    mkdir_p(svgdir)
                    install_data(from_,
                        os.path.join(svgdir, desktop_file + ext))

            appdir = os.path.join(destdir, 'usr/share/applications')
            mkdir_p(appdir)

            desktop = configparser.RawConfigParser()
            desktop.optionxform = lambda option: option
            desktop['Desktop Entry'] = {}
            entry = desktop['Desktop Entry']
            entry['Name'] = package.longname or self.game.longname
            if 'name' in quirks:
                entry['Name'] += ' - ' + quirks['name']
            entry['GenericName'] = self.game.genre + ' game'
            entry['TryExec'] = program

            install_to = self.packaging.substitute(package.install_to,
                    package.name).lstrip('/')

            if 'args' in quirks:
                args = quirks['args'] % main_wad
            elif package.expansion_for:
                iwad = self.game.packages[package.expansion_for].only_file
                assert iwad is not None, "Couldn't find %s's IWAD" % main_wad
                args = (  '-iwad /' + install_to + '/' + iwad
                       + ' -file /' + install_to + '/' + main_wad)
            else:
                args = '-iwad /' + install_to + '/' + main_wad
            entry['Exec'] = program + ' ' + args
            entry['Icon'] = desktop_file
            entry['Terminal'] = 'false'
            entry['Type'] = 'Application'
            entry['Categories'] = 'Game;'
            entry['Keywords'] = wad_base + ';'

            with open(os.path.join(appdir, '%s.desktop' % desktop_file),
                      'w', encoding='utf-8') as output:
                 desktop.write(output, space_around_delimiters=False)

            self.packaging.override_lintian(destdir, package.name,
                    'desktop-command-not-in-package',
                    'usr/share/applications/%s.desktop %s' %
                     (desktop_file, program))

            if FORMAT == 'deb':
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
