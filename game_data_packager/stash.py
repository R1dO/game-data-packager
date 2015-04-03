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

import glob
import os
import sys

from . import load_games,GameData,HashedFile

if len(sys.argv) == 1 or not os.path.isdir(sys.argv[1]):
    sys.exit("This tool help you package all the games from your game stash\n\n"
             "Usage: %s <destination_folder>" % sys.argv[0])

files = []
for name, game in load_games().items():
    for filename,f in game.files.items():
         if f.size and f.size > 100000:
             files.append({'game' : name,
                           'name' : filename,
                           'size' : f.size,
                           'md5' : f.md5,
                           'unsuitable' : f.unsuitable})

games = set()
unsuitable = dict()
for path in sorted(glob.glob(sys.argv[1] + '/*')):
    if os.path.isfile(path):
        size = os.stat(path).st_size
        hashes = HashedFile.from_file(path, open(path, 'rb'))
        match = False
        for file in files:
            if file['size'] == size and file['md5'] == hashes.md5:
                match = True
                if file['unsuitable']:
                    unsuitable[file['game']] = [path, file['unsuitable']]
                else:
                    games.add(file['game'])
                break
        if os.environ.get('DEBUG'):
            print('%-20s %-30s %10d %s' % (file['game'] if match else '<>', 
                                  os.path.basename(path), size, hashes.md5))

for game in games:
   if game in unsuitable: del unsuitable[game]

if unsuitable:
   print('The files for these games are not supported:')
   for game in unsuitable:
        print(" %s %s, reason: %s" % (game, 
              unsuitable[game][0] , unsuitable[game][1]))

if games:
   print('These games seems to be avaible:')
   print(sorted(games))
   print('trying to package...')
   # XXX: actually do something
else:
   sys.exit('Found nothing to package')
