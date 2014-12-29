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
        self.distinctive_name = True
        self.distinctive_size = False
        self.download = None
        self.install = False
        self._install_as = None
        self._look_for = []
        self.optional = False
        self._provides = set()
        self._size = None
        self.unpack = None

    @property
    def look_for(self):
        if not self._look_for:
            self._look_for = set([self.name.lower()])
        return self._look_for
    @look_for.setter
    def look_for(self, value):
        self._look_for = set(x.lower() for x in value)

    @property
    def install_as(self):
        if self._install_as is None:
            return self.name
        return self._install_as
    @install_as.setter
    def install_as(self, value):
        self.install = (value is not None)
        self._install_as = value

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
            'distinctive_name': self.distinctive_name,
            'distinctive_size': self.distinctive_size,
            'download': self.download,
            'install': self.install,
            'install_as': self.install_as,
            'look_for': list(self.look_for),
            'name': self.name,
            'optional': self.optional,
            'provides': list(self.provides),
            'size': self.size,
            'unpack': self.unpack,
        }

class GameDataPackage(object):
    def __init__(self,
            name,
            datadir='/usr/share/games/game-data-packager',
            etcdir='/etc/game-data-packager',
            workdir=None):
        # The name of the binary package
        self.name = name

        # game-data-packager's configuration directory
        self.etcdir = etcdir

        # game-data-packager's data directory.
        self.datadir = datadir

        # A temporary directory.
        self.workdir = workdir

        # Clean up these directories on exit.
        self._cleanup_dirs = set()

        # If true, we may compress the .deb. If false, don't.
        self.compress_deb = True

        self.yaml = yaml.load(open(os.path.join(self.datadir, name + '.yaml')))
        assert self.yaml['package'] == name

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

        # Where we install files.
        # For instance, if this is 'usr/share/games/quake3' and we have
        # a WantedFile with install_as='baseq3/pak1.pk3' then we would
        # put 'usr/share/games/quake3/baseq3/pak1.pk3' in the .deb.
        # The default is 'usr/share/games/' plus the binary package's name.
        self.install_to = 'usr/share/games/' + name

        if 'install_to' in self.yaml:
            self.install_to = self.yaml['install_to']

        self._populate_files(self.yaml.get('files'))
        self._populate_files(self.yaml.get('install_files'), install=True)

        if 'install_files_from_cksums' in self.yaml:
            for line in self.yaml['install_files_from_cksums'].splitlines():
                stripped = line.strip()
                if stripped == '' or stripped.startswith('#'):
                    continue

                _, size, filename = line.split(None, 2)
                f = self._ensure_file(filename)
                size = int(size)
                assert (f.size == size or f.size is None), (f.size, size)
                f.size = size
                f.install = True

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

        for filename, f in self.files.items():
            files[filename] = f.to_yaml()

        for provided, by in self.providers.items():
            providers[provided] = list(by)

        return {
            'package': self.name,
            'providers': providers,
            'files': files,
            'install_to': self.install_to,
        }

    def _populate_files(self, d, **kwargs):
        if d is None:
            return

        for filename, data in d.items():
            f = self._ensure_file(filename)

            for k in kwargs:
                setattr(f, k, kwargs[k])

            for k in (
                    'distinctive_name',
                    'distinctive_size',
                    'download',
                    'install',
                    'install_as',
                    'look_for',
                    'md5',
                    'optional',
                    'provides',
                    'sha1',
                    'sha256',
                    'size',
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
        size = os.path.getsize(path)
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

        if not hashes.matches(wanted):
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
        match_path = '/' + path.lower()
        size = os.path.getsize(path)

        if really_should_match_something:
            if size > QUITE_LARGE:
                logger.info('identifying %s', path)
            hashes = HashedFile.from_file(path, open(path, 'rb'), size=size,
                    progress=(size > QUITE_LARGE))
        else:
            hashes = None

        for wanted in self.files.values():
            for lf in wanted.look_for:
                if match_path.endswith('/' + lf):
                    self.use_file(wanted, path, hashes)
                    if wanted.distinctive_name:
                        return

            if wanted.distinctive_size:
                if wanted.size == size:
                    self.use_file(wanted, path, hashes)

            if hashes is not None:
                if hashes.matches(wanted):
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
                    path = os.path.join(dirpath, fn)
                    self.consider_file(path, False)
        else:
            logger.warning('file "%s" does not exist or is not a file or ' +
                    'directory', path)

    def fill_gaps(self, download=False, log=True):
        possible = True

        for (filename, wanted) in self.files.items():
            if wanted.install and filename not in self.found:
                if not self.fill_gap(wanted, download=download):
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

                if wanted.size is not None and wanted.size != entry.file_size:
                    continue

                match_path = '/' + entry.filename

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

                if wanted.size is not None and wanted.size != entry.size:
                    continue

                match_path = '/' + entry.name

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
        logger.debug('could not find %s, trying to derive it...', wanted.name)
        possible = False

        for provider_name in self.providers.get(wanted.name, ()):
            provider = self.files[provider_name]

            if provider.download or provider_name in self.found:
                possible = True

            if (download and provider_name not in self.found and
                    provider.download):
                logger.debug('trying to download %s to provide %s...',
                        provider.name, wanted.name)
                urls = self.choose_mirror(provider)
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
                                'tmp', provider.name)
                        tmpdir = os.path.dirname(tmp)
                        mkdir_p(tmpdir)
                        wf = open(tmp, 'wb')
                        logger.info('downloading %s', url)
                        hf = HashedFile.from_file(url, rf, wf,
                                size=provider.size, progress=True)
                        wf.close()

                        if self.use_file(provider, tmp, hf):
                            break
                        else:
                            os.remove(tmp)
                    except Exception as e:
                        logger.warning('Failed to download "%s": %s', url,
                                e)
                        self.download_failed.add(url)
                        if tmp is not None:
                            os.remove(tmp)

            if provider_name in self.found:
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

        if not possible:
            if log:
                logger.error('could not find %s:\n' +
                        '  expected:\n' +
                        '    size:   %d bytes\n' +
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

    def check_complete(self, log=False):
        # Got everything?
        complete = True
        for (filename, wanted) in self.files.items():
            if not wanted.install:
                continue

            if filename in self.found:
                continue

            complete = False
            if log:
                logger.error('could not find %s:\n' +
                        '  expected:\n' +
                        '    size:   %d bytes\n' +
                        '    md5:    %s\n' +
                        '    sha1:   %s\n' +
                        '    sha256: %s',
                        wanted.name,
                        wanted.size,
                        wanted.md5,
                        wanted.sha1,
                        wanted.sha256)

        return complete

    def fill_dest_dir(self, destdir):
        if not self.check_complete(log=True):
            return False

        docdir = os.path.join(destdir, 'usr/share/doc', self.name)
        mkdir_p(docdir)
        shutil.copyfile(os.path.join(self.datadir, self.name + '.copyright'),
                os.path.join(docdir, 'copyright'))
        shutil.copyfile(os.path.join(self.datadir, 'changelog.gz'),
                os.path.join(docdir, 'changelog.gz'))

        # slipstream_instsize, slipstream_repack assume that
        # slipstream.unpacked and DEBIAN are in the same place.
        # The shell script code puts slipstream.unpacked in workdir.
        assert destdir == self.workdir + '/slipstream.unpacked'
        debdir = os.path.join(self.workdir, 'DEBIAN')
        mkdir_p(debdir)
        shutil.copyfile(os.path.join(self.datadir, self.name + '.control'),
                os.path.join(debdir, 'control'))

        for (filename, wanted) in self.files.items():
            if not wanted.install:
                continue

            copy_from = self.found[filename]

            # cp it into place
            with TemporaryUmask(0o22):
                logger.debug('Found %s at %s', wanted.name, copy_from)
                copy_to = os.path.join(destdir,
                        self.install_to,
                        wanted.install_as)
                copy_to_dir = os.path.dirname(copy_to)
                logger.debug('Copying to %s', copy_to)
                if not os.path.isdir(copy_to_dir):
                    mkdir_p(copy_to_dir)
                # Use cp(1) so we can make a reflink if source and
                # destination happen to be the same btrfs volume
                subprocess.check_call(['cp', '--reflink=auto', copy_from,
                    copy_to])

        # FIXME: eventually we should build the .deb in Python, but for now
        # we let the shell script do it

        # Hackish way to communicate to shell script that we don't want
        # compression
        if not self.compress_deb:
            open(os.path.join(self.workdir, 'DO-NOT-COMPRESS'), 'w').close()

        return True
