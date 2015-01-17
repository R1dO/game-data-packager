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

from collections import defaultdict
from enum import Enum
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
from .util import (MEBIBYTE,
        TemporaryUmask,
        mkdir_p,
        rm_rf,
        human_size,
        which)
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

class FillResult(Enum):
    UNDETERMINED = 0
    IMPOSSIBLE = 1
    DOWNLOAD_NEEDED = 2
    COMPLETE = 3

    def __and__(self, other):
        if other is FillResult.UNDETERMINED:
            return self

        if self is FillResult.UNDETERMINED:
            return other

        if other is FillResult.IMPOSSIBLE or self is FillResult.IMPOSSIBLE:
            return FillResult.IMPOSSIBLE

        if other is FillResult.DOWNLOAD_NEEDED or self is FillResult.DOWNLOAD_NEEDED:
            return FillResult.DOWNLOAD_NEEDED

        return FillResult.COMPLETE

    def __or__(self, other):
        if other is FillResult.UNDETERMINED:
            return self

        if self is FillResult.UNDETERMINED:
            return other

        if other is FillResult.COMPLETE or self is FillResult.COMPLETE:
            return FillResult.COMPLETE

        if other is FillResult.DOWNLOAD_NEEDED or self is FillResult.DOWNLOAD_NEEDED:
            return FillResult.DOWNLOAD_NEEDED

        return FillResult.IMPOSSIBLE

class NoPackagesPossible(Exception):
    pass

class DownloadsFailed(Exception):
    pass

class DownloadNotAllowed(Exception):
    pass

