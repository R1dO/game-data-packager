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

from game_data_packager import (load_games, GameData, FillResult)

games = []
for name, game in load_games().items():
    freeload = False
    for package in game.packages.values():
        if package.rip_cd or package.expansion_for:
            continue
        elif GameData.fill_gaps(game, package=package,
                log=False) is not FillResult.IMPOSSIBLE:
            freeload = True
            break

    game_struct = {
             'genre': game.genre or 'Unknown',
             'shortname': name,
             'longname': game.longname,
             'freeload': '' if freeload else "  ($)",
             }
    games.append(game_struct)

games = sorted(games, key=lambda k: (k['genre'], k['shortname'], k['longname']))

last_genre = None
for game in games:
   if last_genre is None or game['genre'] != last_genre:
       print('[%s]' % game['genre'])
   print('%20s - %s%s' % (game['shortname'], game['longname'], game['freeload']))
   last_genre = game['genre']

print('')
print('($): no freeload (fullgame/demo) available')
print('     remember there is doom-wad-shareware in non-free repository')
