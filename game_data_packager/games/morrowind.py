#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2016 Alexandre Detiste <alexandre@detiste.be>
#             2016 Simon McVittie <smcv@debian.org>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License version 2
# as published by the Free Software Foundation.
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
from ..util import (check_call)

logger = logging.getLogger(__name__)

class MorrowindGameData(GameData):
    def construct_task(self, **kwargs):
        return MorrowindTask(self, **kwargs)

class MorrowindTask(PackagingTask):
    def fill_dest_dir(self, package, destdir):
        super(MorrowindTask, self).fill_dest_dir(package, destdir)

        install_to = self.packaging.substitute(package.install_to,
                                               package.name)

        datadir = os.path.join(destdir, install_to.strip('/'))
        assert datadir.startswith(destdir + '/'), (datadir, destdir)

        subdir_expected_by_iniimporter = os.path.join(datadir, 'Data Files')
        os.symlink(datadir, subdir_expected_by_iniimporter)

        ini = os.path.join(datadir, 'Morrowind.ini')

        initext = open(ini + '.orig', encoding='latin-1').read()

        if package.name.startswith( # either of:
                ('morrowind-tribunal', 'morrowind-complete')):
            initext = initext + '\r\nGameFile1=Tribunal.esm\r\n'

        if package.name.startswith('morrowind-bloodmoon'):
            initext = initext + '\r\nGameFile1=Bloodmoon.esm\r\n'

        if package.name.startswith('morrowind-complete'):
            initext = initext + '\r\nGameFile2=Bloodmoon.esm\r\n'

        open(ini, 'w', encoding='latin-1').write(initext)

        cfg = os.path.join(datadir, 'openmw.cfg')

        check_call(['openmw-iniimporter',
                    '--verbose',
                    '--game-files',
                    '--encoding', 'win1252',
                    '--ini', ini,
                    '--cfg', cfg])
        os.unlink(subdir_expected_by_iniimporter)

        with open(cfg, 'a', encoding='utf-8') as f:
            f.write('data=%s\n' % os.path.join('/', install_to))

        # then user needs to do this:
        #
        # $ mkdir -p ~/.config/openmw/
        # $ cp /usr/share/games/morrowind-fr/openmw.cfg ~/.config/openmw/

# 1) sample output of openmw-iniimporter without "Data Files"

#cfg file does not exist
#load ini file: "/tmp/gdptmp.k5ig_6ps/morrowind-fr-data.deb.d/usr/share/games/morrowind-fr/Morrowind.ini"
#Warning: ignored empty value for key 'General:Beta Comment File'.
#Warning: ignored empty value for key 'General:Editor Starting Cell'.
#load cfg file: "/tmp/gdptmp.k5ig_6ps/morrowind-fr-data.deb.d/usr/share/games/morrowind-fr/openmw.cfg"
#content file: "/tmp/gdptmp.k5ig_6ps/morrowind-fr-data.deb.d/usr/share/games/morrowind-fr/Data Files/Morrowind.esm" not found
#write to: /tmp/gdptmp.k5ig_6ps/morrowind-fr-data.deb.d/usr/share/games/morrowind-fr/openmw.cfg

# 2) I can't 100% reproduce the openmw.cfg created by openmw

#$ diff -uw .config/openmw/openmw.cfg /usr/share/games/morrowind-fr/openmw.cfg
#--- .config/openmw/openmw.cfg   2016-01-19 14:46:28.522761855 +0100
#+++ /usr/share/games/morrowind-fr/openmw.cfg    2016-01-19 14:52:58.000000000 +0100
#@@ -1,5 +1,4 @@
#-no-sound=0
#-fallback-archive=Morrowind.bsa
#+content=Morrowind.esm
# fallback=LightAttenuation_UseConstant,0
# fallback=LightAttenuation_ConstantValue,0.0
# fallback=LightAttenuation_UseLinear,1
#@@ -494,6 +493,15 @@
# fallback=Moons_Masser_Fade_In_Finish,15
# fallback=Moons_Masser_Fade_Out_Start,7
# fallback=Moons_Masser_Fade_Out_Finish,10
#-encoding=win1252
#-data=/usr/share/games/morrowind-fr
#-content=Morrowind.esm
#+fallback=Blood_Model_0,BloodSplat.nif
#+fallback=Blood_Model_1,BloodSplat2.nif
#+fallback=Blood_Model_2,BloodSplat3.nif
#+fallback=Blood_Texture_0,Tx_Blood.tga
#+fallback=Blood_Texture_1,Tx_Blood_White.tga
#+fallback=Blood_Texture_2,Tx_Blood_Gold.tga
#+fallback=Blood_Texture_Name_0,Default (Red)
#+fallback=Blood_Texture_Name_1,Skeleton (White)
#+fallback=Blood_Texture_Name_2,Metal Sparks (Gold)
#+fallback-archive=Morrowind.bsa
#+no-sound=0
#+data=/usr/share/games/morrowind-fr

GAME_DATA_SUBCLASS = MorrowindGameData
