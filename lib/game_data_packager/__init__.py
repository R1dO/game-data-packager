#!/usr/bin/python3
# vim:set fenc=utf-8:
#
# Copyright © 2014-2015 Simon McVittie <smcv@debian.org>
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

"""Prototype for a more data-driven game-data-packager implementation.
"""

import argparse
import glob
import hashlib
import importlib
import io
import logging
import os
import random
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile

from debian.deb822 import Deb822
import yaml

from .paths import DATADIR, ETCDIR
from .util import TemporaryUmask, mkdir_p, rm_rf, human_size, MEBIBYTE
from .version import GAME_PACKAGE_VERSION

logging.basicConfig()
logger = logging.getLogger('game-data-packager')

# For now, we're given these by the shell script wrapper.

if os.environ.get('DEBUG'):
    logging.getLogger().setLevel(logging.DEBUG)
else:
    logging.getLogger().setLevel(logging.INFO)

# arbitrary cutoff for providing progress bars
QUITE_LARGE = 50 * MEBIBYTE

MD5SUM_DIVIDER = re.compile(r' [ *]?')

class HashedFile(object):
    def __init__(self, name):
        self.name = name
        self.md5 = None
        self.sha1 = None
        self.sha256 = None
        self.skip_hash_matching = False

    @classmethod
    def from_file(cls, name, f, write_to=None, size=None, progress=False):
        md5 = hashlib.new('md5')
        sha1 = hashlib.new('sha1')
        sha256 = hashlib.new('sha256')
        done = 0

        if progress and sys.stderr.isatty():
            pad = [' ']
            def update_progress(s):
                if len(pad[0]) <= len(s):
                    pad[0] = ' ' * len(s)
                print(' %s \r %s\r' % (pad[0], s), end='', file=sys.stderr)
        else:
            update_progress = lambda s: None

        while True:
            if size is None:
                update_progress(human_size(done))
            else:
                update_progress('%.0f%% %s/%s' % (
                            100 * done / size,
                            human_size(done),
                            human_size(size)))

            blob = f.read(io.DEFAULT_BUFFER_SIZE)
            if not blob:
                update_progress('')
                break

            done += len(blob)

            md5.update(blob)
            sha1.update(blob)
            sha256.update(blob)
            if write_to is not None:
                write_to.write(blob)

        self = cls(name)
        self.md5 = md5.hexdigest()
        self.sha1 = sha1.hexdigest()
        self.sha256 = sha256.hexdigest()
        return self

    @property
    def have_hashes(self):
        return ((self.md5 is not None) or
                (self.sha1 is not None) or
                (self.sha256 is not None))

    def matches(self, other):
        matched = False

        if self.skip_hash_matching or other.skip_hash_matching:
            return False

        if None not in (self.md5, other.md5):
            matched = True
            if self.md5 != other.md5:
                return False

        if None not in (self.sha1, other.sha1):
            matched = True
            if self.sha1 != other.sha1:
                return False

        if None not in (self.sha256, other.sha256):
            matched = True
            if self.sha256 != other.sha256:
                return False

        if not matched:
            raise ValueError(('Unable to determine whether checksums match:\n' +
                        '%s has:\n' +
                        '  md5:    %s\n' +
                        '  sha1:   %s\n' +
                        '  sha256: %s\n' +
                        '%s has:\n' +
                        '  md5:    %s\n' +
                        '  sha1:   %s\n' +
                        '  sha256: %s\n') % (
                        self.name,
                        self.md5,
                        self.sha1,
                        self.sha256,
                        other.name,
                        other.md5,
                        other.sha1,
                        other.sha256))

        return True

class WantedFile(HashedFile):
    def __init__(self, name):
        super(WantedFile, self).__init__(name)
        self.alternatives = []
        self.distinctive_name = True
        self.distinctive_size = False
        self.download = None
        self.install_as = name
        self.install_to = None
        self._look_for = []
        self.optional = False
        self._provides = set()
        self._size = None
        self.unpack = None

    @property
    def look_for(self):
        if self.alternatives:
            return set([])
        if not self._look_for:
            self._look_for = set([self.name.lower()])
        return self._look_for
    @look_for.setter
    def look_for(self, value):
        self._look_for = set(x.lower() for x in value)

    @property
    def size(self):
        return self._size
    @size.setter
    def size(self, value):
        self._size = int(value)

    @property
    def provides(self):
        return self._provides
    @provides.setter
    def provides(self, value):
        self._provides = set(value)

    def to_yaml(self):
        return {
            'alternatives': self.alternatives,
            'distinctive_name': self.distinctive_name,
            'distinctive_size': self.distinctive_size,
            'download': self.download,
            'install_as': self.install_as,
            'install_to': self.install_to,
            'look_for': list(self.look_for),
            'name': self.name,
            'optional': self.optional,
            'provides': list(self.provides),
            'size': self.size,
            'skip_hash_matching': self.skip_hash_matching,
            'unpack': self.unpack,
        }

