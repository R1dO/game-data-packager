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

import os
import yaml

from game_data_packager import load_games
from game_data_packager.util import ascii_safe

if __name__ == '__main__':
    for name, game in load_games().items():
        ascii_safe(game.longname, force=True).encode('ascii')
        ascii_safe(game.help_text, force=True).encode('ascii')
        if 'DEBUG' in os.environ:
            print('# %s -----------------------------------------' % name)
            print(yaml.safe_dump(game.to_yaml()))
