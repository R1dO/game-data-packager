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

CDROM_SECTOR = 2048

import hashlib
import sys

if len(sys.argv) != 2:
    exit('Usage: cdrom_md5.py <file>')

with open(sys.argv[1], 'rb') as f:
    while True:
        blob = f.read(CDROM_SECTOR)
        if not blob:
            break
        md5 = hashlib.new('md5')
        md5.update(blob)
        print(md5.hexdigest())
