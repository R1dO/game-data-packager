#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2014-2016 Simon McVittie <smcv@debian.org>
# Copyright © 2015-2016 Alexandre Detiste <alexandre@detiste.be>
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
import time
import zipfile

from . import (load_games)
from .config import (read_config)
from .data import (ProgressCallback)
from .gog import (run_gog_meta_mode)
from .paths import (DATADIR)
from .steam import (run_steam_meta_mode)
from .util import (human_size)

logger = logging.getLogger(__name__)

class TerminalProgress(ProgressCallback):
    def __init__(self, interval=0.2, info=None):
        """Constructor.

        Progress will update at most once per @interval seconds, unless we
        are at a "checkpoint".
        """
        self.pad = ' '
        self.interval = interval
        self.ts = time.time()
        self.info = info

    def __call__(self, done=None, total=None, checkpoint=False):
        ts = time.time()

        if done is None or (ts < self.ts + self.interval and not checkpoint):
            return

        if self.info is not None:
            print(self.info, file=sys.stderr)
            self.info = None

        if done is None or total == 0:
            s = ''
        elif total is None or total == 0:
            s = human_size(done)
        else:
            s = '%.0f%% %s/%s' % (100 * done / total,
                    human_size(done),
                    human_size(total))

        self.ts = ts

        if len(self.pad) <= len(s):
            self.pad = ' ' * len(s)

        print(' %s \r %s\r' % (self.pad, s), end='', file=sys.stderr)

    def __enter__(self):
        return self

    def __exit__(self, et=None, ev=None, tb=None):
        self()

