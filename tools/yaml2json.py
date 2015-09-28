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
import sys

import yaml

def main():
    for f in sys.argv[1:]:
        data = yaml.load(open(f, encoding='utf-8'), Loader=yaml.CLoader)
        game = f[5:].split('.')[0]
        with open('data/wikipedia.csv', 'r', encoding='utf8') as csv:
            for line in csv.readlines():
                shortname, url = line.strip().split(';', 1)
                if shortname == game:
                    data['wikipedia'] = url
                    break
        json.dump(data, sys.stdout, sort_keys=True)

if __name__ == '__main__':
    main()
