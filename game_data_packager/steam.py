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
import xml.etree.ElementTree
import urllib.request

def parse_acf(path):
    for manifest in glob.glob(path + '/*.acf'):
        with open(manifest) as data:
            # the .acf files are not really JSON files
            level = 0
            acf_struct = {}
            for line in data.readlines():
                if line.strip() == '{':
                   level += 1
                elif line.strip() == '}':
                   level -= 1
                elif level != 1:
                   continue
                elif '"\t\t"' in line:
                   key , value = line.split('\t\t')
                   key = key.strip().strip('"')
                   value = value.strip().strip('"')
                   if key in ('appid', 'name', 'installdir'):
                       acf_struct[key] = value
            if 'name' not in acf_struct:
                acf_struct['name'] = acf_struct['installdir']
            yield acf_struct

def owned_steam_games(steam_id):
    url = "http://steamcommunity.com/profiles/" + steam_id + "/games?xml=1"
    html = urllib.request.urlopen(url)
    tree = xml.etree.ElementTree.ElementTree()
    tree.parse(html)
    games_xml = tree.getiterator('game')
    for game in games_xml:
        appid = int(game.find('appID').text)
        name = game.find('name').text
        #print(appid, name)
        yield (appid, name)

def get_steam_id():
    path = os.path.expanduser('~/.steam/config/loginusers.vdf')
    if not os.path.isfile(path):
        return None
    with open(path, 'r', ) as data:
        for line in data.readlines():
            line = line.strip('\t\n "')
            if line not in ('users', '{'):
                return line
