#!/usr/bin/python3
# vim:set fenc=utf-8:
#
# Copyright © 2014 Simon McVittie <smcv@debian.org>
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

import argparse
import os
import sys

from . import GameDataPackage

def go(argv):
    parser = argparse.ArgumentParser(description='Package game files.',
            prog='game-data-packager ' + os.environ['SHORTNAME'])
    parser.add_argument('--repack', action='store_true')
    parser.add_argument('paths', nargs='*',
            metavar='DIRECTORY|FILE')
    args = parser.parse_args(argv[1:])

    with GameDataPackage(argv[0],
            datadir=os.environ['DATADIR'],
            workdir=os.environ['WORKDIR'],
            etcdir=os.environ['ETCDIR'],
            ) as package:

        if args.repack:
            args.paths.insert(0, '/' + package.install_to)

        for arg in args.paths:
            package.consider_file_or_dir(arg)

        package.fill_gaps()
        package.fill_gaps(download=True)

        if not package.fill_dest_dir(os.environ['DESTDIR']):
            sys.exit(1)

    # FIXME: make the .deb (currently done in shell script by the wrapper)

if __name__ == '__main__':
    go(sys.argv[1:])
