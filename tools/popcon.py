#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2016 Alexandre Detiste <alexandre@detiste.be>
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
import gzip
import sys

scope = set()
with open('out/bash_completion', 'r') as bash:
    # keep each even line
    while bash.readline():
        scope |= set(bash.readline().rstrip().split())

# old package names
scope.add('quake2-data')
scope.add('wolf3d-data-wl1')
scope.add('wolf3d-v14-data')
scope.add('rtcw-data')

# add this to compare against other Doom packages
scope.add('doom-wad-shareware')

scope.add('game-data-packager')

def process(scope, distro):
    result = dict()
    if len(sys.argv) == 2:
        popcon = '/var/cache/popcon/' + distro + '_' + sys.argv[1] + '.gz'
    else:
        popcon = sorted(glob.glob('/var/cache/popcon/' + distro + '_*.gz')).pop()

    with gzip.open(popcon, 'rb') as f:
        file_content = f.read().decode('latin1')
    for line in file_content.split('\n'):
        if not line or line[0] in ('#','-'):
            continue
        try:
            package, score = line.split()[1:3]
            score = int(score)
            if package in scope:
                #print("%30s %d" % (package, score))
                result[package] = score
        # theres is some random crap with 0 popcon in the Ubuntu file
        except ValueError:
            #print(distro,line)
            pass

    return result

debian = process(scope, 'debian')
ubuntu = process(scope, 'ubuntu')

games = []
for key in scope:
     games.append({
                   'name': key,
                   'debian': debian.get(key, 0),
                   'ubuntu': ubuntu.get(key, 0),
                  })

games = sorted(games, key=lambda k: (-k['debian'], k['name']))

print ('Package                                             Debian   Ubuntu')
print ('-------------------------------------------------------------------')
for package in games:
    print('%49s %8d %8d' % (package['name'],
                            package['debian'],
                            package['ubuntu']))
