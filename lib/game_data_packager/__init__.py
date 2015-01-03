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

"""Prototype for a more data-driven game-data-packager implementation.
"""

import hashlib
import io
import logging
import os
import random
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile

import yaml

from .util import TemporaryUmask, mkdir_p, human_size, MEBIBYTE

logging.basicConfig()
logger = logging.getLogger('game-data-packager')

# For now, we're given these by the shell script wrapper.
DATADIR = os.environ['DATADIR']
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

        # set of names of WantedFile instances to be installed
        self._install = set()

        # type of package: full, demo or expansion
        # full packages include quake-registered, quake2-full-data, quake3-data
        # demo packages include quake-shareware, quake2-demo-data
        # expansion packages include quake-armagon, quake-music, quake2-rogue
        self._type = 'full'

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
            'symlinks': self.symlinks,
        }

class GameData(object):
    def __init__(self,
            shortname,
            datadir='/usr/share/games/game-data-packager',
            etcdir='/etc/game-data-packager',
            workdir=None):
        # The name of the game
        self.shortname = shortname

        # game-data-packager's configuration directory
        self.etcdir = etcdir

        # game-data-packager's data directory.
        self.datadir = datadir

        # A temporary directory.
        self.workdir = workdir

        # Clean up these directories on exit.
        self._cleanup_dirs = set()

        # binary package name => GameDataPackage
        self.packages = {}

        # If true, we may compress the .deb. If false, don't.
        self.compress_deb = True

        self.yaml = yaml.load(open(os.path.join(self.datadir,
            shortname + '.yaml')))

        if 'package' in self.yaml:
            package = GameDataPackage(self.yaml['package'])
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
        # { 'baseq3/pak1.pk3' => WantedFile instance }
        self.files = {}

        # Map from WantedFile name to a set of names of WantedFile instances
        # from which the file named in the key can be extracted or generated.
        # { 'baseq3/pak1.pk3' => set(['linuxq3apoint-1.32b-3.x86.run']) }
        self.providers = {}

        # Map from WantedFile name to the absolute or relative path of
        # a matching file on disk.
        # { 'baseq3/pak1.pk3' => '/usr/share/games/quake3/baseq3/pak1.pk3' }
        self.found = {}

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

                package = GameDataPackage(binary)
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

        if 'compress_deb' in self.yaml:
            self.compress_deb = self.yaml['compress_deb']

        logger.debug('loaded package description:\n%s',
                yaml.safe_dump(self.to_yaml()))

        # consistency check
        for package in self.packages.values():
            # there had better be something it wants to install
            assert package.install, package.name
            for installable in package.install:
                assert installable in self.files, installable

        for filename, wanted in self.files.items():
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

        for filename, f in self.files.items():
            files[filename] = f.to_yaml()

        for provided, by in self.providers.items():
            providers[provided] = list(by)

        for name, package in self.packages.items():
            packages[name] = package.to_yaml()

        return {
            'packages': packages,
            'providers': providers,
            'files': files,
        }

    def _populate_package(self, package, d):
        if 'type' in d:
            package.type = d['type']

        if 'symlinks' in d:
            package.symlinks = d['symlinks']

        if 'install_to' in d:
            package.install_to = d['install_to']

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

    def use_file(self, wanted, path, hashes=None):
        logger.debug('found possible %s at %s', wanted.name, path)
        size = os.stat(path).st_size
        if wanted.size is not None and wanted.size != size:
            if wanted.distinctive_name:
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

    def consider_file(self, path, really_should_match_something):
        if not os.path.exists(path):
            # dangling symlink
            return

        match_path = '/' + path.lower()
        size = os.stat(path).st_size

        if really_should_match_something:
            if size > QUITE_LARGE:
                logger.info('identifying %s', path)
            hashes = HashedFile.from_file(path, open(path, 'rb'), size=size,
                    progress=(size > QUITE_LARGE))
        else:
            hashes = None

        for wanted in self.files.values():
            if wanted.alternatives:
                continue

            for lf in wanted.look_for:
                if match_path.endswith('/' + lf):
                    self.use_file(wanted, path, hashes)
                    if wanted.distinctive_name:
                        return

            if wanted.distinctive_size:
                if wanted.size == size:
                    logger.debug('... matched by distinctive size %d', size)
                    self.use_file(wanted, path, hashes)

            if hashes is not None:
                if not wanted.skip_hash_matching and hashes.matches(wanted):
                    logger.debug('... matched hashes of %s', wanted.name)
                    self.use_file(wanted, path, hashes)
                    return
        else:
            if really_should_match_something:
                logger.warning('file "%s" does not match any known file', path)

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
                alt_possible = False

                for alt in wanted.alternatives:
                    logger.debug('trying alternative: %s', alt)
                    if alt in self.found:
                        alt_possible = True
                        break
                    elif self.fill_gap(self.files[alt], download=download,
                            log=log):
                        alt_possible = True

                if alt_possible:
                    pass
                elif not self.fill_gap(wanted, download=download, log=log):
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
                f = open(os.path.join(self.etcdir, mirror_list))
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
            elif providable:
                # we don't have it, but we can get it
                possible = True
            # else impossible, but try next provider

        if not possible:
            if log:
                if wanted.alternatives:
                    logger.error('could not find any version of %s:',
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
                else:
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

    def fill_dest_dir(self, package, destdir):
        if not self.check_complete(package, log=True):
            return False

        docdir = os.path.join(destdir, 'usr/share/doc', package.name)
        mkdir_p(docdir)
        shutil.copyfile(os.path.join(self.datadir, package.name + '.copyright'),
                os.path.join(docdir, 'copyright'))
        shutil.copyfile(os.path.join(self.datadir, 'changelog.gz'),
                os.path.join(docdir, 'changelog.gz'))

        # slipstream_instsize, slipstream_repack assume that
        # slipstream.unpacked and DEBIAN are in the same place.
        # The shell script code puts slipstream.unpacked in workdir.
        assert destdir == self.workdir + '/slipstream.unpacked'
        debdir = os.path.join(self.workdir, 'DEBIAN')
        mkdir_p(debdir)
        shutil.copyfile(os.path.join(self.datadir, package.name + '.control'),
                os.path.join(debdir, 'control'))

        for ms in ('preinst', 'postinst', 'prerm', 'postrm'):
            maintscript = os.path.join(self.datadir, package.name + '.' + ms)
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

        # FIXME: eventually we should build the .deb in Python, but for now
        # we let the shell script do it

        # Hackish way to communicate to shell script that we don't want
        # compression
        if not self.compress_deb:
            open(os.path.join(self.workdir, 'DO-NOT-COMPRESS'), 'w').close()

        return True