def run_command_line():
    logger.debug('Arguments: %r', sys.argv)

    # Don't set any defaults on this base parser, because it interferes
    # with the ability to recognise the same argument either before or
    # after the game name. Set them on the Namespace instead.
    base_parser = argparse.ArgumentParser(prog='game-data-packager',
            description='Package game files.',
            add_help=False,
            argument_default=argparse.SUPPRESS)

    base_parser.add_argument('--package', '-p', action='append',
            dest='packages', metavar='PACKAGE',
            help='Produce this data package (may be repeated)')

    base_parser.add_argument('--install-method', metavar='METHOD',
            dest='install_method',
            help='Use METHOD (apt, dpkg, gdebi, gdebi-gtk, gdebi-kde) ' +
                'to install packages')

    base_parser.add_argument('--gain-root-command', metavar='METHOD',
            dest='gain_root_command',
            help='Use METHOD (su, sudo, pkexec) to gain root if needed')

    # This is about ability to audit, not freeness. We don't have an
    # option to restrict g-d-p to dealing with Free Software, because
    # that would rule out the vast majority of its packages: if a game's
    # data is Free Software, we could put it in main or contrib and not need
    # g-d-p at all.
    base_parser.add_argument('--binary-executables', action='store_true',
            help='allow installation of executable code that was not built ' +
                'from public source code')

    # Misc options
    group = base_parser.add_mutually_exclusive_group()
    group.add_argument('-i', '--install', action='store_true',
            help='install the generated package')
    group.add_argument('-n', '--no-install', action='store_false',
            dest='install',
            help='do not install the generated package (requires -d, default)')
    base_parser.add_argument('-d', '--destination', metavar='OUTDIR',
            help='write the generated .deb(s) to OUTDIR')

    group = base_parser.add_mutually_exclusive_group()
    group.add_argument('-z', '--compress', action='store_true',
            help='compress generated .deb (default if -d is used)')
    group.add_argument('--no-compress', action='store_false',
            dest='compress',
            help='do not compress generated .deb (default without -d)')

    group = base_parser.add_mutually_exclusive_group()
    group.add_argument('--download', action='store_true',
            help='automatically download necessary files if possible ' +
                '(default)')
    group.add_argument('--no-download', action='store_false',
            dest='download', help='do not download anything')
    base_parser.add_argument('--save-downloads', metavar='DIR',
            help='save downloaded files to DIR, and look for files there')

    group = base_parser.add_mutually_exclusive_group()
    group.add_argument('--verbose', action='store_true',
            help='show output from external tools')
    group.add_argument('--no-verbose', action='store_false',
            dest='verbose', help='hide output from external '
             'tools (default)')

    class DebugAction(argparse.Action):
        def __call__(self, parser, namespace, values, option_string=None):
            logging.getLogger().setLevel(logging.DEBUG)

    base_parser.add_argument('--debug', action=DebugAction, nargs=0,
            help='show debug messages')

    class DumbParser(argparse.ArgumentParser):
        def error(self, message):
            pass

    dumb_parser = DumbParser(parents=(base_parser,),add_help=False)
    dumb_parser.add_argument('game', type=str, nargs='?')
    dumb_parser.add_argument('paths', type=str, nargs='*')
    dumb_parser.add_argument('-h', '--help', action='store_true', dest='h')
    g = dumb_parser.parse_args().game
    zip = os.path.join(DATADIR, 'vfs.zip')
    if g is None:
        games = load_games()
    elif '-h' in sys.argv or '--help' in sys.argv:
        games = load_games()
    elif os.path.isfile(os.path.join(DATADIR, '%s.json' % g)):
        games = load_games(game=g)
    elif not os.path.isfile(zip):
        games = load_games()
    else:
        with zipfile.ZipFile(zip, 'r') as zf:
            if '%s.json' % g in zf.namelist():
                games = load_games(game=g)
            else:
                games = load_games()

    parser = argparse.ArgumentParser(prog='game-data-packager',
            description='Package game files.', parents=(base_parser,),
            epilog='Run "game-data-packager GAME --help" to see ' +
                'game-specific arguments.')

    game_parsers = parser.add_subparsers(dest='shortname',
            title='supported games', metavar='GAME')

    for g in sorted(games.keys()):
        games[g].add_parser(game_parsers, base_parser)

    # GOG meta-mode
    gog_parser = game_parsers.add_parser('gog',
        help='Package all your GOG.com games at once',
        description='Automatically package all your GOG.com games',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=(base_parser,))
    group = gog_parser.add_mutually_exclusive_group()
    group.add_argument('--all', action='store_true', default=False,
                       help='show all GOG.com games')
    group.add_argument('--new', action='store_true', default=False,
                       help='show all new GOG.com games')

    # Steam meta-mode
    steam_parser = game_parsers.add_parser('steam',
        help='Package all Steam games at once',
        description='Automatically package all your Steam games',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=(base_parser,))
    group = steam_parser.add_mutually_exclusive_group()
    group.add_argument('--all', action='store_true', default=False,
                       help='package all Steam games')
    group.add_argument('--new', action='store_true', default=False,
                       help='package all new Steam games')

    config = read_config()
    parsed = argparse.Namespace(
            binary_executables=False,
            compress=None,
            destination=None,
            download=True,
            verbose=False,
            install=False,
            install_method='',
            gain_root_command='',
            packages=[],
            save_downloads=None,
            shortname=None,
    )
    if config['install']:
        logger.debug('obeying INSTALL=yes in configuration')
        parsed.install = True
    if config['preserve']:
        logger.debug('obeying PRESERVE=yes in configuration')
        parsed.destination = '.'
    if config['verbose']:
        logger.debug('obeying VERBOSE=yes in configuration')
        parsed.verbose = True
    if config['install_method']:
        logger.debug('obeying INSTALL_METHOD=%r in configuration',
                config['install_method'])
        parsed.install_method = config['install_method']
    if config['gain_root_command']:
        logger.debug('obeying GAIN_ROOT_COMMAND=%r in configuration',
                config['gain_root_command'])
        parsed.gain_root_command = config['gain_root_command']

    parser.parse_args(namespace=parsed)
    logger.debug('parsed command-line arguments into: %r', parsed)

    if parsed.destination is None and not parsed.install:
        logger.error('At least one of --install or --destination is required')
        sys.exit(2)

    if parsed.shortname is None:
        parser.print_help()
        sys.exit(0)

    for arg, path in (('--save-downloads', parsed.save_downloads),
                      ('--destination', parsed.destination)):
        if path is None:
            continue
        elif not os.path.isdir(path):
            logger.error('argument "%s" to %s does not exist', path, arg)
            sys.exit(2)
        elif not os.access(path, os.W_OK | os.X_OK):
            logger.error('argument "%s" to %s is not writable', path, arg)
            sys.exit(2)

    if parsed.shortname == 'steam':
        run_steam_meta_mode(parsed, games)
        return
    elif parsed.shortname == 'gog':
        run_gog_meta_mode(parsed, games)
        return
    elif parsed.shortname in games:
        game = games[parsed.shortname]
    else:
        parsed.package = parsed.shortname
        for game in games.values():
            if parsed.shortname in game.packages:
                break
            if parsed.shortname in game.aliases:
                break
        else:
            raise AssertionError('could not find %s' % parsed.shortname)

    with game.construct_task() as task:
        if sys.stderr.isatty():
            task.progress_factory = TerminalProgress

        task.run_command_line(parsed)

if __name__ == '__main__':
    run_command_line()