class HashedFile(object):
    def __init__(self, name):
        self.name = name
        self._md5 = None
        self._sha1 = None
        self._sha256 = None
        self.skip_hash_matching = False

    @classmethod
    def from_file(cls, name, f, write_to=None, size=None, progress=False):
        return cls.from_concatenated_files(name, [f], write_to, size, progress)

    @classmethod
    def from_concatenated_files(cls, name, fs, write_to=None, size=None,
            progress=False):
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

        for f in fs:
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

    @property
    def md5(self):
        return self._md5
    @md5.setter
    def md5(self, value):
        if self._md5 is not None and value != self._md5:
            raise AssertionError('trying to set md5 of "%s" to both %s '
                    + 'and %s', self.name, self._md5, value)
        self._md5 = value

    @property
    def sha1(self):
        return self._sha1
    @sha1.setter
    def sha1(self, value):
        if self._sha1 is not None and value != self._sha1:
            raise AssertionError('trying to set sha1 of "%s" to both %s '
                    + 'and %s', self.name, self._sha1, value)
        self._sha1 = value

    @property
    def sha256(self):
        return self._sha256
    @sha256.setter
    def sha256(self, value):
        if self._sha256 is not None and value != self._sha256:
            raise AssertionError('trying to set sha256 of "%s" to both %s '
                    + 'and %s', self.name, self._sha256, value)
        self._sha256 = value

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
        self._provides = set()
        self._size = None
        self.unpack = None
        self.unsuitable = None

    @property
    def look_for(self):
        if self.alternatives:
            return set([])
        if not self._look_for:
            self._look_for = set([self.name.lower(), self.install_as.lower()])
        return self._look_for
    @look_for.setter
    def look_for(self, value):
        self._look_for = set(x.lower() for x in value)

    @property
    def size(self):
        return self._size
    @size.setter
    def size(self, value):
        if self._size is not None and value != self._size:
            raise AssertionError('trying to set size of "%s" to both %d '
                    + 'and %d', self.name, self._size, value)
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

        # Prefixes of files that get installed to /usr/share/doc/PACKAGE
        # instead
        self.install_to_docdir = []

        # symlink => real file (the opposite way round that debhelper does it,
        # because the links must be unique but the real files are not
        # necessarily)
        self.symlinks = {}

        # Steam ID and path
        self.steam = {}

        # set of names of WantedFile instances to be installed
        self._install = set()

        # set of names of WantedFile instances to be optionally installed
        self._optional = set()

        # type of package: full, demo or expansion
        # full packages include quake-registered, quake2-full-data, quake3-data
        # demo packages include quake-shareware, quake2-demo-data
        # expansion packages include quake-armagon, quake-music, quake2-rogue
        self._type = 'full'

        self.version = GAME_PACKAGE_VERSION

        # if not None, install every file provided by the files with
        # these names
        self._install_contents_of = set()

    @property
    def install(self):
        return self._install
    @install.setter
    def install(self, value):
        self._install = set(value)

    @property
    def install_contents_of(self):
        return self._install_contents_of
    @install_contents_of.setter
    def install_contents_of(self, value):
        self._install_contents_of = set(value)

    @property
    def optional(self):
        return self._optional
    @optional.setter
    def optional(self, value):
        self._optional = set(value)

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
            'install_to_docdir': self.install_to_docdir,
            'name': self.name,
            'optional': sorted(self.optional),
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

        # these should be per-package
        assert 'install_files' not in self.yaml
        assert 'package' not in self.yaml
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

        # Map from WantedFile name to whether we can get it.
        # file_status[x] is COMPLETE if and only if either
        # found[x] exists, or x has alternative y and found[y] exists.
        self.file_status = defaultdict(lambda: FillResult.UNDETERMINED)

        # Map from WantedFile look_for name to a set of names of WantedFile
        # instances which might be it
        # { 'doom2.wad': set(['doom2.wad_1.9', 'doom2.wad_bfg', ...]) }
        self.known_filenames = {}

        # Map from WantedFile size to a set of names of WantedFile
        # instances which might be it
        # { 14604584: set(['doom2.wad_1.9']) }
        self.known_sizes = {}

        # Maps from md5, sha1, sha256 to a set of names of WantedFile instances
        # { '25e1459...': set(['doom2.wad_1.9']) }
        self.known_md5s = {}
        self.known_sha1s = {}
        self.known_sha256s = {}

        # Failed downloads
        self.download_failed = set()

        # Map from GameDataPackage name to whether we can do it
        self.package_status = defaultdict(lambda: FillResult.UNDETERMINED)

        # Set of executables we wanted but don't have
        self.missing_tools = set()

        # Set of filenames we couldn't unpack
        self.unpack_failed = set()

        self._populate_files(self.yaml.get('files'))

        assert 'packages' in self.yaml

        for binary, data in self.yaml['packages'].items():
            # these should only be at top level, since they are global
            assert 'cksums' not in data, binary
            assert 'md5sums' not in data, binary
            assert 'sha1sums' not in data, binary
            assert 'sha256sums' not in data, binary

            package = self.construct_package(binary)
            self.packages[binary] = package
            self._populate_package(package, data)

        if 'cksums' in self.yaml:
            for line in self.yaml['cksums'].splitlines():
                stripped = line.strip()
                if stripped == '' or stripped.startswith('#'):
                    continue

                _, size, filename = line.split(None, 2)
                f = self._ensure_file(filename)
                f.size = int(size)

        for alg in ('md5', 'sha1', 'sha256'):
            if alg + 'sums' in self.yaml:
                for line in self.yaml[alg + 'sums'].splitlines():
                    stripped = line.strip()
                    if stripped == '' or stripped.startswith('#'):
                        continue

                    hexdigest, filename = MD5SUM_DIVIDER.split(line, 1)
                    f = self._ensure_file(filename)
                    setattr(f, alg, hexdigest)

        for filename, f in self.files.items():
            for provided in f.provides:
                self.providers.setdefault(provided, set()).add(filename)

            if f.alternatives:
                continue

            if f.distinctive_size and f.size is not None:
                self.known_sizes.setdefault(f.size, set()).add(filename)

            for lf in f.look_for:
                self.known_filenames.setdefault(lf, set()).add(filename)

            if f.md5 is not None:
                self.known_md5s.setdefault(f.md5, set()).add(filename)

            if f.sha1 is not None:
                self.known_sha1s.setdefault(f.sha1, set()).add(filename)

            if f.sha256 is not None:
                self.known_sha256s.setdefault(f.sha256, set()).add(filename)

        if 'compress_deb' in self.yaml:
            self.compress_deb = self.yaml['compress_deb']

        if 'help_text' in self.yaml:
            self.help_text = self.yaml['help_text']

        if 'steam' in self.yaml:
            self.steam = self.yaml['steam']

        for package in self.packages.values():
            for provider in package.install_contents_of:
                assert provider in self.files, (package.name, provider)
                for filename in self.files[provider].provides:
                    assert filename in self.files, (package.name, provider,
                            filename)
                    package.install.add(filename)

        # consistency check
        for package in self.packages.values():
            # there had better be something it wants to install
            assert package.install, package.name
            for installable in package.install:
                assert installable in self.files, installable
            for installable in package.optional:
                assert installable in self.files, installable

        for filename, wanted in self.files.items():
            if wanted.unpack:
                assert 'format' in wanted.unpack, filename
                if wanted.unpack['format'] == 'cat':
                    assert len(wanted.provides) == 1, filename
                    assert isinstance(wanted.unpack['other_parts'],
                            list), filename

            if wanted.alternatives:
                for alt in wanted.alternatives:
                    assert alt in self.files, alt

                # if this is a placeholder for a bunch of alternatives, then
                # it doesn't make sense for it to have a defined checksum
                # or size
                assert wanted.md5 is None, wanted.name
                assert wanted.sha1 is None, wanted.name
                assert wanted.sha256 is None, wanted.name
                assert wanted.size is None, wanted.name

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
        for k in ('type', 'longname', 'symlinks', 'install_to',
                'install_to_docdir', 'install_contents_of', 'steam'):
            if k in d:
                setattr(package, k, d[k])

        if 'install' in d:
            for filename in d['install']:
                f = self._ensure_file(filename)
                package.install.add(filename)

        if 'optional' in d:
            assert isinstance(d['optional'], list), package.name
            for filename in d['optional']:
                f = self._ensure_file(filename)
                package.optional.add(filename)

        if 'install_files_from_cksums' in d:
            for line in d['install_files_from_cksums'].splitlines():
                stripped = line.strip()
                if stripped == '' or stripped.startswith('#'):
                    continue

                _, size, filename = line.split(None, 2)
                f = self._ensure_file(filename)
                f.size = int(size)
                package.install.add(filename)

        self._populate_files(d.get('install_files'), install_package=package)

    def _populate_files(self, d, install_package=None,
            **kwargs):
        if d is None:
            return

        for filename, data in d.items():
            if install_package is not None:
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
                    'provides',
                    'sha1',
                    'sha256',
                    'size',
                    'skip_hash_matching',
                    'unpack',
                    'unsuitable',
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

        if wanted.unsuitable:
            logger.warning('"%s" matches known file "%s" but cannot '
                    'be used:\n%s', path, wanted.name, wanted.unsuitable)
            # ... but do not continue processing
            return True

        logger.debug('... yes, looks good')
        self.found[wanted.name] = path
        self.file_status[wanted.name] = FillResult.COMPLETE
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
                            log=(self.files[wanted_name].distinctive_name
                                and len(candidates) == 1)):
                        return
                else:
                    if len(candidates) > 1:
                        candidates = [self.files[c] for c in candidates]
                        for candidate in candidates:
                            if not candidate.distinctive_name:
                                break
                            else:
                                self._log_not_any_of(path, size, hashes,
                                        'possible "%s"' % look_for, candidates)

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
            for wanted_name in (self.known_md5s.get(hashes.md5, set()) |
                    self.known_sha1s.get(hashes.sha1, set()) |
                    self.known_sha256s.get(hashes.sha256, set())):
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
            if candidate.unsuitable:
                continue

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
        """Return a FillResult.
        """
        assert package is not None

        logger.debug('trying to fill any gaps for %s', package.name)

        # this is redundant, it's only done to get the debug messages first
        for filename in package.install:
            if filename not in self.found:
                wanted = self.files[filename]

                for alt in wanted.alternatives:
                    if alt in self.found:
                        break
                else:
                    logger.debug('gap needs to be filled for %s: %s',
                            package.name, filename)

        result = FillResult.COMPLETE

        for filename in (package.install | package.optional):
            if filename not in self.found:
                wanted = self.files[filename]

                if wanted.alternatives:
                    for alt in wanted.alternatives:
                        self.file_status[filename] |= self.file_status[alt]
                else:
                    # updates file_status as a side-effect
                    self.fill_gap(package, wanted, download=download, log=log)

            if filename in package.install:
                # it is mandatory
                result &= self.file_status[filename]

        self.package_status[package.name] = result
        return result

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
        random.shuffle(mirrors)
        if 'GDP_MIRROR' in os.environ:
            url = os.environ.get('GDP_MIRROR')
            if url.startswith('/'):
                url = 'file://' + url
            elif url.split(':')[0] not in ('http', 'https', 'ftp', 'file'):
                url = 'http://' + url
            if not url.endswith('/'):
                url = url + '/'
            url = url + details.get('name', wanted.name)
            mirrors.insert(0, url)
        if not mirrors:
            logger.error('Could not select a mirror for "%s"', wanted.name)
            return []
        return mirrors

    def cat_files(self, package, provider, wanted):
        other_parts = provider.unpack['other_parts']
        for p in other_parts:
            self.fill_gap(package, self.files[p], download=False, log=True)
            if p not in self.found:
                # can't concatenate: one of the bits is missing
                break
        else:
            # we didn't break, so we have all the bits
            path = os.path.join(self.get_workdir(), 'tmp',
                    wanted.name)
            with open(path, 'wb') as writer:
                def open_files():
                    yield open(self.found[provider.name], 'rb')
                    for p in other_parts:
                        yield open(self.found[p], 'rb')
                hasher = HashedFile.from_concatenated_files(wanted.name,
                        open_files(), writer, size=wanted.size,
                        progress=(wanted.size > QUITE_LARGE))
            self.use_file(wanted, path, hasher)

    def fill_gap(self, package, wanted, download=False, log=True):
        """Try to unpack, download or otherwise obtain wanted.

        If download is true, we may attempt to download wanted or a
        file that will provide it.

        Return a FillResult.
        """
        if wanted.name in self.found:
            assert self.file_status[wanted.name] is FillResult.COMPLETE
            return FillResult.COMPLETE

        if self.file_status[wanted.name] is FillResult.IMPOSSIBLE:
            return FillResult.IMPOSSIBLE

        if (self.file_status[wanted.name] is FillResult.DOWNLOAD_NEEDED and
                not download):
            return FillResult.DOWNLOAD_NEEDED

        logger.debug('could not find %s, trying to derive it...', wanted.name)

        self.file_status[wanted.name] = FillResult.IMPOSSIBLE

        if wanted.alternatives:
            for alt in wanted.alternatives:
                self.file_status[wanted.name] |= self.fill_gap(package,
                        self.files[alt], download=download, log=False)

            if self.file_status[wanted.name] is FillResult.IMPOSSIBLE and log:
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

            return self.file_status[wanted.name]

        # no alternatives: try getting the file itself

        if wanted.download:
            # we think we can get it
            self.file_status[wanted.name] = FillResult.DOWNLOAD_NEEDED

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
                            assert (self.file_status[wanted.name] ==
                                    FillResult.COMPLETE)
                            return FillResult.COMPLETE
                        else:
                            os.remove(tmp)
                    except Exception as e:
                        logger.warning('Failed to download "%s": %s', url,
                                e)
                        self.download_failed.add(url)
                        if tmp is not None:
                            os.remove(tmp)

        providers = list(self.providers.get(wanted.name, ()))

        # if we are installing everything from a downloadable file,
        # prefer to fill any gaps from that one, not some other
        # (e.g. don't download the Quake II demo if we're building
        # a .deb for the full game, just because their files happen to
        # overlap)
        for provider_name in package.install_contents_of:
            if provider_name in providers:
                logger.debug('preferring "%s" to provide files for %s',
                        provider_name, package.name)
                providers = [provider_name] + [p for p in providers if
                        p != provider_name]

        for provider_name in providers:
            provider = self.files[provider_name]

            # don't bother if we wouldn't be able to unpack it anyway
            if not self.check_unpacker(provider):
                continue

            # recurse to unpack or (see whether we can) download the provider
            provider_status = self.fill_gap(package, provider,
                    download=download, log=log)

            if provider_status is FillResult.COMPLETE:
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
                    to_unpack = provider.unpack.get('unpack', provider.provides)
                    logger.debug('Extracting %r from %s',
                            to_unpack, found_name)
                    tmpdir = os.path.join(self.get_workdir(), 'tmp',
                            provider_name + '.d')
                    mkdir_p(tmpdir)
                    subprocess.check_call(['lha', 'xq',
                                os.path.abspath(found_name)] +
                            list(to_unpack), cwd=tmpdir)
                    for f in to_unpack:
                        self.consider_file(os.path.join(tmpdir, f), True)
                elif fmt == 'id-shr-extract':
                    to_unpack = provider.unpack.get('unpack', provider.provides)
                    logger.debug('Extracting %r from %s',
                            to_unpack, found_name)
                    tmpdir = os.path.join(self.get_workdir(), 'tmp',
                            provider_name + '.d')
                    mkdir_p(tmpdir)
                    subprocess.check_call(['id-shr-extract',
                                os.path.abspath(found_name)],
                            cwd=tmpdir)
                    for f in to_unpack:
                        self.consider_file(os.path.join(tmpdir, f), True)
                elif fmt == 'cat':
                    self.cat_files(package, provider, wanted)

                if wanted.name in self.found:
                    assert (self.file_status[wanted.name] ==
                            FillResult.COMPLETE)
                    return FillResult.COMPLETE
            elif self.file_status[provider_name] is FillResult.DOWNLOAD_NEEDED:
                # we don't have it, but we can get it
                self.file_status[wanted.name] |= FillResult.DOWNLOAD_NEEDED
            # else impossible, but try next provider

        if self.file_status[wanted.name] is FillResult.IMPOSSIBLE and log:
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

        return self.file_status[wanted.name]

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

        for filename in (package.install | package.optional):
            wanted = self.files[filename]
            install_as = wanted.install_as

            if filename in self.found:
                copy_from = self.found[filename]
            else:
                for alt in wanted.alternatives:
                    if alt in self.found:
                        copy_from = self.found[alt]
                        if wanted.install_as == '$alternative':
                            install_as = self.files[alt].install_as
                        break
                else:
                    if filename not in package.install:
                        logger.debug('optional file %r is missing, ignoring',
                                filename)
                        continue

                    raise AssertionError('we already checked that %s exists' %
                            (filename))

            # cp it into place
            with TemporaryUmask(0o22):
                logger.debug('Found %s at %s', wanted.name, copy_from)

                install_to = wanted.install_to

                if install_to is None:
                    install_to = package.install_to

                if install_to.startswith('$docdir'):
                    install_to = 'usr/share/doc/%s%s' % (package.name,
                            install_to[7:])

                for prefix in package.install_to_docdir:
                    if wanted.name.startswith(prefix + '/'):
                        install_to = 'usr/share/doc/%s' % package.name

                copy_to = os.path.join(destdir, install_to, install_as)
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
            '.'], cwd=destdir).decode('utf-8').split(None, 1)[0]
        assert control['Package'] in ('PACKAGE', package.name)
        control['Package'] = package.name
        control['Installed-Size'] = size
        package.version = control['Version'].replace('VERSION',
                GAME_PACKAGE_VERSION)
        control['Version'] = package.version

    def get_control_template(self, package):
        return os.path.join(DATADIR, package.name + '.control.in')

    def add_parser(self, parsers, base_parser):
        parser = parsers.add_parser(self.shortname,
                help=self.longname, aliases=self.packages.keys(),
                description=self.help_text,
                formatter_class=argparse.RawDescriptionHelpFormatter,
                parents=(base_parser,))
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

    def look_for_files(self, paths=(), search=True):
        paths = list(paths)

        if search:
            for path in self.try_repack_from:
                if os.path.isdir(path):
                    paths.append(path)

            for package in self.packages.values():
                path = '/' + package.install_to
                if os.path.isdir(path):
                    paths.append(path)
                path = '/usr/share/doc/' + package.name
                if os.path.isdir(path):
                    paths.append(path)

            for path in self.iter_steam_paths():
                paths.append(path)

        for arg in paths:
            logger.debug('%s...', arg)
            self.consider_file_or_dir(arg)

    def run_command_line(self, args):
        logger.debug('package description:\n%s',
                yaml.safe_dump(self.to_yaml()))

        preserve_debs = (getattr(args, 'destination', None) is not None)
        install_debs = getattr(args, 'install', True)

        if getattr(args, 'compress', None) is None:
            # default to not compressing if we aren't going to install it
            # anyway
            args.compress = preserve_debs

        self.look_for_files(paths=args.paths, search=args.search)

        if args.shortname in self.packages:
            packages = set([self.packages[args.shortname]])
        else:
            packages = set(self.packages.values())

        try:
            ready = self.prepare_packages(packages,
                    build_demos=args.demo, download=args.download)
        except NoPackagesPossible:
            logger.error('Unable to complete any packages.')
            if self.missing_tools:
                # we already logged warnings about the files as they came up
                self.log_missing_tools()
                raise SystemExit(1)

            # probably not enough files supplied?
            # print the help text, maybe that helps the user to determine
            # what they should have added
            self.argument_parser.print_help()
            raise SystemExit(1)
        except DownloadNotAllowed:
            logger.error('Unable to complete any packages because ' +
                    'downloading missing files was not allowed.')
            raise SystemExit(1)
        except DownloadsFailed:
            # we already logged an error
            logger.error('Unable to complete any packages because downloads failed.')
            raise SystemExit(1)

        if args.destination is None:
            destination = self.get_workdir()
        else:
            destination = args.destination

        debs = self.build_packages(ready,
                compress=getattr(args, 'compress', True),
                destination=destination)

        rm_rf(os.path.join(self.get_workdir(), 'tmp'))

        if preserve_debs:
            for deb in debs:
                print('generated "%s"' % os.path.abspath(deb))

        if install_debs:
            self.install_packages(debs)

    def prepare_packages(self, packages, build_demos=False, download=True):
        possible = set()

        for package in packages:
            if self.fill_gaps(package, log=False) is not FillResult.IMPOSSIBLE:
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
                    if self.fill_gaps(package=package,
                            log=True) is not FillResult.IMPOSSIBLE:
                        logger.error('%s unexpectedly succeeded on second ' +
                                'attempt. Please report this as a bug',
                                package.name)
                        possible.add(package)
                    else:
                        raise NoPackagesPossible()
            else:
                # If no demo, repeat the process for the first
                # (hopefully only) full package, so we can log *its* errors.
                for package in self.packages.values():
                    if package.type == 'full':
                        if self.fill_gaps(package=package,
                                log=True) is not FillResult.IMPOSSIBLE:
                            logger.error('%s unexpectedly succeeded on ' +
                                    'second attempt. Please report this as '
                                    'a bug', package.name)
                            possible.add(package)
                        else:
                            raise NoPackagesPossible()
                else:
                    raise NoPackagesPossible()

        ready = set()

        have_full = False
        for package in possible:
            if package.type == 'full':
                have_full = True

        for package in possible:
            if have_full and package.type == 'demo' and not build_demos:
                # no point in packaging the demo if we have the full
                # version
                logger.debug('will not produce %s because we have a full ' +
                        'version', package.name)
                continue

            logger.debug('will produce %s', package.name)
            result = self.fill_gaps(package=package, download=download,
                    log=True)
            if result is FillResult.COMPLETE:
                ready.add(package)
            elif result is FillResult.DOWNLOAD_NEEDED and not download:
                logger.warning('As requested, not downloading necessary ' +
                        'files for %s', package.name)
            else:
                logger.error('Failed to download necessary files for %s',
                        package.name)

        if not ready:
            if not download:
                raise DownloadNotAllowed()
            raise DownloadsFailed()

        return ready

    def build_packages(self, ready, destination, compress):
        debs = set()

        for package in ready:
            deb = self.build_deb(package, destination, compress=compress)

            if deb is None:
                raise SystemExit(1)

            debs.add(deb)

        return debs

    def install_packages(self, debs):
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

    def build_deb(self, package, destination, compress=True):
        """
        If we have all the necessary files for package, build the .deb
        and return the output filename in destination. Otherwise return None.
        """
        destdir = os.path.join(self.get_workdir(), '%s.deb.d' % package.name)
        if not self.fill_dest_dir(package, destdir):
            # FIXME: probably better as an exception?
            return None

        # it had better have a /usr and a DEBIAN directory or
        # something has gone very wrong
        assert os.path.isdir(os.path.join(destdir, 'usr')), destdir
        assert os.path.isdir(os.path.join(destdir, 'DEBIAN')), destdir

        deb_basename = '%s_%s_all.deb' % (package.name, package.version)

        outfile = os.path.join(os.path.abspath(destination), deb_basename)

        # only compress if the caller says we should and the YAML
        # says it's worthwhile
        if compress and self.compress_deb:
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

        rm_rf(destdir)
        return outfile

    def check_unpacker(self, wanted):
        if not wanted.unpack:
            return True

        if wanted.name in self.unpack_failed:
            return False

        fmt = wanted.unpack['format']

        if fmt in ('id-shr-extract', 'lha'):
            if which(fmt) is None:
                logger.warning('cannot unpack "%s": tool "%s" is not ' +
                        'installed', wanted.name, fmt)
                self.missing_tools.add(fmt)
                self.unpack_failed.add(wanted.name)
                return False

        return True

    def log_missing_tools(self):
        if not self.missing_tools:
            return False

        package_map = {
                'id-shr-extract': 'dynamite',
                'lha': 'lhasa',
        }
        packages = set()

        for t in self.missing_tools:
            p = package_map.get(t)
            if p is not None:
                packages.add(p)

        logger.warning('installing these packages might help:\n' +
                'apt-get install %s',
                ' '.join(sorted(packages)))

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
    logger.debug('Arguments: %r', sys.argv)

    # Don't set any defaults on this base parser, because it interferes
    # with the ability to recognise the same argument either before or
    # after the game name. Set them on the Namespace instead.
    base_parser = argparse.ArgumentParser(prog='game-data-packager',
            description='Package game files.',
            add_help=False,
            argument_default=argparse.SUPPRESS)

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
    group.add_argument('--search', action='store_true',
            help='look for installed files in Steam and other likely places ' +
                '(default)')
    group.add_argument('--no-search', action='store_false',
            dest='search',
            help='only look in paths provided on the command line')

    group = base_parser.add_mutually_exclusive_group()
    group.add_argument('--download', action='store_true',
            help='automatically download necessary files if possible ' +
                '(default)')
    group.add_argument('--no-download', action='store_false',
            dest='download', help='do not download anything')

    parser = argparse.ArgumentParser(prog='game-data-packager',
            description='Package game files.', parents=(base_parser,))

    game_parsers = parser.add_subparsers(dest='shortname',
            title='supported games', metavar='GAME')

    games = load_yaml_games(os.environ.get('WORKDIR', None))

    for g in sorted(games.keys()):
        games[g].add_parser(game_parsers, base_parser)

    parsed = argparse.Namespace(
            compress=None,
            destination=None,
            download=True,
            install=False,
            search=True,
    )
    parser.parse_args(namespace=parsed)

    if parsed.destination is None and not parsed.install:
        logger.error('At least one of --install or --destination is required')
        sys.exit(2)

    if parsed.shortname is None:
        parser.print_help()
        sys.exit(0)

    with games[parsed.shortname] as game:
        game.run_command_line(parsed)
