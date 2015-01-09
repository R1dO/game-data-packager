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

import os
import sys

from . import GameData

if __name__ == '__main__':
    with GameData(sys.argv[1],
            datadir=os.environ['DATADIR'],
            workdir=os.environ['WORKDIR'],
            etcdir=os.environ['ETCDIR'],
            ) as game:
        game.run_command_line(sys.argv[2:])
