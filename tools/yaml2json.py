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
    data = yaml.load(open(f, encoding='utf-8'), Loader=yaml.CLoader)
    game = f[5:].split('.')[0]

    with open('data/wikipedia.csv', 'r', encoding='utf8') as csv:
        for line in csv.readlines():
            shortname, url = line.strip().split(';', 1)
            if shortname == game:
                data['wikipedia'] = url
                break

    v = data.pop('files', None)
    if v is not None:
        offload = os.path.splitext(out)[0] + '.files'
        json.dump(v, open(offload + '.tmp', 'w', encoding='utf-8'), sort_keys=True)
        os.rename(offload + '.tmp', offload)

    for k in ('cksums', 'sha1sums', 'sha256sums', 'md5sums',
            'size_and_md5'):
        v = data.pop(k, None)
        offload = os.path.splitext(out)[0] + '.' + k

        if v is not None:
            with open(offload + '.tmp', 'w', encoding='utf-8') as writer:
                for line in v.splitlines():
                    stripped = line.strip()
                    if stripped == '' or stripped.startswith('#'):
                        continue
                    writer.write(line)
                    writer.write('\n')
            os.rename(offload + '.tmp', offload)
        elif os.path.isfile(offload):
            os.remove(offload)

    json.dump(data, open(out + '.tmp', 'w', encoding='utf-8'), sort_keys=True)
    os.rename(out + '.tmp', out)

if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
