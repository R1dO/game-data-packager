#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2015 Alexandre Detiste <alexandre@detiste.be>
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

from game_data_packager import (load_games)

games = []
order = { 'demo' : 1,
          'full' : 2,
          'expansion' : 3}
for name, game in load_games().items():
    game.load_file_data()
    for package in game.packages.values():
        if package.rip_cd:
            continue
        size_min, size_max = game.size(package)
        games.append({
             'game': name,
             'year': int((package.copyright or game.copyright)[2:6]),
             'type': package.type,
             'fanmade': {True: 'Y'}.get(game.fanmade, 'N'),
             'package': package.name,
             'disks': package.disks or game.disks or 1,
             'size_min': size_min,
             'size_max': size_max,
             })

games = sorted(games, key=lambda k: (k['game'], order[k['type']], k['package']))

print('GAME;YEAR;TYPE;FANMADE;PACKAGE;DISKS;SIZE_MIN;SIZE_MAX')
for g in games:
   print('%s;%d;%s;%s;%s;%d;%d;%d' % (g['game'], g['year'], g['type'], g['fanmade'],
                                      g['package'], g['disks'], g['size_min'], g['size_max']))
