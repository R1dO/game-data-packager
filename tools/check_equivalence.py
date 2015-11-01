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

import difflib
import json
import os
import sys
import time

from game_data_packager import load_games
from game_data_packager.util import ascii_safe

def dump(serialized):
    return json.dumps(serialized, sort_keys=True, indent=2)

if __name__ == '__main__':
    games = '*'

    if len(sys.argv) > 1:
        assert len(sys.argv) == 2
        games = sys.argv[1]

    if os.path.exists('ref.zip'):
        t = time.process_time()
        # usage:
        # make
        # cp out/vfs.zip ref.zip
        # make
        # make check
        from_ref = load_games(games, use_vfs='ref.zip')
        dt = time.process_time() - t
        print('# loaded game data from ref.zip in %.3f seconds' % dt)
    else:
        from_ref = None

    t = time.process_time()
    from_vfs = load_games(games, use_vfs=True)
    dt = time.process_time() - t
    print('# loaded game data from vfs.zip in %.3f seconds' % dt)

    t = time.process_time()
    from_json = load_games(games, use_vfs=False)
    dt = time.process_time() - t
    print('# loaded game data from JSON in %.3f seconds' % dt)

    t = time.process_time()
    from_yaml = load_games(games, use_vfs=False, use_yaml=True)
    dt = time.process_time() - t
    print('# loaded game data from YAML in %.3f seconds' % dt)

    assert set(from_vfs.keys()) == set(from_json.keys())
    assert set(from_vfs.keys()) == set(from_yaml.keys())

    if from_ref is not None:
        assert set(from_vfs.keys()) == set(from_ref.keys())

    fail = False

    for (name, game) in sorted(from_vfs.items()):
        print('# %s -----------------------------------------' % name)

        game.load_file_data()
        ascii_safe(game.longname, force=True).encode('ascii')
        ascii_safe(game.help_text, force=True).encode('ascii')
        vfs_to_json = dump(game.to_yaml())

        json_game = from_json[name]
        json_game.load_file_data()
        json_to_json = dump(json_game.to_yaml())

        yaml_game = from_yaml[name]
        yaml_game.load_file_data()
        yaml_to_json = dump(yaml_game.to_yaml())

        if yaml_to_json != vfs_to_json:
            sys.stdout.writelines(difflib.unified_diff(
                yaml_to_json.splitlines(True),
                vfs_to_json.splitlines(True),
                '%s loaded from YAML' % name,
                '%s loaded from vfs.zip' % name, n=50))
            fail = True

        if json_to_json != vfs_to_json:
            sys.stdout.writelines(difflib.unified_diff(
                json_to_json.splitlines(True),
                vfs_to_json.splitlines(True),
                '%s loaded from JSON' % name,
                '%s loaded from vfs.zip' % name, n=50))
            fail = True

        if from_ref is not None:
            ref_game = from_ref[name]
            ref_game.load_file_data(use_vfs='ref.zip')
            ref_to_json = dump(ref_game.to_yaml())

            if ref_to_json != vfs_to_json:
                sys.stdout.writelines(difflib.unified_diff(
                    ref_to_json.splitlines(True),
                    vfs_to_json.splitlines(True),
                    '%s loaded from ref.zip' % name,
                    '%s loaded from vfs.zip' % name, n=50))

    raise SystemExit(fail)
