#!/usr/bin/python3
# vim:set fenc=utf-8:
#
# Copyright © 2014 Simon McVittie <smcv@debian.org>
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

from .. import GameData

logger = logging.getLogger('game-data-packager.games.tyrian')

class TyrianGameData(GameData):
    def add_parser(self, parsers, base_parser):
        parser = super(TyrianGameData, self).add_parser(parsers, base_parser)
        parser.add_argument('-f', action='append', dest='paths',
                metavar='tyrian21.zip', help='Path to tyrian21.zip')
        parser.add_argument('-w', dest='download', action='store_true',
                help='Download tyrian21.zip (done automatically if necessary)')
        return parser

GAME_DATA_SUBCLASS = TyrianGameData
