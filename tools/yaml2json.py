#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2015 Simon McVittie <smcv@debian.org>
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
import sys

import yaml

def main(f, out):
    data = yaml.load(open(f, encoding='utf-8'), Loader=yaml.CSafeLoader)
    json.dump(data, open(out + '.tmp', 'w', encoding='utf-8'), sort_keys=True)
    os.rename(out + '.tmp', out)

if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])

