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
import logging
import os
import sys

from . import GameData

logging.basicConfig()
logger = logging.getLogger('game-data-packager')

def go(argv):
    parser = argparse.ArgumentParser(description='Package game files.',
            prog='game-data-packager ' + os.environ['SHORTNAME'])
    parser.add_argument('--repack', action='store_true')
    parser.add_argument('paths', nargs='*',
            metavar='DIRECTORY|FILE')
    args = parser.parse_args(argv[1:])

    with GameData(argv[0],
            datadir=os.environ['DATADIR'],
            workdir=os.environ['WORKDIR'],
            etcdir=os.environ['ETCDIR'],
            ) as game:

        if args.repack:
            can_repack = False
            absent = set()

            for package in game.packages.values():
                path = '/' + package.install_to
                if os.path.isdir(path):
                    args.paths.insert(0, path)
                    can_repack = True
                elif (package.name == 'quake3-data' and
                        os.path.isdir('/usr/share/games/quake3')):
                    # FIXME: this is a hack, it would be better to
                    # have alternative locations defined in the YAML
                    args.paths.insert(0, path)
                    can_repack = True
                else:
                    absent.add(path)

            if not can_repack:
                raise SystemExit('cannot repack %s: could not open %r' %
                        (package, sorted(absent)))

        for arg in args.paths:
            game.consider_file_or_dir(arg)

        possible = set()

        for package in game.packages.values():
            if argv[0] in game.packages and package.name != argv[0]:
                continue

            if game.fill_gaps(package, log=False):
                logger.debug('%s is possible', package.name)
                possible.add(package)
            else:
                logger.debug('%s is impossible', package.name)

        if not possible:
            logger.debug('No packages were possible')
            # Repeat the process for the first (hopefully only)
            # demo/shareware package, so we can log its errors.
            for package in game.packages.values():
                if package.type == 'demo':
                    if game.fill_gaps(package=package, log=True):
                        logger.error('%s unexpectedly succeeded on second ' +
                                'attempt. Please report this as a bug',
                                package.name)
                        possible.add(package)
                    else:
                        sys.exit(1)
            else:
                # If no demo, repeat the process for the first
                # (hopefully only) full package, so we can log *its* errors.
                for package in game.packages.values():
                    if package.type == 'full':
                        if game.fill_gaps(package=package, log=True):
                            logger.error('%s unexpectedly succeeded on ' +
                                    'second attempt. Please report this as '
                                    'a bug', package.name)
                            possible.add(package)
                        else:
                            sys.exit(1)
                else:
                    raise SystemExit('Unable to complete any packages. ' +
                            'Please provide more files or directories.')

        ready = set()

        have_full = False
        for package in possible:
            if package.type == 'full':
                have_full = True

        for package in possible:
            if have_full and package.type == 'demo':
                # no point in packaging the demo if we have the full
                # version
                logger.debug('will not produce %s because we have a full ' +
                        'version', package.name)
                continue

            logger.debug('will produce %s', package.name)
            if game.fill_gaps(package=package, download=True, log=True):
                ready.add(package)
            else:
                logger.error('Failed to download necessary files for %s',
                        package.name)

        if not ready:
            sys.exit(1)

        for package in ready:
            destdir = os.path.join(os.environ['WORKDIR'],
                    '%s.deb.d' % package.name)
            if not game.fill_dest_dir(package, destdir):
                sys.exit(1)

    # FIXME: make the .deb (currently done in shell script by the wrapper)

if __name__ == '__main__':
    go(sys.argv[1:])
