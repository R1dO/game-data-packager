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

# pre-calculate a list of packages from yaml files
# for bash auto-completion

import os
import glob
#import yaml

for yaml_file in sorted(glob.glob('data/*.yaml')):
    print(os.path.splitext(os.path.basename(yaml_file))[0])
    with open(yaml_file, encoding='utf-8') as raw:
        #yaml_data = yaml.load(raw, Loader=yaml.CSafeLoader)
        #for key in sorted(yaml_data['packages'].keys()):
        #    print(key, end=' ')

        for line in raw:
            if line.strip() == 'packages:':
                break
        for line in raw:
            if line == '\n':
                continue
            if line[0] != ' ':
                break
            if line[2] not in (' ', '#'):
                print(line.strip(':\n '), end=' ')

        print('')
