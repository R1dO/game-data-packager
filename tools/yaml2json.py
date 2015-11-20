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
    game = f[5:].split('.')[0]

    with open('data/wikipedia.csv', 'r', encoding='utf8') as csv:
        for line in csv.readlines():
            shortname, url = line.strip().split(';', 1)
            if shortname == game:
                data['wikipedia'] = url
                break

    v = data.pop('files', None)
    offload = os.path.splitext(out)[0] + '.files'
    if v is not None:
        json.dump(v, open(offload + '.tmp', 'w', encoding='utf-8'), sort_keys=True)
        os.rename(offload + '.tmp', offload)
    elif os.path.isfile(offload):
        os.remove(offload)

    groups = data.pop('groups', None)
    offload = os.path.splitext(out)[0] + '.groups'

    if groups is not None:
        with open(offload + '.tmp', 'w', encoding='utf-8') as writer:
            assert isinstance(groups, dict)
            for group_name, group_data in sorted(groups.items()):
                writer.write('[%s]\n' % group_name)

                if isinstance(group_data, dict):
                    attrs = {}
                    members = group_data['group_members']
                    for k, v in group_data.items():
                        if k != 'group_members':
                            attrs[k] = v
                    if attrs:
                        json.dump(attrs, writer, sort_keys=True)
                        writer.write('\n')
                elif isinstance(group_data, (str, list)):
                    members = group_data
                else:
                    raise AssertionError('group %r should be dict, str or list' % group_name)

                has_members = False

                if isinstance(members, str):
                    for line in members.splitlines():
                        assert not line.startswith('[')
                        assert not line.startswith('{')
                        line = line.strip()
                        if line and not line.startswith('#'):
                            has_members = True
                            writer.write(' '.join(line.split()))
                            writer.write('\n')
                elif isinstance(members, list):
                    for m in members:
                        has_members = True
                        writer.write('? ? %s\n' % m)
                else:
                    raise AssertionError('group %r members should be str or list' % group_name)

                # an empty group is no use, and would break the assumption
                # that we can use f.group_members to detect groups
                assert has_members

        os.rename(offload + '.tmp', offload)
    elif os.path.isfile(offload):
        os.remove(offload)

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
