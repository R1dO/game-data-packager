#!/usr/bin/python3
# encoding=utf-8
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

logger = logging.getLogger('game-data-packager.games.rott')

class ROTTGameData(GameData):
    def add_parser(self, parsers, base_parser):
        parser = super(ROTTGameData, self).add_parser(parsers, base_parser)
        parser.add_argument('-f', dest='download', action='store_false',
                help='Require 1rott13.zip on the command line')
        parser.add_argument('-w', dest='download', action='store_true',
                help='Download 1rott13.zip (done automatically if necessary)')
        return parser

GAME_DATA_SUBCLASS = ROTTGameData
