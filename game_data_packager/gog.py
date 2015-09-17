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

class Gog:
    available = None

    def owned_games(self):
        if self.available is not None:
            return self.available

        self.available = []
        cache = os.path.expanduser('~/.cache/lgogdownloader/gamedetails.json')
        if not which('lgogdownloader'):
            pass
        elif os.path.isfile(cache):
            data = json.load(open(cache, encoding='utf-8'))
            for key in data['games']:
                self.available.append(key['gamename'])
        else:
            try:
                list = subprocess.check_output(['lgogdownloader', '--list'],
                               stdin=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL,
                               universal_newlines=True)
                self.available = list.splitlines()
            except subprocess.CalledProcessError:
                pass

        return self.available

    def is_native(self, wanted):
        cache = os.path.expanduser('~/.cache/lgogdownloader/gamedetails.json')
        if not os.path.isfile(cache):
            return

        data = json.load(open(cache, encoding='utf-8'))
        for game in data['games']:
            if game['gamename'] != wanted:
                continue
            for installer in game['installers']:
                if installer['platform'] == 4:
                    return True
            return False

    def get_id_from_archive(self, archive):
        cache = os.path.expanduser('~/.cache/lgogdownloader/gamedetails.json')
        if not os.path.isfile(cache):
            return None

        archive = os.path.basename(archive)

        data = json.load(open(cache, encoding='utf-8'))
        for game in data['games']:
            for installer in game['installers']:
                if installer['path'].endswith(archive):
                    return game['gamename']

GOG = Gog()