class GameDataPackage(object):
    def __init__(self, name):
        # The name of the binary package
        self.name = name

        # The optional marketing name of this version
        self.longname = None

        # Where we install files.
        # For instance, if this is 'usr/share/games/quake3' and we have
        # a WantedFile with install_as='baseq3/pak1.pk3' then we would
        # put 'usr/share/games/quake3/baseq3/pak1.pk3' in the .deb.
        # The default is 'usr/share/games/' plus the binary package's name.
        self.install_to = 'usr/share/games/' + name

        # symlink => real file (the opposite way round that debhelper does it,
        # because the links must be unique but the real files are not
        # necessarily)
        self.symlinks = {}

        # Steam ID and path
        self.steam = {}

        # set of names of WantedFile instances to be installed
        self._install = set()

        # type of package: full, demo or expansion
        # full packages include quake-registered, quake2-full-data, quake3-data
        # demo packages include quake-shareware, quake2-demo-data
        # expansion packages include quake-armagon, quake-music, quake2-rogue
        self._type = 'full'

        self.version = GAME_PACKAGE_VERSION

    @property
    def install(self):
        return self._install
    @install.setter
    def install(self, value):
        self._install = set(value)

    @property
    def type(self):
        return self._type
    @type.setter
    def type(self, value):
        assert value in ('full', 'demo', 'expansion'), value
        self._type = value

    def to_yaml(self):
        return {
            'install': sorted(self.install),
            'install_to': self.install_to,
            'name': self.name,
            'steam': self.steam,
            'symlinks': self.symlinks,
        }

