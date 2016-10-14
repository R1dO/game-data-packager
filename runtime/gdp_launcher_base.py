#!/usr/bin/python3
# encoding=utf-8

# game-data-packager command-line launcher stub

# Copyright © 2015-2016 Simon McVittie <smcv@debian.org>
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
import json
import glob
import logging
import os
import shlex
import shutil
import string
import sys
import traceback

from gdp_launcher_version import GAME_PACKAGE_VERSION

if 'GDP_UNINSTALLED' in os.environ:
    RUNTIME_BUILT = './out'
    RUNTIME_SOURCE = './runtime'
else:
    RUNTIME_BUILT = '/usr/share/games/game-data-packager-runtime'
    RUNTIME_SOURCE = '/usr/share/games/game-data-packager-runtime'

# Normalize environment so we can use ${XDG_DATA_HOME} unconditionally.
# Do this before we use GLib functions that might create worker threads,
# because setenv() is not thread-safe.
ORIG_ENVIRON = os.environ.copy()
os.environ.setdefault('XDG_CACHE_HOME', os.path.expanduser('~/.cache'))
os.environ.setdefault('XDG_CONFIG_HOME', os.path.expanduser('~/.config'))
os.environ.setdefault('XDG_CONFIG_DIRS', '/etc/xdg')
os.environ.setdefault('XDG_DATA_HOME', os.path.expanduser('~/.local/share'))
os.environ.setdefault('XDG_DATA_DIRS', '/usr/local/share:/usr/share')

logger = logging.getLogger('game-data-packager.launcher.base')

if os.environ.get('GDP_DEBUG'):
    logger.setLevel(logging.DEBUG)
else:
    logger.setLevel(logging.INFO)

DISTRO = 'the distribution'

try:
    os_release = open('/usr/lib/os-release')
except:
    pass
else:
    for line in os_release:
        if line.startswith('NAME='):
            line = line[5:].strip()
            if line.startswith('"'):
                line = line.strip('"')
            elif line.startswith("'"):
                line = line.strip("'")
            DISTRO = line

def expand(path, **kwargs):
    if path is None:
        return None

    return os.path.expanduser(string.Template(path).substitute(os.environ,
        **kwargs))

