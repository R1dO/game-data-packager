#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2015 Alexandre Detiste <alexandre@detiste.be>
#           © 2015 Simon McVittie <smcv@debian.org>
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
import zipfile

from .. import (GameData)
from ..build import (PackagingTask, mkdir_p)

logger = logging.getLogger('game-data-packager.games.rtcw')

class RTCWGameData(GameData):
    def construct_task(self, **kwargs):
        return RTCWTask(self, **kwargs)

class RTCWTask(PackagingTask):
    def fill_dest_dir(self, package, destdir):
        if not super(RTCWTask, self).fill_dest_dir(package, destdir):
            return False

        if package.name != 'rtcw-fr-data':
            return True

        zip_in = os.path.join(destdir, 'usr/share/games/rtcw/main', 'sp_pak1.pk3')
        zip_out = os.path.join(destdir, 'usr/share/games/rtcw/main', 'sp_pak3_fr.pk3')

        with zipfile.ZipFile(zip_in, 'r') as zf_in:
            txt = zf_in.open('text/EnglishUSA/escape1.txt').read()
        with zipfile.ZipFile(zip_out, 'w') as zf_out:
            zf_out.writestr('text/EnglishUSA/escape1.txt', txt)

        return True

GAME_DATA_SUBCLASS = RTCWGameData
