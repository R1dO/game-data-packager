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

# a simple spider to locate Wikipedia url
# in per-engine-wiki pages
# we don't rescan games we already have

import sys
import time
import urllib.request
from bs4 import BeautifulSoup
from game_data_packager import load_games

CSV = 'data/wikipedia.csv'

try:
     todo = sys.argv[1]
except IndexError:
     todo = '*'

urls = dict()
with open(CSV, 'r', encoding='utf8') as f:
    for line in f.readlines():
        line = line.strip()
        if not line:
            continue
        shortname, url = line.split(';', 1)
        urls[shortname] = url

def is_wikipedia(href):
    return href and "wikipedia" in href

for shortname, game in load_games(None, game=todo).items():
    if not game.wiki:
        continue
    if shortname in urls:
        continue

    print('processing %s ...' % shortname)
    url = game.wikibase + game.wiki
    html = urllib.request.urlopen(url)
    soup = BeautifulSoup(html, 'lxml')
    for tag in soup.find_all(href=is_wikipedia):
        print('  ' + tag['href'])
        urls[shortname] = tag['href']

    #break
    time.sleep(1)

# write it back
with open(CSV, 'w', encoding='utf8') as f:
    for shortname in sorted(urls.keys()):
        f.write(shortname + ';' + urls[shortname] + '\n')