class Launcher:
    def __init__(self, argv=None):
        name = os.path.basename(sys.argv[0])

        if name.endswith('.py'):
            name = name[:-3]

        parser = argparse.ArgumentParser(
                description="game-data-packager's game launcher",
                allow_abbrev=False)
        parser.add_argument('--id', default=name,
                help='identity of launched game (default: from argv[0])')
        parser.add_argument('--demo', default=False, action='store_true',
                help='run a demo version even if the full version is available')
        parser.add_argument('--engine', default=None,
                help='use the specified game engine, if supported')
        parser.add_argument('--expansion', default=None,
                help='expansion to launch')
        parser.add_argument('--smp', default=False, action='store_true',
                help='use a multi-threaded game engine, if supported')
        parser.add_argument('--print-backtrace', default=False,
                action='store_true', help='print backtrace on crash')
        parser.add_argument('--debugger', default=None,
                help='run engine under a debugger')
        parser.add_argument('--quiet', '-q', default=False, action='store_true',
                help='silence console logging')
        parser.add_argument('--allow-binary-only', default=False,
                action='store_true',
                help='Allow running binary-only games')
        parser.add_argument('--version', action='version',
                version='game-data-packager launcher ' + GAME_PACKAGE_VERSION)
        parser.add_argument('arguments', nargs=argparse.REMAINDER,
                help='arguments for the launched game')
        self.args, rest = parser.parse_known_args(argv)
        self.args.arguments.extend(rest)

        if self.args.id == 'launcher':
            parser.print_help()
            sys.exit(2)

        self.id = self.args.id
        self.name = self.id
        self.expansion_name = None

        self.set_id()

        self.data = json.load(open('%s/launch-%s.json' % (RUNTIME_BUILT,
            self.id), encoding='utf-8'))

        self.binary_only = self.data.get('binary_only', False)
        logger.debug('Binary-only: %r', self.binary_only)
        self.required_files = self.data['required_files']
        logger.debug('Checked files: %r', sorted(self.required_files))

        self.dot_directory = expand(self.data.get('dot_directory',
                    '${XDG_DATA_HOME}/' + self.id))
        logger.debug('Dot directory: %s', self.dot_directory)

        if 'engine' in self.data:
            self.engines = [self.data['engine']]
        elif 'engines' in self.data:
            self.engines = self.data['engines']
        else:
            self.engines = []

        if self.args.smp:
            if 'smp_engine' in self.data:
                self.engines.insert(0, self.data['smp_engine'])
            else:
                raise SystemExit('This game does not have a separate '
                        'SMP/threaded engine')

        if self.engines and self.args.engine is not None:
            self.engines.insert(0, self.args.engine)

        self.engine = None

        self.base_directories = list(map(expand,
                        self.data.get('base_directories',
                            ['/usr/lib/' + self.id])))
        logger.debug('Base directories: %r', self.base_directories)

        self.library_path = self.data.get('library_path', [])
        logger.debug('Library path: %r', self.library_path)

        self.working_directory = expand(self.data.get('working_directory',
                    None))
        logger.debug('Working directory: %s', self.working_directory)

        self.argv = self.data.get('argv', [])
        if isinstance(self.argv, str):
            self.argv = self.argv.split()

        self.exit_status = 1

        if self.binary_only:
            assert self.dot_directory is not None
            if self.id in ('quake4', 'etqw'):
                self.warning_stamp = os.path.join(self.dot_directory,
                        'confirmed-binary-only')
            else:
                self.warning_stamp = os.path.join(self.dot_directory,
                        'confirmed-binary-only.stamp')
        else:
            self.warning_stamp = None

        self.symlink_into_dot_directory = self.data.get(
                'symlink_into_dot_directory', [])

        for p in self.base_directories:
            logger.debug('Searching: %s' % p)

        # sanity check: game engines often don't cope well with missing data
        self.have_all_data = self.check_required_files(self.base_directories,
            self.required_files)

        if (self.args.demo or not self.have_all_data) and 'demo' in self.data:
            demo_directories = list(map(expand,
                            self.data['demo'].get('base_directories',
                                self.data['base_directories'])))
            if self.check_required_files(demo_directories,
                    self.data['demo'].get('required_files',
                        self.required_files)):
                self.have_all_data = True
                self.base_directories = demo_directories

            if 'argv' in self.data['demo']:
                self.argv = self.data['demo']['argv']
                if isinstance(self.argv, str):
                    self.argv = self.argv.split()
        else:
            # assume expansions only work with non-demo data
            for expansion, data in self.data.get('expansions', {}).items():
                base_directories = list(map(expand, data.get('base_directories',
                    []))) + self.base_directories

                if self.check_required_files(base_directories,
                        data.get('extra_required_files', [])):
                    self.symlink_into_dot_directory = (
                            self.symlink_into_dot_directory +
                            data.get('symlink_into_dot_directory', []))

                aliases = data.get('aliases', [])
                if isinstance(aliases, str):
                    aliases = aliases.split()

                if (self.expansion_name == expansion or
                        self.expansion_name in aliases):
                    extra_argv = data.get('extra_argv', [])
                    if isinstance(extra_argv, str):
                        extra_argv = extra_argv.split()
                    self.argv = self.argv + extra_argv

                    extra_required_files = data.get('extra_required_files', [])
                    if isinstance(extra_required_files, str):
                        extra_required_files = extra_required_files.split()
                    self.required_files = (self.required_files +
                            extra_required_files)

                    self.base_directories = base_directories
                    break

        logger.debug('Arguments: %r', self.argv)

    def set_id(self):
        pass

    def check_required_files(self, base_directories, required_files,
            warn=True):
        for f in required_files:
            f = expand(f)
            logger.debug('looking for %s', f)
            for p in base_directories:
                logger.debug('looking for %s in %s', f, p)
                if os.path.exists(os.path.join(p, f)):
                    logger.debug('found %s in %s', f, p)
                    break
            else:
                if warn:
                    logger.warning('Data file is missing: %s' % f)
                return False
        else:
            return True

    def run_error(self, message):
        logger.error(message)

    def main(self):
        if self.engines:
            for e in self.engines:
                e = expand(e)
                if shutil.which(e) is not None:
                    self.engine = e
                    break
            else:
                self.run_error(
                        '\n'.join(
                            [self.load_text('missing-engine.txt',
                                'Game engine missing, tried:')] +
                            [expand(e) for e in self.engines]))
                sys.exit(72)    # EX_OSFILE

        if self.dot_directory is not None:
            os.makedirs(self.dot_directory, exist_ok=True)

        if not self.have_all_data:
            self.run_error(
                    self.load_text('missing-data.txt', 'Data files missing'))
            sys.exit(72)    # EX_OSFILE

        if (self.binary_only and not os.path.exists(self.warning_stamp) and
                not self.args.allow_binary_only):
            self.exit_status = 77   # EX_NOPERM
            self.run_confirm_binary_only()
            sys.exit(self.exit_status)
            raise AssertionError('not reached')

        try:
            self.exec_game()
        except:
            self.run_error(traceback.format_exc())
            sys.exit(self.exit_status)
        else:
            raise AssertionError('exec_game should never return')

    def flush(self):
        for f in (sys.stdout, sys.stderr):
            f.flush()

    def run_confirm_binary_only(self):
        # don't do anything, we have no GUI
        self.run_error('Not running binary-only game without '
                '--allow-binary-only')

    def exec_game(self, _unused=None):
        self.exit_status = 69   # EX_UNAVAILABLE

        # Copy before linking, so that the copies will suppress symlink
        # creation
        for pattern in self.data.get('copy_into_dot_directory', ()):
            assert self.dot_directory is not None
            # copy from all base directories, highest priority first
            for base in self.base_directories:
                for f in glob.glob(os.path.join(base, pattern)):
                    assert f.startswith(base + '/')
                    target = os.path.join(self.dot_directory,
                            f[len(base) + 1:])
                    d = os.path.dirname(target)

                    if os.path.exists(target):
                        logger.debug('Already exists: %s', target)
                        continue

                    if d:
                        logger.info('Creating directory: %s', d)
                        os.makedirs(d, exist_ok=True)

                    logger.info('Copying %s -> %s', f, target)
                    shutil.copyfile(f, target)

        for subdir in self.symlink_into_dot_directory:
            assert self.dot_directory is not None
            dot_subdir = os.path.join(self.dot_directory, subdir)
            logger.debug('symlinking ${each base directory}/%s/** as %s/**',
                    subdir, dot_subdir)
            # prune dangling symbolic links
            if os.path.exists(dot_subdir):
                logger.debug('checking %r for dangling symlinks',
                        dot_subdir)
                for dirpath, dirnames, filenames in os.walk(dot_subdir):
                    logger.debug('walking: %r %r %r', dirpath, dirnames,
                            filenames)
                    for filename in filenames:
                        logger.debug('checking whether %r is a dangling '
                                'symlink', filename)
                        f = os.path.join(dirpath, filename)

                    if not os.path.exists(f):
                        logger.info('Removing dangling symlink %s', f)
                        os.remove(f)

            # symlink in all base directories, highest priority first
            for base in self.base_directories:
                base_subdir = os.path.join(base, subdir)
                logger.debug('Searching for files to link in %s', base_subdir)
                for dirpath, dirnames, filenames in os.walk(base_subdir):
                    logger.debug('walking: %r %r %r', dirpath, dirnames,
                            filenames)
                    for filename in filenames:
                        logger.debug('ensuring that %s is symlinked in',
                                filename)

                        f = os.path.join(dirpath, filename)
                        logger.debug('%s', f)
                        assert f.startswith(base_subdir + '/')

                        target = os.path.join(dot_subdir,
                                f[len(base_subdir) + 1:])
                        d = os.path.dirname(target)

                        if os.path.exists(target):
                            logger.debug('Already exists: %s', target)
                            continue

                        if os.path.lexists(target):
                            logger.info('Removing dangling symlink %s', target)
                            os.remove(target)

                        if d:
                            logger.info('Creating directory: %s', d)
                            os.makedirs(d, exist_ok=True)

                        logger.info('Symlinking %s -> %s', f, target)
                        os.symlink(f, target)

        if self.working_directory is not None:
            os.chdir(self.working_directory)

        for p in self.base_directories:
            if os.path.isdir(p):
                base_directory = p
                break
        else:
            base_directory = None

        self.argv = [expand(a, base_directory=base_directory)
                for a in self.argv]

        if self.engine is not None:
            self.argv.insert(0, self.engine)

        environ = os.environ.copy()

        library_path = self.library_path[:]

        if 'LD_LIBRARY_PATH' in environ:
            library_path.append(environ['LD_LIBRARY_PATH'])

        environ['LD_LIBRARY_PATH'] = ':'.join(library_path)

        if self.args.print_backtrace:
            self.argv[:0] = ['gdb', '-return-child-result', '-batch',
                    '-ex', 'run', '-ex', 'thread apply all bt full',
                    '-ex', 'kill', '-ex', 'quit', '--args']
        elif self.args.debugger:
            self.argv[:0] = shlex.split(self.args.debugger)

        logger.debug('Executing: %r', self.argv + self.args.arguments)
        self.flush()

        if self.args.quiet:
            os.dup2(os.open(os.devnull, os.O_RDONLY), 0)
            os.dup2(os.open(os.devnull, os.O_WRONLY), 1)
            os.dup2(os.open(os.devnull, os.O_WRONLY), 2)

        os.execvpe(self.argv[0], self.argv + self.args.arguments, environ)

        raise AssertionError('os.execve should never return')

    def load_text(self, filename, placeholder):
        for f in ('%s.%s' % (self.id, filename), filename):
            try:
                path = os.path.join(RUNTIME_SOURCE, f)
                text = open(path).read()
            except OSError:
                pass
            else:
                text = string.Template(text).safe_substitute(
                        distro=DISTRO,
                        name=self.name,
                        )
                # strip single \n
                text = text.replace('\n\n', '\r\r').replace('\n', ' ')
                text = text.replace('\r', '\n')
                return text
        else:
            return placeholder

if __name__ == '__main__':
    logging.basicConfig()
    Launcher().main()