class GameData(object):
    def __init__(self,
            shortname,
            yaml_data,
            workdir=None):
        # The name of the game for command-line purposes, e.g. quake3
        self.shortname = shortname

        # The formal name of the game, e.g. Quake III Arena
        self.longname = shortname

        # A temporary directory.
        self.workdir = workdir

        # Clean up these directories on exit.
        self._cleanup_dirs = set()

        # binary package name => GameDataPackage
        self.packages = {}

        # If true, we may compress the .deb. If false, don't.
        self.compress_deb = True

        self.help_text = ''

        # Extra directories where we might find game files
        self.try_repack_from = []

        # Steam ID and path
        self.steam = {}

        self.yaml = yaml_data

        self.argument_parser = None

        if 'longname' in self.yaml:
            self.longname = self.yaml['longname']

        if 'try_repack_from' in self.yaml:
            paths = self.yaml['try_repack_from']
            if isinstance(paths, list):
                self.try_repack_from = paths
            elif isinstance(paths, str):
                self.try_repack_from = [paths]
            else:
                raise AssertionError('try_repack_from should be str or list')

        if 'package' in self.yaml:
            package = self.construct_package(self.yaml['package'])
            self.packages[self.yaml['package']] = package
            assert 'packages' not in self.yaml
        else:
            assert self.yaml['packages']
            assert 'install_files' not in self.yaml

            # these do not make sense at top level if there is more than
            # one package
            assert 'symlinks' not in self.yaml
            assert 'install_files_from_cksums' not in self.yaml

        # Map from WantedFile name to instance.
        # { 'baseq3/pak1.pk3': WantedFile instance }
        self.files = {}

        # Map from WantedFile name to a set of names of WantedFile instances
        # from which the file named in the key can be extracted or generated.
        # { 'baseq3/pak1.pk3': set(['linuxq3apoint-1.32b-3.x86.run']) }
        self.providers = {}

        # Map from WantedFile name to the absolute or relative path of
        # a matching file on disk.
        # { 'baseq3/pak1.pk3': '/usr/share/games/quake3/baseq3/pak1.pk3' }
        self.found = {}

        # Map from WantedFile look_for name to a set of names of WantedFile
        # instances which might be it
        # { 'doom2.wad': set(['doom2.wad_1.9', 'doom2.wad_bfg', ...]) }
        self.known_filenames = {}

        # Map from WantedFile size to a set of names of WantedFile
        # instances which might be it
        # { 14604584: set(['doom2.wad_1.9']) }
        self.known_sizes = {}

        # Maps from md5, sha1, sha256 to the name of a unique
        # WantedFile instance
        # { '25e1459...': 'doom2.wad_1.9' }
        self.known_md5s = {}
        self.known_sha1s = {}
        self.known_sha256s = {}

        # Failed downloads
        self.download_failed = set()

        self._populate_files(self.yaml.get('files'))
        self._populate_files(self.yaml.get('install_files'), install=True)

        if 'package' in self.yaml:
            self._populate_package(next(iter(self.packages.values())),
                    self.yaml)

        if 'packages' in self.yaml:
            for binary, data in self.yaml['packages'].items():
                # these should only be at top level, since they are global
                assert 'md5sums' not in data, binary
                assert 'sha1sums' not in data, binary
                assert 'sha256sums' not in data, binary

                package = self.construct_package(binary)
                self.packages[binary] = package
                self._populate_package(package, data)

        for alg in ('md5', 'sha1', 'sha256'):
            if alg + 'sums' in self.yaml:
                for line in self.yaml[alg + 'sums'].splitlines():
                    stripped = line.strip()
                    if stripped == '' or stripped.startswith('#'):
                        continue

                    hexdigest, filename = MD5SUM_DIVIDER.split(line, 1)
                    f = self._ensure_file(filename)
                    already = getattr(f, alg)
                    assert (already == hexdigest or already is None), (alg, already, hexdigest)
                    setattr(f, alg, hexdigest)

        for filename, f in self.files.items():
            for provided in f.provides:
                self.providers.setdefault(provided, set()).add(filename)

            if f.alternatives:
                continue

            if f.distinctive_size and f.size is not None:
                self.known_sizes.setdefault(f.size, set()).add(filename)

            if f.distinctive_name:
                for lf in f.look_for:
                    self.known_filenames.setdefault(lf, set()).add(filename)

            if f.md5 is not None:
                if self.known_md5s.get(f.md5):
                    logger.warning('md5 %s matches %s and also %s' %
                            (f.md5, self.known_md5s[f.md5], filename))
                self.known_md5s[f.md5] = filename

            if f.sha1 is not None:
                if self.known_sha1s.get(f.sha1):
                    logger.warning('sha1 %s matches %s and also %s' %
                            (f.sha1, self.known_sha1s[f.sha1], filename))
                self.known_sha1s[f.sha1] = filename

            if f.sha256 is not None:
                if self.known_sha256s.get(f.sha256):
                    logger.warning('sha256 %s matches %s and also %s' %
                            (f.sha256, self.known_sha256s[f.sha256], filename))
                self.known_sha256s[f.sha256] = filename

        if 'compress_deb' in self.yaml:
            self.compress_deb = self.yaml['compress_deb']

        if 'help_text' in self.yaml:
            self.help_text = self.yaml['help_text']

        if 'steam' in self.yaml:
            self.steam = self.yaml['steam']

        # consistency check
        for package in self.packages.values():
            # there had better be something it wants to install
            assert package.install, package.name
            for installable in package.install:
                assert installable in self.files, installable

        for filename, wanted in self.files.items():
            if wanted.unpack:
                assert 'format' in wanted.unpack, filename
                if wanted.unpack['format'] == 'lha':
                    # for this unpacker we have to know what to pull out
                    assert wanted.unpack['unpack'], filename

            if wanted.alternatives:
                for alt in wanted.alternatives:
                    assert alt in self.files, alt

                # if this is a placeholder for a bunch of alternatives, then
                # it doesn't make sense for it to have a defined checksum
                # or size
                assert wanted.md5 is None
                assert wanted.sha1 is None
                assert wanted.sha256 is None
                assert wanted.size is None

    def __enter__(self):
        return self

    def __exit__(self, *ignored):
        for d in self._cleanup_dirs:
            shutil.rmtree(d, onerror=lambda func, path, ei:
                logger.warning('error removing "%s":' % path, exc_info=ei))
        self._cleanup_dirs = set()

    def __del__(self):
        self.__exit__()

    def get_workdir(self):
        if self.workdir is None:
            self.workdir = tempfile.mkdtemp(prefix='gdptmp.')
            self._cleanup_dirs.add(self.workdir)
        return self.workdir

    def to_yaml(self):
        files = {}
        providers = {}
        packages = {}
        known_filenames = {}
        known_sizes = {}

        for filename, f in self.files.items():
            files[filename] = f.to_yaml()

        for provided, by in self.providers.items():
            providers[provided] = list(by)

        for size, known in self.known_sizes.items():
            known_sizes[size] = list(known)

        for filename, known in self.known_filenames.items():
            known_filenames[filename] = list(known)

        for name, package in self.packages.items():
            packages[name] = package.to_yaml()

        return {
            'help_text': self.help_text,
            'known_filenames': known_filenames,
            'known_md5s': self.known_md5s,
            'known_sha1s': self.known_sha1s,
            'known_sha256s': self.known_sha256s,
            'known_sizes': known_sizes,
            'packages': packages,
            'providers': providers,
            'files': files,
        }

    def _populate_package(self, package, d):
        if 'type' in d:
            package.type = d['type']

        if 'longname' in d:
            package.longname = d['longname']

        if 'symlinks' in d:
            package.symlinks = d['symlinks']

        if 'install_to' in d:
            package.install_to = d['install_to']

        if 'steam' in d:
            package.steam = d['steam']

        if 'install' in d:
            for filename in d['install']:
                f = self._ensure_file(filename)
                package.install.add(filename)

        if 'install_files_from_cksums' in d:
            for line in d['install_files_from_cksums'].splitlines():
                stripped = line.strip()
                if stripped == '' or stripped.startswith('#'):
                    continue

                _, size, filename = line.split(None, 2)
                f = self._ensure_file(filename)
                size = int(size)
                assert (f.size == size or f.size is None), (f.size, size)
                f.size = size
                package.install.add(filename)

        self._populate_files(d.get('install_files'), install=True,
                install_package=package)

    def _populate_files(self, d, install=False, install_package=None,
            **kwargs):
        if d is None:
            return

        if install and install_package is None:
            assert len(self.packages) == 1
            install_package = next(iter(self.packages.values()))

        for filename, data in d.items():
            if data.get('install', install):
                if install_package is None:
                    assert len(self.packages) == 1
                    install_package = next(iter(self.packages.values()))
                install_package.install.add(filename)

            f = self._ensure_file(filename)

            for k in kwargs:
                setattr(f, k, kwargs[k])

            for k in (
                    'alternatives',
                    'distinctive_name',
                    'distinctive_size',
                    'download',
                    'install_as',
                    'install_to',
                    'look_for',
                    'md5',
                    'optional',
                    'provides',
                    'sha1',
                    'sha256',
                    'size',
                    'skip_hash_matching',
                    'unpack',
                    ):
                if k in data:
                    setattr(f, k, data[k])

    def _ensure_file(self, name):
        if name not in self.files:
            self.files[name] = WantedFile(name)

        return self.files[name]

    def use_file(self, wanted, path, hashes=None, log=True):
        logger.debug('found possible %s at %s', wanted.name, path)
        size = os.stat(path).st_size
        if wanted.size is not None and wanted.size != size:
            if log:
                logger.warning('found possible %s\n' +
                        'but its size does not match:\n' +
                        '  file: %s\n' +
                        '  expected: %d bytes\n' +
                        '  found   : %d bytes',
                        wanted.name,
                        path,
                        wanted.size,
                        size)
            return False

        if hashes is None:
            if size > QUITE_LARGE:
                logger.info('checking %s', path)
            hashes = HashedFile.from_file(path, open(path, 'rb'), size=size,
                    progress=(size > QUITE_LARGE))

        if not wanted.skip_hash_matching and not hashes.matches(wanted):
            if log:
                logger.warning('found possible %s\n' +
                    'but its checksums do not match:\n' +
                    '  file: %s\n' +
                    '  expected:\n' +
                    '    md5:    %s\n' +
                    '    sha1:   %s\n' +
                    '    sha256: %s\n' +
                    '  got:\n' +
                    '    md5:    %s\n' +
                    '    sha1:   %s\n' +
                    '    sha256: %s',
                    wanted.name,
                    path,
                    wanted.md5,
                    wanted.sha1,
                    wanted.sha256,
                    hashes.md5,
                    hashes.sha1,
                    hashes.sha256)
            return False

        logger.debug('... yes, looks good')
        self.found[wanted.name] = path
        return True

    def _ensure_hashes(self, hashes, path, size):
        if hashes is not None:
            return hashes

        if size > QUITE_LARGE:
            logger.info('identifying %s', path)
        return HashedFile.from_file(path, open(path, 'rb'), size=size,
                progress=(size > QUITE_LARGE))

    def consider_file(self, path, really_should_match_something):
        if not os.path.exists(path):
            # dangling symlink
            return

        tried = set()

        match_path = '/' + path.lower()
        size = os.stat(path).st_size

        # if a file (as opposed to a directory) is specified on the
        # command-line, try harder to match it to something
        if really_should_match_something:
            hashes = self._ensure_hashes(None, path, size)
        else:
            hashes = None

        for look_for, candidates in self.known_filenames.items():
            if match_path.endswith('/' + look_for):
                hashes = self._ensure_hashes(hashes, path, size)
                for wanted_name in candidates:
                    if wanted_name in tried:
                        continue
                    tried.add(wanted_name)
                    if self.use_file(self.files[wanted_name], path, hashes,
                            log=(len(candidates) == 1)):
                        return
                else:
                    if len(candidates) > 1:
                        self._log_not_any_of(path, size, hashes,
                                'possible "%s"' % look_for,
                                [self.files[c] for c in candidates])

        if size in self.known_sizes:
            hashes = self._ensure_hashes(hashes, path, size)
            candidates = self.known_sizes[size]
            for wanted_name in candidates:
                if wanted_name in tried:
                    continue
                tried.add(wanted_name)
                if self.use_file(self.files[wanted_name], path, hashes,
                        log=(len(candidates) == 1)):
                    return
                else:
                    if len(candidates) > 1:
                        self._log_not_any_of(path, size, hashes,
                                'file of size %d' % size,
                                [self.files[c] for c in candidates])

        if hashes is not None:
            for wanted_name in (self.known_md5s.get(hashes.md5),
                    self.known_sha1s.get(hashes.sha1),
                    self.known_sha256s.get(hashes.sha256)):
                if wanted_name is not None and wanted_name not in tried:
                    tried.add(wanted_name)
                    if self.use_file(self.files[wanted_name], path, hashes):
                        return

        if really_should_match_something:
            logger.warning('file "%s" does not match any known file', path)

    def _log_not_any_of(self, path, size, hashes, why, candidates):
        message = ('found %s but it is not one of the expected ' +
                'versions:\n' +
                '    file:   %s\n' +
                '    size:   %d bytes\n' +
                '    md5:    %s\n' +
                '    sha1:   %s\n' +
                '    sha256: %s\n' +
                'expected one of:\n')
        args = (why, path, size, hashes.md5, hashes.sha1, hashes.sha256)

        for candidate in candidates:
            message = message + ('  %s:\n' +
                    '    size:   ' + (
                        '%s' if candidate.size is None else '%d bytes') +
                    '\n' +
                    '    md5:    %s\n' +
                    '    sha1:   %s\n' +
                    '    sha256: %s\n')
            args = args + (candidate.name, candidate.size, candidate.md5,
                    candidate.sha1, candidate.sha256)

        logger.warning(message, *args)


    def consider_file_or_dir(self, path):
        if os.path.isfile(path):
            self.consider_file(path, True)
        elif os.path.isdir(path):
            for dirpath, dirnames, filenames in os.walk(path):
                for fn in filenames:
                    self.consider_file(os.path.join(dirpath, fn), False)
        else:
            logger.warning('file "%s" does not exist or is not a file or ' +
                    'directory', path)

    def fill_gaps(self, package, download=False, log=True):
        assert package is not None

        logger.debug('trying to fill any gaps for %s', package.name)

        possible = True

        for filename in package.install:
            if filename not in self.found:
                wanted = self.files[filename]

                for alt in wanted.alternatives:
                    if alt in self.found:
                        break
                else:
                    logger.debug('gap needs to be filled for %s: %s',
                            package.name, filename)

        for filename in package.install:
            if filename not in self.found:
                wanted = self.files[filename]

                for alt in wanted.alternatives:
                    if alt in self.found:
                        break
                else:
                    if not self.fill_gap(wanted, download=download, log=log):
                        possible = False

        return possible

    def consider_zip(self, name, zf, provider):
        should_provide = set(provider.provides)

        for entry in zf.infolist():
            if not entry.file_size:
                continue

            for filename in provider.provides:
                wanted = self.files.get(filename)

                if wanted is None:
                    continue

                if wanted.alternatives:
                    continue

                if wanted.size is not None and wanted.size != entry.file_size:
                    continue

                match_path = '/' + entry.filename.lower()

                for lf in wanted.look_for:
                    if match_path.endswith('/' + lf):
                        should_provide.discard(filename)

                        if filename in self.found:
                            continue

                        entryfile = zf.open(entry)

                        tmp = os.path.join(self.get_workdir(),
                                'tmp', wanted.name)
                        tmpdir = os.path.dirname(tmp)
                        mkdir_p(tmpdir)

                        wf = open(tmp, 'wb')
                        if entry.file_size > QUITE_LARGE:
                            logger.info('extracting %s from %s', entry.filename, name)
                        else:
                            logger.debug('extracting %s from %s', entry.filename, name)
                        hf = HashedFile.from_file(
                                name + '//' + entry.filename, entryfile, wf,
                                size=entry.file_size,
                                progress=(entry.file_size > QUITE_LARGE))
                        wf.close()

                        if not self.use_file(wanted, tmp, hf):
                            os.remove(tmp)

        if should_provide:
            for missing in sorted(should_provide):
                logger.error('%s should have provided %s but did not',
                        name, missing)

    def consider_tar_stream(self, name, tar, provider):
        should_provide = set(provider.provides)

        for entry in tar:
            if not entry.isfile():
                continue

            for filename in provider.provides:
                wanted = self.files.get(filename)

                if wanted is None:
                    continue

                if wanted.alternatives:
                    continue

                if wanted.size is not None and wanted.size != entry.size:
                    continue

                match_path = '/' + entry.name.lower()

                for lf in wanted.look_for:
                    if match_path.endswith('/' + lf):
                        should_provide.discard(filename)

                        if filename in self.found:
                            continue

                        entryfile = tar.extractfile(entry)

                        tmp = os.path.join(self.get_workdir(),
                                'tmp', wanted.name)
                        tmpdir = os.path.dirname(tmp)
                        mkdir_p(tmpdir)

                        wf = open(tmp, 'wb')
                        if entry.size > QUITE_LARGE:
                            logger.info('extracting %s from %s', entry.name, name)
                        else:
                            logger.debug('extracting %s from %s', entry.name, name)
                        hf = HashedFile.from_file(
                                name + '//' + entry.name, entryfile, wf,
                                size=entry.size,
                                progress=(entry.size > QUITE_LARGE))
                        wf.close()

                        if not self.use_file(wanted, tmp, hf):
                            os.remove(tmp)

        if should_provide:
            for missing in sorted(should_provide):
                logger.error('%s should have provided %s but did not',
                        name, missing)

    def choose_mirror(self, wanted):
        mirrors = []
        if type(wanted.download) is str:
            return [wanted.download]
        for mirror_list, details in wanted.download.items():
            try:
                f = open(os.path.join(ETCDIR, mirror_list))
                for line in f:
                    url = line.strip()
                    if not url:
                        continue
                    if url.startswith('#'):
                        continue
                    if details.get('path', '.') != '.':
                        if not url.endswith('/'):
                            url = url + '/'
                        url = url + details['path']
                    if not url.endswith('/'):
                        url = url + '/'
                    url = url + details.get('name', wanted.name)
                    mirrors.append(url)
            except:
                logger.warning('Could not open mirror list "%s"', mirror_list,
                        exc_info=True)
        if not mirrors:
            logger.error('Could not select a mirror for "%s"', wanted.name)
            return []
        random.shuffle(mirrors)
        return mirrors

    def fill_gap(self, wanted, download=False, log=True):
        """Try to unpack, download or otherwise obtain wanted.

        If download is true, we may attempt to download wanted or a
        file that will provide it.

        Return True if either we have the wanted file, or download is False
        but we think we can get it by downloading.
        """
        if wanted.name in self.found:
            return True

        logger.debug('could not find %s, trying to derive it...', wanted.name)

        if wanted.alternatives:
            for alt in wanted.alternatives:
                if alt in self.found:
                    return True
                elif self.fill_gap(self.files[alt], download=download,
                        log=False):
                    return True

            if log:
                logger.error('could not find a suitable version of %s:',
                        wanted.name)

                for alt in wanted.alternatives:
                    alt = self.files[alt]
                    logger.error('%s:\n' +
                            '  expected:\n' +
                            '    size:   ' + (
                                '%s' if alt.size is None else '%d bytes') +
                            '\n' +
                            '    md5:    %s\n' +
                            '    sha1:   %s\n' +
                            '    sha256: %s',
                            alt.name,
                            alt.size,
                            alt.md5,
                            alt.sha1,
                            alt.sha256)

            return False

        # no alternatives: try getting the file itself

        possible = False

        if wanted.download:
            if download:
                logger.debug('trying to download %s...', wanted.name)
                urls = self.choose_mirror(wanted)
                for url in urls:
                    if url in self.download_failed:
                        logger.debug('... no, it already failed')
                        continue

                    logger.debug('... %s', url)
                    tmp = None

                    try:
                        rf = urllib.request.urlopen(url)
                        if rf is None:
                            continue

                        tmp = os.path.join(self.get_workdir(),
                                'tmp', wanted.name)
                        tmpdir = os.path.dirname(tmp)
                        mkdir_p(tmpdir)
                        wf = open(tmp, 'wb')
                        logger.info('downloading %s', url)
                        hf = HashedFile.from_file(url, rf, wf,
                                size=wanted.size, progress=True)
                        wf.close()

                        if self.use_file(wanted, tmp, hf):
                            assert self.found[wanted.name] == tmp
                            return True
                        else:
                            os.remove(tmp)
                    except Exception as e:
                        logger.warning('Failed to download "%s": %s', url,
                                e)
                        self.download_failed.add(url)
                        if tmp is not None:
                            os.remove(tmp)
            else:
                # We can easily get it, but see whether we can unpack it
                # from files available locally
                possible = True

        for provider_name in self.providers.get(wanted.name, ()):
            provider = self.files[provider_name]

            # recurse to unpack or (see whether we can) download the provider
            providable = self.fill_gap(provider, download=download, log=log)

            if provider_name in self.found:
                possible = True
                found_name = self.found[provider_name]
                logger.debug('trying provider %s found at %s',
                        provider_name, found_name)
                fmt = provider.unpack['format']

                if fmt == 'dos2unix':
                    tmp = os.path.join(self.get_workdir(),
                            'tmp', wanted.name)
                    tmpdir = os.path.dirname(tmp)
                    mkdir_p(tmpdir)

                    rf = open(found_name, 'rb')
                    contents = rf.read()
                    wf = open(tmp, 'wb')
                    wf.write(contents.replace(b'\r\n', b'\n'))

                    self.use_file(wanted, tmp, None)
                elif fmt in ('tar.gz', 'tar.bz2', 'tar.xz'):
                    rf = open(found_name, 'rb')
                    if 'skip' in provider.unpack:
                        skipped = rf.read(provider.unpack['skip'])
                        assert len(skipped) == provider.unpack['skip']
                    with tarfile.open(
                            found_name,
                            mode='r|' + fmt[4:],
                            fileobj=rf) as tar:
                        self.consider_tar_stream(found_name, tar, provider)
                elif fmt == 'zip':
                    with zipfile.ZipFile(found_name, 'r') as zf:
                        self.consider_zip(found_name, zf, provider)
                elif fmt == 'lha':
                    logger.debug('Extracting %r from %s',
                            provider.unpack['unpack'], found_name)
                    tmpdir = os.path.join(self.get_workdir(), 'tmp',
                            provider_name + '.d')
                    mkdir_p(tmpdir)
                    subprocess.check_call(['lha', 'xq',
                                os.path.abspath(found_name)] +
                            provider.unpack['unpack'],
                            cwd=tmpdir)
                    for f in provider.unpack['unpack']:
                        self.consider_file(os.path.join(tmpdir, f), True)

            elif providable:
                # we don't have it, but we can get it
                possible = True
            # else impossible, but try next provider

        if not possible:
            if log:
                logger.error('could not find %s:\n' +
                        '  expected:\n' +
                        '    size:   ' + (
                            '%s' if wanted.size is None else '%d bytes') +
                        '\n' +
                        '    md5:    %s\n' +
                        '    sha1:   %s\n' +
                        '    sha256: %s',
                        wanted.name,
                        wanted.size,
                        wanted.md5,
                        wanted.sha1,
                        wanted.sha256)

            return False

        return True

    def check_complete(self, package, log=False):
        # Got everything?
        complete = True
        for filename in package.install:
            if filename in self.found:
                continue

            wanted = self.files[filename]

            for alt in wanted.alternatives:
                if alt in self.found:
                    break
            else:
                complete = False
                if log:
                    logger.error('could not find %s:\n' +
                            '  expected:\n' +
                            '    size:   ' + (
                                '%s' if wanted.size is None else '%d bytes') +
                            '\n' +
                            '    md5:    %s\n' +
                            '    sha1:   %s\n' +
                            '    sha256: %s',
                            wanted.name,
                            wanted.size,
                            wanted.md5,
                            wanted.sha1,
                            wanted.sha256)

        return complete

    def fill_docs(self, package, docdir):
        shutil.copyfile(os.path.join(DATADIR, package.name + '.copyright'),
                os.path.join(docdir, 'copyright'))

    def fill_extra_files(self, package, destdir):
        pass

    def fill_dest_dir(self, package, destdir):
        if not self.check_complete(package, log=True):
            return False

        docdir = os.path.join(destdir, 'usr/share/doc', package.name)
        mkdir_p(docdir)
        shutil.copyfile(os.path.join(DATADIR, 'changelog.gz'),
                os.path.join(docdir, 'changelog.gz'))

        self.fill_docs(package, docdir)

        debdir = os.path.join(destdir, 'DEBIAN')
        mkdir_p(debdir)

        self.fill_extra_files(package, destdir)

        for ms in ('preinst', 'postinst', 'prerm', 'postrm'):
            maintscript = os.path.join(DATADIR, package.name + '.' + ms)
            if os.path.isfile(maintscript):
                shutil.copy(maintscript, os.path.join(debdir, ms))

        for filename in package.install:
            wanted = self.files[filename]

            if filename in self.found:
                copy_from = self.found[filename]
            else:
                for alt in wanted.alternatives:
                    if alt in self.found:
                        copy_from = self.found[alt]
                        break
                else:
                    raise AssertionError('we already checked that %s exists' %
                            (filename))

            # cp it into place
            with TemporaryUmask(0o22):
                logger.debug('Found %s at %s', wanted.name, copy_from)
                copy_to = os.path.join(destdir,
                        (wanted.install_to if wanted.install_to is not None
                            else package.install_to),
                        wanted.install_as)
                copy_to_dir = os.path.dirname(copy_to)
                logger.debug('Copying to %s', copy_to)
                if not os.path.isdir(copy_to_dir):
                    mkdir_p(copy_to_dir)
                # Use cp(1) so we can make a reflink if source and
                # destination happen to be the same btrfs volume
                subprocess.check_call(['cp', '--reflink=auto', copy_from,
                    copy_to])

        for symlink, real_file in package.symlinks.items():
            symlink = symlink.lstrip('/')
            real_file = real_file.lstrip('/')

            toplevel, rest = symlink.split('/', 1)
            if real_file.startswith(toplevel + '/'):
                symlink_dirs = symlink.split('/')
                real_file_dirs = real_file.split('/')

                while (len(symlink_dirs) > 0 and len(real_file_dirs) > 0 and
                        symlink_dirs[0] == real_file_dirs[0]):
                    symlink_dirs.pop(0)
                    real_file_dirs.pop(0)

                if len(symlink_dirs) == 0:
                    raise ValueError('Cannot create a symlink to itself')

                target = ('../' * (len(symlink_dirs) - 1)) + '/'.join(real_file_dirs)
            else:
                target = '/' + real_file

            mkdir_p(os.path.dirname(os.path.join(destdir, symlink)))
            os.symlink(target, os.path.join(destdir, symlink))

        # adapted from dh_md5sums
        subprocess.check_call("find . -type f ! -regex '\./DEBIAN/.*' " +
                "-printf '%P\\0' | LC_ALL=C sort -z | " +
                "xargs -r0 md5sum > DEBIAN/md5sums",
                shell=True, cwd=destdir)
        os.chmod(os.path.join(destdir, 'DEBIAN/md5sums'), 0o644)

        control_in = open(self.get_control_template(package))
        control = Deb822(control_in)
        self.modify_control_template(control, package, destdir)
        control.dump(fd=open(os.path.join(debdir, 'control'), 'wb'),
                encoding='utf-8')
        os.chmod(os.path.join(debdir, 'control'), 0o644)

        for dirpath, dirnames, filenames in os.walk(destdir):
            for fn in filenames + dirnames:
                full = os.path.join(dirpath, fn)
                stat_res = os.lstat(full)
                if stat.S_ISLNK(stat_res.st_mode):
                    continue
                elif (stat.S_ISDIR(stat_res.st_mode) or
                        (stat.S_IMODE(stat_res.st_mode) & 0o111) != 0):
                    # make directories and executable files rwxr-xr-x
                    os.chmod(full, 0o755)
                else:
                    # make other files rw-r--r--
                    os.chmod(full, 0o644)

        return True

    def modify_control_template(self, control, package, destdir):
        size = subprocess.check_output(['du', '-sk', '--exclude=./DEBIAN',
            '.'], cwd=destdir).decode('utf-8').rstrip('\n')
        assert control['Package'] in ('PACKAGE', package.name)
        control['Package'] = package.name
        control['Installed-Size'] = size
        package.version = control['Version'].replace('VERSION',
                GAME_PACKAGE_VERSION)
        control['Version'] = package.version

    def get_control_template(self, package):
        return os.path.join(DATADIR, package.name + '.control.in')

    def add_parser(self, parsers):
        parser = parsers.add_parser(self.shortname,
                help=self.longname, aliases=self.packages.keys(),
                description=self.help_text,
                formatter_class=argparse.RawDescriptionHelpFormatter)
        parser.add_argument('paths', nargs='*',
                metavar='DIRECTORY|FILE',
                help='Files to use in constructing the .deb')

        # There is only a --demo option if at least one package is a demo
        parser.set_defaults(demo=False)
        for package in self.packages.values():
            if package.type == 'demo':
                parser.add_argument('--demo', action='store_true',
                        default=False,
                        help='Build demo package even if files for full '
                            + 'version are available')
                break

        self.argument_parser = parser
        return parser

    def run_command_line(self, args):
        logger.debug('package description:\n%s',
                yaml.safe_dump(self.to_yaml()))

        self.preserve_debs = (getattr(args, 'destination', None) is not None)
        self.install_debs = getattr(args, 'install', True)

        if getattr(args, 'compress', None) is None:
            # default to not compressing if we aren't going to install it
            # anyway
            args.compress = self.preserve_debs

        # only compress if the command-line says we should and the YAML
        # says it's worthwhile
        self.compress_deb = (self.compress_deb and
                getattr(args, 'compress', True))

        for path in self.try_repack_from:
            if os.path.isdir(path):
                args.paths.append(path)

        for package in self.packages.values():
            path = '/' + package.install_to
            if os.path.isdir(path):
                args.paths.append(path)

        for path in self.iter_steam_paths():
            args.paths.append(path)

        for arg in args.paths:
            logger.debug('%s...', arg)
            self.consider_file_or_dir(arg)

        possible = set()

        for package in self.packages.values():
            if (args.shortname in self.packages and
                    package.name != args.shortname):
                continue

            if self.fill_gaps(package, log=False):
                logger.debug('%s is possible', package.name)
                possible.add(package)
            else:
                logger.debug('%s is impossible', package.name)

        if not possible:
            logger.debug('No packages were possible')
            # Repeat the process for the first (hopefully only)
            # demo/shareware package, so we can log its errors.
            for package in self.packages.values():
                if package.type == 'demo':
                    if self.fill_gaps(package=package, log=True):
                        logger.error('%s unexpectedly succeeded on second ' +
                                'attempt. Please report this as a bug',
                                package.name)
                        possible.add(package)
                    else:
                        self.argument_parser.print_help()
                        raise SystemExit(1)
            else:
                # If no demo, repeat the process for the first
                # (hopefully only) full package, so we can log *its* errors.
                for package in self.packages.values():
                    if package.type == 'full':
                        if self.fill_gaps(package=package, log=True):
                            logger.error('%s unexpectedly succeeded on ' +
                                    'second attempt. Please report this as '
                                    'a bug', package.name)
                            possible.add(package)
                        else:
                            self.argument_parser.print_help()
                            sys.exit(1)
                else:
                    self.argument_parser.print_help()
                    raise SystemExit('Unable to complete any packages. ' +
                            'Please provide more files or directories.')

        ready = set()

        have_full = False
        for package in possible:
            if package.type == 'full':
                have_full = True

        for package in possible:
            if have_full and package.type == 'demo' and not args.demo:
                # no point in packaging the demo if we have the full
                # version
                logger.debug('will not produce %s because we have a full ' +
                        'version', package.name)
                continue

            logger.debug('will produce %s', package.name)
            if self.fill_gaps(package=package, download=True, log=True):
                ready.add(package)
            else:
                logger.error('Failed to download necessary files for %s',
                        package.name)

        if not ready:
            self.argument_parser.print_help()
            raise SystemExit(1)

        debs = set()

        for package in ready:
            destdir = os.path.join(self.get_workdir(),
                    '%s.deb.d' % package.name)
            if not self.fill_dest_dir(package, destdir):
                raise SystemExit(1)

            # it had better have a /usr and a DEBIAN directory or
            # something has gone very wrong
            assert os.path.isdir(os.path.join(destdir, 'usr')), destdir
            assert os.path.isdir(os.path.join(destdir, 'DEBIAN')), destdir

            deb_basename = '%s_%s_all.deb' % (package.name, package.version)

            if args.destination is not None:
                outfile = os.path.join(os.path.abspath(args.destination),
                        deb_basename)
            else:
                outfile = os.path.join(self.get_workdir(), deb_basename)

            if self.compress_deb:
                dpkg_deb_args = []
            else:
                dpkg_deb_args = ['-Znone']

            try:
                subprocess.check_output(['fakeroot', 'dpkg-deb'] +
                        dpkg_deb_args +
                        ['-b', '%s.deb.d' % package.name, outfile],
                        cwd=self.get_workdir())
            except subprocess.CalledProcessError as cpe:
                print(cpe.output)
                raise

            debs.add(outfile)

            rm_rf(destdir)

        rm_rf(os.path.join(self.get_workdir(), 'tmp'))

        if self.preserve_debs:
            for deb in debs:
                print('generated "%s"' % os.path.abspath(deb))

        if self.install_debs:
            print('using su(1) to obtain root privileges and install the package(s)')
            cmd = 'dpkg -i'
            for deb in debs:
                cmd = cmd + ' ' + shlex.quote(deb)

            subprocess.call(['su', '-c', cmd])

    def iter_steam_paths(self):
        for prefix in (
                os.path.expanduser('~/.steam'),
                os.path.join(os.environ.get('XDG_DATA_HOME', os.path.expanduser('~/.local/share')),
                    'wineprefixes/steam/drive_c/Program Files/Steam'),
                os.path.expanduser('~/.wine/drive_c/Program Files/Steam'),
                os.path.expanduser('~/.PlayOnLinux/wineprefix/Steam/drive_c/Program_Files/Steam'),
                ):
            if not os.path.isdir(prefix):
                continue

            path = self.steam.get('path')
            if path is not None:
                for middle in ('steamapps', 'SteamApps'):
                    path = os.path.join(prefix, middle, path)
                    if os.path.isdir(path):
                        logger.debug('possible Steam installation at %s', path)
                        yield path

            for package in self.packages.values():
                path = package.steam.get('path')

                if path is not None:
                    for middle in ('steamapps', 'SteamApps'):
                        path = os.path.join(prefix, middle, path)
                        if os.path.isdir(path):
                            logger.debug('possible Steam installation at %s', path)
                            yield path

    def construct_package(self, binary):
        return GameDataPackage(binary)

