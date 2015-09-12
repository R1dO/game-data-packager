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
import os
import subprocess

from .util import which

def owned_gog_games():
    cache = os.path.expanduser('~/.cache/lgogdownloader/gamedetails.json')
    if os.path.isfile(cache):
       data = json.load(open(cache, encoding='utf-8'))
       for key in data['games']:
           yield key['gamename']
    elif which('lgogdownloader'):
       try:
           list = subprocess.check_output(['lgogdownloader', '--list'],
                               stdin=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL,
                               universal_newlines=True)
       except subprocess.CalledProcessError:
           return
       for line in list.splitlines():
           yield line
