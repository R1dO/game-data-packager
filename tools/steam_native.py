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

import json
import urllib.request
from game_data_packager import load_games
from game_data_packager.util import AGENT

url = 'https://github.com/SteamDatabase/SteamLinux/raw/master/GAMES.json'
response = urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': AGENT}))
native = json.loads(response.read().decode('utf8'))
native = set(int(id) for id in native.keys())

for shortname, game in load_games().items():
   for package in game.packages.values():
       steam = package.steam or game.steam
       if not steam:
           continue
       if steam.get('native') and steam.get('id') in native:
           print('correctly tagged as native: %s' % package.name)
       elif steam.get('native'):
           print('extraneously tagged as native: %s' % package.name)
       elif steam.get('id') in native:
           print('should be tagged as native: %s' % package.name)