def load_yaml_games(workdir=None):
    games = {}

    for yamlfile in glob.glob(os.path.join(DATADIR, '*.yaml')):
        try:
            g = os.path.basename(yamlfile)
            g = g[:len(g) - 5]

            yaml_data = yaml.load(open(yamlfile))

            plugin = yaml_data.get('plugin', g)

            try:
                plugin = importlib.import_module('game_data_packager.games.%s' %
                        plugin)
                game_data_constructor = plugin.GAME_DATA_SUBCLASS
            except (ImportError, AttributeError) as e:
                logger.debug('No special code for %s: %s', g, e)
                game_data_constructor = GameData

            games[g] = game_data_constructor(g, yaml_data, workdir=workdir)
        except:
            print('Error loading %s:\n' % yaml)
            raise

    return games

def run_command_line():
    workdir = os.environ['WORKDIR']
    logger.debug('Arguments: %r', sys.argv)

    parser = argparse.ArgumentParser(prog='game-data-packager',
            description='Package game files.')

    game_parsers = parser.add_subparsers(dest='shortname',
            title='supported games', metavar='GAME')

    games = load_yaml_games(workdir)

    for g in sorted(games.keys()):
        games[g].add_parser(game_parsers)

    # Misc options
    parser.add_argument('-i', '--install', action='store_true',
            help='install the generated package')
    parser.add_argument('-n', '--no-install', action='store_false',
            dest='install',
            help='do not install the generated package (requires -d, default)')
    parser.add_argument('-d', '--destination', metavar='OUTDIR',
            help='write the generated .deb(s) to OUTDIR')
    parser.add_argument('-z', '--compress', action='store_true',
            default=None,
            help='compress generated .deb (default unless -i is used)')
    parser.add_argument('--no-compress', action='store_false',
            dest='compress',
            help='do not compress generated .deb (default with -i)')

    parsed = parser.parse_args()

    if parsed.shortname is None:
        parser.print_help()
        sys.exit(0)

    with games[parsed.shortname] as game:
        parsed = parser.parse_args()
        game.run_command_line(parsed)
