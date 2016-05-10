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

from collections import defaultdict
from enum import Enum
import logging
import os
import random
import shutil
import stat
import subprocess
import tempfile
import time
import urllib.request
import zipfile

import yaml
try:
    from debian.debian_support import Version
    BACKPORT_SUFFIX = '~'
except ImportError:
    from distutils.version import LooseVersion as Version
    BACKPORT_SUFFIX = ''

from .data import (HashedFile)
from .gog import GOG
from .packaging import (get_native_packaging_system)
from .paths import (DATADIR, ETCDIR)
from .unpack import (TarUnpacker, ZipUnpacker)
from .unpack.umod import (Umod)
from .util import (AGENT,
        TemporaryUmask,
        check_call,
        check_output,
        copy_with_substitutions,
        lang_score,
        mkdir_p,
        rm_rf,
        recursive_utime,
        which)
from .version import (FORMAT, DISTRO)

if FORMAT == 'deb':
    from debian.deb822 import Deb822

logging.basicConfig()
logger = logging.getLogger(__name__)

class FillResult(Enum):
    UNDETERMINED = 0
    IMPOSSIBLE = 1
    DOWNLOAD_NEEDED = 2
    COMPLETE = 3
    UPGRADE_NEEDED = 4

    def __and__(self, other):
        if other is FillResult.UNDETERMINED:
            return self

        if self is FillResult.UNDETERMINED:
            return other

        if other is FillResult.IMPOSSIBLE or self is FillResult.IMPOSSIBLE:
            return FillResult.IMPOSSIBLE

        if other is FillResult.UPGRADE_NEEDED or self is FillResult.UPGRADE_NEEDED:
            return FillResult.UPGRADE_NEEDED

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

        if other is FillResult.UPGRADE_NEEDED or self is FillResult.UPGRADE_NEEDED:
            return FillResult.UPGRADE_NEEDED

        return FillResult.IMPOSSIBLE

class BinaryExecutablesNotAllowed(Exception):
    pass

class NoPackagesPossible(Exception):
    pass

class DownloadsFailed(Exception):
    pass

class DownloadNotAllowed(Exception):
    pass

class CDRipFailed(Exception):
    pass

def choose_mirror(wanted):
    mirrors = []
    mirror = os.environ.get('GDP_MIRROR')
    if mirror:
        if mirror.startswith('/'):
            mirror = 'file://' + mirror
        elif mirror.split(':')[0] not in ('http', 'https', 'ftp', 'file'):
            mirror = 'http://' + mirror
        if not mirror.endswith('/'):
            mirror = mirror + '/'

    if type(wanted.download) is str:
        if not mirror:
            return [wanted.download]
        url_basename = os.path.basename(wanted.download)
        if '?' not in url_basename:
            mirrors.append(mirror + url_basename)
        wanted.name = wanted.name.replace(' ','%20')
        if wanted.name != url_basename and '?' not in wanted.name:
            mirrors.append(mirror + wanted.name)
        mirrors.append(wanted.download)
        return mirrors

    for mirror_list, details in wanted.download.items():
        try:
            f = open(os.path.join(ETCDIR, mirror_list), encoding='utf-8')
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
    if mirror:
        if mirrors and '?' not in mirrors[0]:
            mirrors.insert(0, mirror + os.path.basename(mirrors[0]))
        elif '?' not in wanted.name:
            mirrors.insert(0, mirror + wanted.name)
    if not mirrors:
        logger.error('Could not select a mirror for "%s"', wanted.name)
        return []
    return mirrors

def iter_fat_mounts(folder):
    with open('/proc/mounts', 'r', encoding='utf8') as mounts:
        for line in mounts.readlines():
            mount, vfstype = line.split(' ')[1:3]
            if vfstype in ('fat', 'vfat', 'ntfs'):
                path = os.path.join(mount, 'Program Files', folder)
                if os.path.isdir(path):
                    yield path
                path = os.path.join(mount, folder)
                if os.path.isdir(path):
                    yield path

class PackagingTask(object):
    def __init__(self, game, packaging=None):
        # A GameData object.
        self.game = game

        # A packaging system.
        self.__packaging = packaging

        # A temporary directory.
        self.__workdir = None

        # Clean up these directories on exit.
        self._cleanup_dirs = set()

        # Map from WantedFile name to whether we can get it.
        # file_status[x] is COMPLETE if and only if either
        # found[x] exists, or x has alternative y and found[y] exists.
        self.file_status = defaultdict(lambda: FillResult.UNDETERMINED)

        # Map from WantedFile name to the absolute or relative path of
        # a matching file on disk.
        # { 'baseq3/pak1.pk3': '/usr/share/games/quake3/baseq3/pak1.pk3' }
        self.found = {}

        # Failed downloads
        self.download_failed = set()

        # Map from GameDataPackage name to whether we can do it
        self.package_status = defaultdict(lambda: FillResult.UNDETERMINED)

        # Set of executables we wanted but don't have
        self.missing_tools = set()

        # Set of filenames we couldn't unpack, or already unpacked
        self.unpack_tried = set()

        # Block device from which to rip audio
        self.cd_device = None

        # Found CD tracks
        # e.g. { 'quake-music': { 2: '/usr/.../id1/music/track02.ogg' } }
        self.cd_tracks = {}

        # If true, be more verbose
        self.verbose = False

        # None or an existing directory in which to save downloaded files.
        self.save_downloads = None

        # How to compress the .deb:
        # True: dpkg-deb's default
        # False: -Znone
        # str: -Zstr (gzip, xz or none)
        # list: arbitrary options (e.g. -z9 -Zgz -Sfixed)
        self.compress_deb = game.compress_deb

        # Factory for a progress report (or None).
        self.progress_factory = lambda info=None: None

        self.game.load_file_data()

    def __del__(self):
        self.__exit__(None, None, None)

    def __enter__(self):
        return self

    def __exit__(self, _et, _ev, _tb):
        for d in self._cleanup_dirs:
            shutil.rmtree(d, onerror=lambda func, path, ei:
                logger.warning('error removing "%s":' % path, exc_info=ei))
        self._cleanup_dirs = set()

    @property
    def packaging(self):
        """The PackagingSystem in use."""
        if self.__packaging is None:
            self.__packaging = get_native_packaging_system()

        return self.__packaging

    def get_workdir(self):
        if self.__workdir is None:
            self.__workdir = tempfile.mkdtemp(prefix='gdptmp.')
            self._cleanup_dirs.add(self.__workdir)
        return self.__workdir

    def use_file(self, found, candidates, path, hashes=None):
        logger.debug('found %s at %s', found, path)
        size = os.stat(path).st_size

        assert candidates

        remaining = set()

        for wanted in candidates:
            if wanted.size is None or wanted.size == size:
                remaining.add(wanted)
            else:
                logger.debug('... not the right size to be %s', wanted.name)

        if not remaining:
            for candidate in candidates:
                if not candidate.distinctive_name:
                    # silently ignore dissimilar file
                    logger.debug('... not a distinctive name, ignoring')
                    return False

            self._log_not_any_of(path, size, hashes, found, candidates)
            return False

        if hashes is None:
            hashes = HashedFile.from_file(path, open(path, 'rb'), size=size,
                    progress=self.progress_factory(info='checking %s' % path))

        for wanted in remaining:
            if not wanted.skip_hash_matching and not hashes.matches(wanted):
                logger.debug('... not the right hashes to be %s', wanted.name)
                continue

            if wanted.unsuitable:
                logger.warning('"%s" matches known file "%s" but cannot '
                        'be used:\n%s', path, wanted.name, wanted.unsuitable)
                # ... but do not continue processing
                return True

            logger.debug('... matches %s', wanted.name)
            self.found[wanted.name] = path
            self.file_status[wanted.name] = FillResult.COMPLETE

            # opportunistically use this same file to provide anything else that
            # has the same hashes (a duplicate file with a different name)
            for other_name in (self.game.known_md5s.get(hashes.md5, set()) |
                    self.game.known_sha1s.get(hashes.sha1, set()) |
                    self.game.known_sha256s.get(hashes.sha256, set())):
                other = self.game.files[other_name]
                if other is not wanted and other.matches(hashes):
                    logger.debug('... also matches %s', other_name)
                    self.found[other_name] = path
                    self.file_status[other_name] = FillResult.COMPLETE

            # no point in continuing, we've identified everything that matches
            # the hashes
            return True

        self._log_not_any_of(path, size, hashes, found, candidates)

    def consider_file(self, path, really_should_match_something, trusted=False):
        if not os.path.exists(path):
            # dangling symlink
            return

        match_path = '/' + path.lower()
        size = os.stat(path).st_size

        for p in self.game.rip_cd_packages:
            assert p.rip_cd

            # We use whatever the first track is (usually 2, because track
            # 1 is data) to locate the rest of the tracks.
            # We assume tracks in the middle are not missing.
            look_for = '/' + (p.rip_cd['filename_format'] %
                    p.rip_cd.get('first_track', 2))
            if match_path.endswith(look_for):
                self.cd_tracks[p.name] = {}
                # make sure it is at least as long as look_for
                # (corner-case: g-d-p quake id1/music)
                audio = path
                if not audio.startswith('/'):
                    audio = './' + audio
                basedir = audio[:len(audio) - len(look_for)]

                # The CD audio spec says we can't go beyond track 99.
                for i in range(p.rip_cd.get('first_track', 2), 100):
                    audio = os.path.join(basedir,
                            p.rip_cd['filename_format'] % i)
                    if not os.path.isfile(audio):
                        break
                    self.cd_tracks[p.name][i] = audio
                return

        # if a file (as opposed to a directory) is specified on the
        # command-line, try harder to match it to something
        if really_should_match_something:
            hashes = self.__ensure_hashes(None, path, size)
        else:
            hashes = None

        for look_for, candidates in self.game.known_filenames.items():
            if match_path.endswith('/' + look_for):
                candidates = [self.game.files[c] for c in candidates]
                if candidates:
                    hashes = self.__ensure_hashes(hashes, path, size)
                    if self.use_file('possible "%s"' % look_for, candidates,
                            path, hashes):
                        return

        if size in self.game.known_sizes:
            candidates = self.game.known_sizes[size]
            if candidates:
                hashes = self.__ensure_hashes(hashes, path, size)
                candidates = [self.game.files[c] for c in candidates]
                if self.use_file('file of size %d' % size,
                        candidates, path, hashes):
                    return

        if hashes is not None:
            look_for = None
            candidates = set()

            for c in (self.game.known_md5s.get(hashes.md5, set()) |
                    self.game.known_sha1s.get(hashes.sha1, set()) |
                    self.game.known_sha256s.get(hashes.sha256, set())):
                look_for = c
                candidates.add(self.game.files[c])

            if candidates and self.use_file('possible "%s"' % c,
                    candidates, path, hashes):
                return

            if not trusted:
                trusted = GOG.verify_checksum(path, size, hashes.md5)

        basename = os.path.basename(path)
        extension = os.path.splitext(basename)[1]
        if trusted:
            logger.warning('\n\nPlease report this unknown archive to '
                           'game-data-packager@packages.debian.org\n\n'
                           '  %-9s %s %s\n'
                           '  %s  %s\n' % (size, hashes.md5, basename, hashes.sha1, basename))
            if basename.startswith('gog_') and extension == '.sh':
                with ZipUnpacker(path) as unpacker:
                    self.consider_stream(path, unpacker)
            elif basename.startswith('setup_') and extension == '.exe':
                version = check_output(['innoextract', '-v', '-s'],
                        universal_newlines=True)
                args = ['-I', '/app'] if Version(version.split('-')[0]) >= Version('1.5') else []
                if not self.verbose:
                    args.append('--silent')
                    args.append('--progress')
                    logger.info('extracting %s (%d bytes) with InnoExtract...'
                                    % (basename, size))
                tmpdir = os.path.join(self.get_workdir(), 'tmp',
                            basename + '.d')
                mkdir_p(tmpdir)
                check_call(['innoextract',
                    '--language', 'english',
                    '-T', 'local',
                    '-d', tmpdir,
                    path] + args)
                self.consider_file_or_dir(tmpdir)
        elif really_should_match_something:
            logger.warning('file "%s" does not match any known file', path)
            # ... still G-D-P should try to process any random .zip
            # file thrown at it, like the .zip provided by GamersHell
            # or the MojoSetup installers provided by GOG.com
            if (extension.lower() in ('.zip', '.apk')
               or (basename.startswith('gog_') and extension == '.sh')):
                with ZipUnpacker(path) as unpacker:
                    self.consider_stream(path, unpacker)
            elif extension.lower() == '.deb' and which('dpkg-deb'):
                with subprocess.Popen(['dpkg-deb', '--fsys-tarfile', path],
                            stdout=subprocess.PIPE) as fsys_process:
                    with TarUnpacker(path + '//data.tar.*',
                           reader=fsys_process.stdout, compression='') as tar:
                        self.consider_stream(path, tar)

    def _log_not_any_of(self, path, size, hashes, why, candidates):
        message = ('found %s but it is not one of the expected ' +
                'versions:\n' +
                '    file:   %s\n' +
                '    size:   %d bytes\n' +
                '    md5:    %s\n' +
                '    sha1:   %s\n' +
                '    sha256: %s\n')
        args = (why, path, size, hashes.md5, hashes.sha1, hashes.sha256)

        candidates = [c for c in candidates if not c.unsuitable]

        if len(candidates) == 1:
            message += 'expected:\n'
        elif len(candidates) > 1:
            message += 'expected one of:\n'

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

    def consider_file_or_dir(self, path, provider=None):
        st = os.stat(path)

        if provider is None:
            should_provide = set()
        else:
            should_provide = set(provider.provides_files)

        if stat.S_ISREG(st.st_mode):
            self.consider_file(path, True)
        elif stat.S_ISDIR(st.st_mode):
            for dirpath, dirnames, filenames in os.walk(path):
                for fn in filenames:
                    self.consider_file(os.path.join(dirpath, fn), False)
        elif stat.S_ISBLK(st.st_mode):
            if self.game.rip_cd_packages:
                self.cd_device = path
            else:
                logger.warning('"%s" does not have a package containing CD '
                        'audio, ignoring block device "%s"',
                        self.game.shortname, path)
        else:
            logger.warning('file "%s" does not exist or is not a file, ' +
                    'directory or CD block device', path)

        for missing in sorted(f.name for f in should_provide):
            if missing not in self.found:
                logger.error('%s should have provided %s but did not',
                        self.found[provider.name], missing)

    def fill_gaps(self, package, download=False, log=True, recheck=False):
        """Return a FillResult.
        """
        assert package is not None

        logger.debug('trying to fill any gaps for %s', package.name)

        # this is redundant, it's only done to get the debug messages first
        for wanted in package.install_files:
            if wanted.name not in self.found:
                for alt in wanted.alternatives:
                    if alt in self.found:
                        break
                else:
                    logger.debug('gap needs to be filled for %s: %s',
                            package.name, wanted.name)

        result = FillResult.COMPLETE

        # search first for files that have only one provider,
        # to avoid extraneous downloads
        unique_provider = list()
        multi_provider = list()
        for wanted in (package.install_files | package.optional_files):
            if len(self.game.providers.get(wanted.name,[])) == 1:
                unique_provider.append(wanted)
            else:
                multi_provider.append(wanted)

        for wanted in unique_provider + multi_provider:
            if wanted.name not in self.found:
                # updates file_status as a side-effect
                self.fill_gap(package, wanted, download=download,
                        recheck=recheck,
                        log=(log and wanted in package.install_files))

            logger.debug('%s: %s', wanted.name, self.file_status[wanted.name])

            if wanted in package.install_files:
                # it is mandatory
                result &= self.file_status[wanted.name]

        self.package_status[package.name] = result
        logger.debug('%s: %s', package.name, result)
        return result

    def consider_stream(self, name, unpacker, provider=None):
        if provider is None:
            try_to_unpack = self.game.files
            should_provide = set()
            distinctive_dirs = False
        else:
            try_to_unpack = set(f.name for f in provider.provides_files)
            should_provide = set(try_to_unpack)
            distinctive_dirs = provider.unpack.get('distinctive_dirs', True)

        for entry in unpacker:
            if not entry.is_extractable or not entry.is_regular_file:
                continue

            for filename in try_to_unpack:
                wanted = self.game.files.get(filename)

                if wanted is None:
                    continue

                if wanted.alternatives:
                    continue

                if wanted.size not in (None, entry.size):
                    continue

                match_path = '/' + entry.name.lower()

                for lf in wanted.look_for:
                    if not distinctive_dirs:
                        lf = os.path.basename(lf)

                    if match_path.endswith('/' + lf):
                        # use this one
                        break
                else:
                    # proceed to next entry
                    continue

                should_provide.discard(filename)

                if filename in self.found:
                    continue

                entryfile = unpacker.open(entry)

                tmp = os.path.join(self.get_workdir(),
                        'tmp', wanted.name)
                tmpdir = os.path.dirname(tmp)
                mkdir_p(tmpdir)

                wf = open(tmp, 'wb')

                hf = HashedFile.from_file(
                        name + '//' + entry.name, entryfile, wf,
                        size=entry.size,
                        progress=self.progress_factory(
                            info='extracting %s from %s' % (entry.name, name)),
                        )
                wf.close()

                if entry.mtime is not None:
                    orig_time = entry.mtime
                elif provider is not None:
                    orig_name = self.found[provider.name]
                    orig_time = os.stat(orig_name).st_mtime
                else:
                    orig_time = None

                if orig_time is not None:
                    os.utime(tmp, (orig_time, orig_time))

                if not self.use_file(wanted.name, (wanted,), tmp, hf):
                    os.remove(tmp)

        if should_provide:
            for missing in sorted(should_provide):
                logger.error('%s should have provided %s but did not',
                        name, missing)

    def cat_files(self, package, provider, wanted):
        other_parts = provider.unpack['other_parts']
        for p in other_parts:
            self.fill_gap(package, self.game.files[p], download=False, log=True)
            if p not in self.found:
                # can't concatenate: one of the bits is missing
                break
        else:
            # we didn't break, so we have all the bits
            path = os.path.join(self.get_workdir(), 'tmp',
                    wanted.name)
            mkdir_p(os.path.dirname(path))
            with open(path, 'wb') as writer:
                def open_files():
                    yield open(self.found[provider.name], 'rb')
                    for p in other_parts:
                        yield open(self.found[p], 'rb')

                hasher = HashedFile.from_concatenated_files(wanted.name,
                        open_files(), writer, size=wanted.size,
                        progress=self.progress_factory(info='building %s' %
                            wanted.name),
                        )
            orig_time = os.stat(self.found[provider.name]).st_mtime
            os.utime(path, (orig_time, orig_time))
            self.use_file(wanted.name, (wanted,), path, hasher)

    def fill_gap(self, package, wanted, download=False, log=True, recheck=False):
        """Try to unpack, download or otherwise obtain wanted.

        If download is true, we may attempt to download wanted or a
        file that will provide it.

        Return a FillResult.
        """
        if wanted.name in self.found:
            assert self.file_status[wanted.name] is FillResult.COMPLETE
            return FillResult.COMPLETE

        if self.file_status[wanted.name] is FillResult.IMPOSSIBLE and not recheck:
            return FillResult.IMPOSSIBLE

        if (self.file_status[wanted.name] is FillResult.DOWNLOAD_NEEDED and
                not download):
            return FillResult.DOWNLOAD_NEEDED

        logger.debug('could not find %s, trying to derive it...', wanted.name)

        self.file_status[wanted.name] = FillResult.IMPOSSIBLE

        if wanted.alternatives:
            for alt in wanted.alternatives:
                self.file_status[wanted.name] |= self.fill_gap(package,
                  self.game.files[alt], download=download, log=False,
                  recheck=recheck)
                if alt in self.found:
                    assert self.file_status[alt] is FillResult.COMPLETE
                    assert self.file_status[wanted.name] is FillResult.COMPLETE
                    return FillResult.COMPLETE

            if self.file_status[wanted.name] is FillResult.IMPOSSIBLE and log:
                logger.error('could not find a suitable version of %s:',
                        wanted.name)

                for alt in wanted.alternatives:
                    alt = self.game.files[alt]
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

                tmpdir = self.save_downloads or os.path.dirname(self.get_workdir())
                statvfs = os.statvfs(tmpdir)
                if wanted.size > statvfs.f_frsize * statvfs.f_bavail:
                    logger.error("Out of space on %s, can't download %s.",
                                  tmpdir, wanted.name)
                    self.download_failed |= set(choose_mirror(wanted))
                    return FillResult.IMPOSSIBLE

                urls = choose_mirror(wanted)
                for url in urls:
                    if url in self.download_failed:
                        logger.debug('... no, it already failed')
                        continue

                    logger.debug('... %s', url)

                    tmp = None
                    try:
                        rf = urllib.request.urlopen(urllib.request.Request(
                                         url,headers={'User-Agent': AGENT}))
                        if rf is None:
                            continue

                        try:
                            size = int(rf.info().get('Content-Length'))
                        except:
                            size = None
                        if size and size != wanted.size:
                            logger.warning("File doesn't have expected size"
                                           " (%s vs %s), skipping %s",
                                           size, wanted.size, url)
                            continue

                        if self.save_downloads is not None:
                            tmp = os.path.join(self.save_downloads,
                                    wanted.name)
                        else:
                            tmp = os.path.join(self.get_workdir(),
                                    'tmp', wanted.name)
                            mkdir_p(os.path.dirname(tmp))

                        wf = open(tmp, 'wb')
                        logger.info('downloading %s', url)
                        hf = HashedFile.from_file(url, rf, wf,
                                size=wanted.size,
                                progress=self.progress_factory())
                        wf.close()

                        if self.use_file(wanted.name, (wanted,), tmp, hf):
                            assert self.found[wanted.name] == tmp
                            assert (self.file_status[wanted.name] ==
                                    FillResult.COMPLETE)
                            return FillResult.COMPLETE
                        else:
                            # file corrupted or something
                            os.remove(tmp)
                    except Exception as e:
                        logger.warning('Failed to download "%s": %s', url,
                                e)
                        self.download_failed.add(url)
                        if tmp is not None:
                            os.remove(tmp)

        providers = list(self.game.providers.get(wanted.name, ()))

        # pick smallest possible provider to download
        # example: this huge archive is a superset of the smaller one
        # 103M /var/www/html/ETQW-client-1.4-1.5-update.x86.run
        # 531M /var/www/html/ETQW-client-1.5-full.x86.run
        if len(providers) > 1:
            sizes = dict()
            for provider_name in providers:
                sizes[provider_name] = self.game.files[provider_name].size or 0
            providers = sorted(sizes, key=sizes.get)

        for provider_name in providers:
            provider = self.game.files[provider_name]

            # don't bother if we wouldn't be able to unpack it anyway
            if not self.check_unpacker(provider):
                continue

            # recurse to unpack or (see whether we can) download the provider
            provider_status = self.fill_gap(package, provider,
                    download=download, log=log)

            # ... and it's other parts
            if (provider_status is FillResult.COMPLETE
                and provider.unpack
                and 'other_parts' in provider.unpack):
                for p in provider.unpack['other_parts']:
                    part_status = self.fill_gap(package, self.game.files[p],
                                                download=False, log=True)
                    logger.debug('other part "%s" is %s' % (p, part_status))
                    provider_status &= part_status

            if provider_name in self.unpack_tried:
                logger.debug('already tried unpacking provider %s',
                        provider_name)
            elif provider_status is FillResult.COMPLETE:
                found_name = self.found[provider_name]
                logger.debug('trying provider %s found at %s',
                        provider_name, found_name)
                fmt = provider.unpack['format']

                self.unpack_tried.add(provider_name)

                if self.verbose and fmt in ('zip', 'unzip'):
                    with zipfile.ZipFile(found_name, 'r') as zf:
                        encoding = provider.unpack.get('encoding', 'cp437')
                        if zf.comment:
                            comment = zf.comment.decode(encoding, 'replace')
                            try:
                                print(comment)
                            except UnicodeError:
                                print(comment.encode('ascii', 'replace').decode('ascii'))
                        if 'FILE_ID.DIZ' in zf.namelist():
                            id_diz = ''
                            try:
                                entryfile = zf.open('FILE_ID.DIZ')
                                id_diz = entryfile.read().decode(encoding, 'replace')
                            except NotImplementedError:
                                if which('unzip'):
                                    id_diz = check_output(['unzip', '-c','-q',
                                        found_name, 'FILE_ID.DIZ']
                                        ).decode(encoding, 'replace')
                            try:
                                print(id_diz)
                            except UnicodeError:
                                print(id_diz.encode('ascii', 'replace').decode('ascii'))

                if fmt == 'dos2unix':
                    tmp = os.path.join(self.get_workdir(),
                            'tmp', wanted.name)
                    tmpdir = os.path.dirname(tmp)
                    mkdir_p(tmpdir)

                    rf = open(found_name, 'rb')
                    contents = rf.read()
                    wf = open(tmp, 'wb')
                    wf.write(contents.replace(b'\r\n', b'\n'))

                    orig_time = os.stat(found_name).st_mtime
                    os.utime(tmp, (orig_time, orig_time))
                    self.use_file(wanted.name, (wanted,), tmp, None)
                elif fmt in ('tar.*', 'tar.gz', 'tar.bz2', 'tar.xz'):
                    reader = open(found_name, 'rb')
                    with TarUnpacker(found_name, reader, compression=fmt[4:],
                            skip=provider.unpack.get('skip', 0)) as tar:
                        self.consider_stream(found_name, tar, provider)
                elif fmt == 'deb':
                    with subprocess.Popen(['dpkg-deb', '--fsys-tarfile', found_name],
                                stdout=subprocess.PIPE) as fsys_process:
                        with TarUnpacker(found_name + '//data.tar.*',
                                fsys_process.stdout, compression='') as tar:
                            self.consider_stream(found_name, tar, provider)
                elif fmt == 'zip':
                    if provider.name.startswith('gog_'):
                        package.used_sources.add(provider.name)
                    with ZipUnpacker(found_name) as unpacker:
                        self.consider_stream(found_name, unpacker, provider)
                elif fmt == 'lha':
                    to_unpack = provider.unpack.get('unpack',
                            [f.name for f in provider.provides_files])
                    logger.debug('Extracting %r from %s',
                            to_unpack, found_name)
                    tmpdir = os.path.join(self.get_workdir(), 'tmp',
                            provider_name + '.d')
                    mkdir_p(tmpdir)
                    arg = 'x' if self.verbose else 'xq'
                    check_call(['lha', arg, os.path.abspath(found_name)] +
                            list(to_unpack),
                            cwd=tmpdir)
                    self.consider_file_or_dir(tmpdir, provider=provider)
                elif fmt == 'id-shr-extract':
                    to_unpack = provider.unpack.get('unpack',
                            [f.name for f in provider.provides_files])
                    logger.debug('Extracting %r from %s',
                            to_unpack, found_name)
                    tmpdir = os.path.join(self.get_workdir(), 'tmp',
                            provider_name + '.d')
                    mkdir_p(tmpdir)
                    check_call(['id-shr-extract', os.path.abspath(found_name)],
                            cwd=tmpdir)
                    # this format doesn't store a timestamp, so the extracted
                    # files will instead inherit the archive's timestamp
                    recursive_utime(tmpdir, os.stat(found_name).st_mtime)
                    self.consider_file_or_dir(tmpdir, provider=provider)
                elif fmt == 'cabextract':
                    to_unpack = provider.unpack.get('unpack',
                            [f.name for f in provider.provides_files])
                    logger.debug('Extracting %r from %s',
                            to_unpack, found_name)
                    tmpdir = os.path.join(self.get_workdir(), 'tmp',
                            provider_name + '.d')
                    mkdir_p(tmpdir)
                    quiet = [] if self.verbose else ['-q']
                    check_call(['cabextract'] + quiet + ['-L',
                            os.path.abspath(found_name)], cwd=tmpdir)
                    self.consider_file_or_dir(tmpdir, provider=provider)
                elif fmt == 'unace-nonfree':
                    to_unpack = provider.unpack.get('unpack',
                            [f.name for f in provider.provides_files])
                    logger.debug('Extracting %r from %s',
                            to_unpack, found_name)
                    tmpdir = os.path.join(self.get_workdir(), 'tmp',
                            provider_name + '.d')
                    mkdir_p(tmpdir)
                    check_call(['unace', 'x',
                             os.path.abspath(found_name)] +
                             list(to_unpack), cwd=tmpdir)
                    self.consider_file_or_dir(tmpdir, provider=provider)
                elif fmt == 'unrar-nonfree':
                    to_unpack = provider.unpack.get('unpack',
                            [f.name for f in provider.provides_files])
                    logger.debug('Extracting %r from %s',
                            to_unpack, found_name)
                    tmpdir = os.path.join(self.get_workdir(), 'tmp',
                            provider_name + '.d')
                    mkdir_p(tmpdir)
                    quiet = [] if self.verbose else ['-inul']
                    check_call(['unrar-nonfree', 'x'] + quiet +
                             [os.path.abspath(found_name)] +
                             list(to_unpack), cwd=tmpdir)
                    self.consider_file_or_dir(tmpdir, provider=provider)
                elif fmt == 'innoextract':
                    if 'unpack' in provider.unpack:
                        to_unpack = provider.unpack['unpack']
                    else:
                        # this will result in extraneous "-I <file>" parameters,
                        # but innoextract doesn't care
                        to_unpack = set()
                        for f in provider.provides_files:
                            to_unpack.add(f.name.split('?')[0])
                            for l in f.look_for:
                                to_unpack.add(l)
                    to_unpack = sorted(to_unpack)
                    logger.debug('Extracting %r from %s', to_unpack, found_name)
                    package.used_sources.add(provider.name)
                    tmpdir = os.path.join(self.get_workdir(), 'tmp',
                                          provider_name + '.d')
                    mkdir_p(tmpdir)
                    cmdline = ['innoextract',
                               '--language', 'english',
                               '-T', 'local',
                               '-d', tmpdir,
                               os.path.abspath(found_name)]
                    if not self.verbose:
                        cmdline.append('--silent')
                        cmdline.append('--progress')
                    version = check_output(['innoextract', '-v', '-s'],
                            universal_newlines=True)
                    if Version(version.split('-')[0]) >= Version('1.5'):
                        prefix = provider.unpack.get('prefix', '')
                        if prefix and not prefix.endswith('/'):
                            prefix += '/'
                        if '$provides' in to_unpack:
                            to_unpack.remove('$provides')
                            to_unpack += [f.name for f in provider.provides_files]
                        for i in to_unpack:
                            cmdline.append('-I')
                            if prefix and i[0] != '/':
                                i = prefix + i
                            cmdline.append(i)
                    check_call(cmdline)
                    self.consider_file_or_dir(tmpdir, provider=provider)
                elif fmt == 'unzip' and which('unzip'):
                    to_unpack = provider.unpack.get('unpack',
                            [f.name for f in provider.provides_files])
                    logger.debug('Extracting %r from %s',
                            to_unpack, found_name)
                    tmpdir = os.path.join(self.get_workdir(), 'tmp',
                            provider_name + '.d')
                    mkdir_p(tmpdir)
                    quiet = ['-q'] if self.verbose else ['-qq']
                    check_call(['unzip', '-j', '-C'] +
                                quiet + [os.path.abspath(found_name)] +
                            list(to_unpack), cwd=tmpdir)
                    # -j junk paths
                    # -C use case-insensitive matching
                    self.consider_file_or_dir(tmpdir, provider=provider)
                elif fmt in ('7z', 'unzip'):
                    to_unpack = provider.unpack.get('unpack',
                            [f.name for f in provider.provides_files])
                    logger.debug('Extracting %r from %s',
                            to_unpack, found_name)
                    tmpdir = os.path.join(self.get_workdir(), 'tmp',
                            provider_name + '.d')
                    mkdir_p(tmpdir)
                    flags = provider.unpack.get('flags', [])
                    if not self.verbose:
                        flags.append('-bd')
                    check_call(['7z', 'x'] + flags +
                                [os.path.abspath(found_name)] +
                                list(to_unpack), cwd=tmpdir)
                    self.consider_file_or_dir(tmpdir, provider=provider)
                elif fmt in ('unar', 'unzip'):
                    to_unpack = provider.unpack.get('unpack',
                            [f.name for f in provider.provides_files])
                    logger.debug('Extracting %r from %s', to_unpack, found_name)
                    tmpdir = os.path.join(self.get_workdir(), 'tmp',
                            provider_name + '.d')
                    mkdir_p(tmpdir)
                    quiet = [] if self.verbose else ['-q']
                    check_call(['unar', '-D'] +
                               quiet + [os.path.abspath(found_name)] +
                               list(to_unpack), cwd=tmpdir)
                    self.consider_file_or_dir(tmpdir, provider=provider)
                elif fmt == 'unshield':
                    to_unpack = provider.unpack.get('unpack',
                            [f.name for f in provider.provides_files])
                    logger.debug('Extracting %r from %s', to_unpack, found_name)
                    tmpdir = os.path.join(self.get_workdir(), 'tmp',
                                          provider_name + '.d')
                    mkdir_p(tmpdir)
                    # we can't specify individual files to extract
                    # but we can narrow down to 'groups'
                    groups = provider.unpack.get('groups')
                    if groups:
                        # unshield only take last '-g' into account
                        for group in groups:
                            check_call(['unshield', '-g', group,
                               'x', os.path.abspath(found_name)], cwd=tmpdir)
                    else:
                        check_call(['unshield', 'x',
                                 os.path.abspath(found_name)], cwd=tmpdir)

                    # this format doesn't store a timestamp, so the extracted
                    # files will instead inherit the archive's timestamp
                    recursive_utime(tmpdir, os.stat(found_name).st_mtime)
                    self.consider_file_or_dir(tmpdir, provider=provider)
                elif fmt == 'arj':
                    to_unpack = provider.unpack.get('unpack',
                            [f.name for f in provider.provides_files])
                    logger.debug('Extracting %r from %s',
                                 to_unpack, found_name)
                    tmpdir = os.path.join(self.get_workdir(), 'tmp',
                                          provider_name + '.d')
                    mkdir_p(tmpdir)
                    check_call(['arj', 'e',
                                  os.path.abspath(found_name)] +
                                  list(to_unpack), cwd=tmpdir)
                    for p in provider.unpack.get('other_parts', []):
                        check_call(['arj', 'e', '-jya',
                                  os.path.join(os.path.dirname(found_name),p)] +
                                  list(to_unpack), cwd=tmpdir)
                    self.consider_file_or_dir(tmpdir, provider=provider)
                elif fmt == 'cat':
                    self.cat_files(package, provider, wanted)

                elif fmt == 'xdelta':
                    # provider (found_name) is the delta
                    # other_parts contains only the base (unpatched) file
                    # wanted is the patched file
                    assert len(provider.unpack['other_parts']) == 1
                    basis = self.game.files[provider.unpack['other_parts'][0]]
                    if basis.name in self.found:
                        out_path = os.path.join(self.get_workdir(), 'tmp',
                                wanted.name)
                        mkdir_p(os.path.dirname(out_path))
                        check_call(['xdelta', 'patch', found_name,
                            self.found[basis.name], out_path])
                        orig_time = os.stat(found_name).st_mtime
                        os.utime(out_path, (orig_time, orig_time))
                        self.use_file(wanted.name, (wanted,), out_path)

                elif fmt == 'umod':
                    with Umod(found_name) as unpacker:
                        self.consider_stream(found_name, unpacker, provider)

                if wanted.name in self.found:
                    assert (self.file_status[wanted.name] ==
                            FillResult.COMPLETE)
                    return FillResult.COMPLETE
            elif wanted.size == 0:
                self.use_file(wanted.name, (wanted,), '/dev/null')
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
        for wanted in package.install_files:
            if wanted.name in self.found:
                continue

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

    def fill_docs(self, package, destdir, pkgdocdir):
        copy_to = os.path.join(destdir, pkgdocdir, 'copyright')
        for n in (package.name, self.game.shortname):
            copy_from = os.path.join(DATADIR, n + '.copyright')
            if os.path.exists(copy_from):
                shutil.copyfile(copy_from, copy_to)
                return

            if os.path.exists(copy_from + '.in'):
                copy_with_substitutions(open(copy_from + '.in',
                            encoding='utf-8'),
                        open(copy_to, 'w', encoding='utf-8'),
                        PACKAGE=package.name)
                return

        copy_from = os.path.join(DATADIR, 'copyright')
        with open(copy_from, encoding='utf-8') as i, \
             open(copy_to, 'w', encoding='utf-8') as o:
            o.write('The package %s was generated using '
                    'game-data-packager.\n' % package.name)

            licenses = set()
            for f in (package.install_files | package.optional_files):
                 if self.file_status[f.name] is not FillResult.COMPLETE:
                     continue
                 if not f.license:
                     continue
                 license_file = f.install_as
                 licenses.add("/%s/%s/%s" % (self.packaging.LICENSEDIR,
                     package.name, license_file))
                 if os.path.splitext(license_file)[0].lower() == 'license':
                     self.packaging.override_lintian(destdir, package.name,
                             'extra-license-file',
                             'usr/share/doc/%s/%s' % (package.name,
                                 license_file))

            if package.component == 'local':
                o.write('It contains proprietary game data '
                        'and must not be redistributed.\n\n')
            elif package.component == 'non-free':
                o.write('It contains proprietary game data '
                        'that may be redistributed\n'
                        'only under conditions specified in\n')
                o.write(',\n'.join(licenses) + '.\n\n')
            else:
                o.write('It contains free game data and may be\n'
                        'redistributed under conditions specified in\n')
                o.write(',\n'.join(licenses) + '.\n\n')


            notice = package.copyright_notice or self.game.copyright_notice
            if notice:
                 o.write('-' * 70)
                 o.write('\n\n' + notice + '\n')
                 o.write('-' * 70 + '\n\n')

            count_usr = 0
            exts = set()
            count_doc = 0
            for f in (package.install_files | package.optional_files):
                 if self.file_status[f.name] is FillResult.IMPOSSIBLE:
                     continue
                 install_to = f.install_to
                 if install_to and install_to.startswith('$pkgdocdir'):
                     count_doc +=1
                 elif install_to and install_to.startswith('$pkglicensedir'):
                     pass
                 else:
                     count_usr +=1
                     # doesn't have to be a .wad, ROTT's EXTREME.RTL
                     # or any other one-datafile .deb would qualify too
                     main_wad = f.install_as
                     exts.add(os.path.splitext(main_wad.lower())[1])

            install_to = self.packaging.substitute(package.install_to,
                    package.name)

            if count_usr == 0 and count_doc == 1:
                o.write('"/usr/share/doc/%s/%s"\n' % (package.name,
                                                      package.only_file))
            elif count_usr == 1:
                o.write('"/%s/%s"\n' % (install_to, main_wad))
            elif len(exts) == 1:
                o.write('The %s files under "/%s/"\n' %
                        (list(exts)[0], install_to))
            else:
                o.write('The files under "/%s/"\n' % install_to)

            if count_usr and count_doc:
                if count_usr == 1:
                    o.write('and the files under "/usr/share/doc/%s/"\n' % package.name)
                else:
                    o.write('and "/usr/share/doc/%s/"\n' % package.name)
                o.write('(except for this copyright file & changelog.gz)\n')

            if (count_usr + count_doc) == 1:
                o.write('is a user-supplied file with copyright\n')
            else:
                o.write('are user-supplied files with copyright\n')

            o.write(package.copyright or self.game.copyright)
            o.write(', with all rights reserved.\n')

            if licenses and package.component == 'local':
                o.write('\nThe full license appears in ')
                o.write(',\n'.join(licenses))
                o.write('\n')

            for line in i.readlines():
                if line.startswith('#'):
                    continue
                o.write(line)


    def fill_extra_files(self, package, destdir):
        pass

    def fill_dest_dir_arch(self, package, destdir, compress, arch):
        PKGINFO = os.path.join(destdir, '.PKGINFO')
        short_desc, _ = self.generate_description(package)
        size = check_output(['du','-bs','.'], cwd=destdir)
        size = int(size.split()[0])
        with open(PKGINFO, 'w',  encoding='utf-8') as pkginfo:
            pkginfo.write('# Generated by game-data-packager %s\n' % package.version.split('+')[-1])
            pkginfo.write('# using fakeroot version %s\n' %
                    self.packaging.current_version('fakeroot'))
            pkginfo.write('# %s\n' % time.strftime("%a %b %d %H:%M:%S UTC %Y", time.gmtime()))
            pkginfo.write('pkgname = %s\n' % package.name)
            pkginfo.write('pkgver = %s-1\n' % package.version)
            pkginfo.write('pkgdesc = %s\n' % short_desc)
            pkginfo.write('url = https://wiki.debian.org/Games/GameDataPackager\n')
            pkginfo.write('builddate = %i\n' % int(time.time()))
            pkginfo.write('packager = Alexandre Detiste <alexandre@detiste.be>\n')
            pkginfo.write('size = %i\n' % size)
            pkginfo.write('arch = %s\n' % arch)
            if os.path.isdir(os.path.join(destdir, 'usr/share/licenses')):
                pkginfo.write('license = custom\n')
            pkginfo.write('group = games\n')
            if package.expansion_for:
                pkginfo.write('depend = %s\n' % package.expansion_for)
            else:
                engine = self.packaging.substitute(
                        package.engine or self.game.engine,
                        package.name)

                if engine and len(engine.split()) == 1:
                    pkginfo.write('depend = %s\n' % engine)

        files = set()
        for dirpath, dirnames, filenames in os.walk(destdir):
                for fn in filenames:
                    full = os.path.join(dirpath, fn)
                    full = full[len(destdir)+1:]
                    files.add(full)

        MTREE = os.path.join(destdir, '.MTREE')
        subprocess.check_call(['fakeroot', 'bsdtar', '-czf', MTREE, '--format=mtree',
                 '--options=!all,use-set,type,uid,gid,mode,time,size,md5,sha256,link']
                 + sorted(files), env={'LANG':'C'}, cwd=destdir)

    def __merge_relations(self, package, rel):
        return set(self.packaging.format_relations(package.relations[rel]))

    def fill_dest_dir_rpm(self, package, destdir, compress, architecture, release):
        specfile = os.path.join(self.get_workdir(), '%s.spec' % package.name)
        short_desc, long_desc = self.generate_description(package)
        short_desc = short_desc[0].upper() + short_desc[1:]

        if self.game.wikibase:
            url = self.game.wikibase + (self.game.wiki or '')
        elif self.game.wikipedia:
            url = self.game.wikipedia
        else:
            url = 'https://wiki.debian.org/Games/GameDataPackager'

        # /usr/games & /usr/share/games should only
        # be seen in rpm's built for Mageia
        SYSTEM_DIRS = set(['/usr',
                           '/usr/bin',
                           '/usr/games',
                           '/usr/lib',
                           '/usr/share',
                           '/usr/share/applications',
                           '/usr/share/doc',
                           '/usr/share/doc/packages',
                           '/usr/share/games',
                           '/usr/share/icons',
                           '/usr/share/icons/hicolor',
                           '/usr/share/icons/hicolor/scalable',
                           '/usr/share/icons/hicolor/scalable/apps',
                           '/usr/share/licenses',
                           '/usr/share/pixmaps'])

        files = set()
        for dirpath, dirnames, filenames in os.walk(destdir):
             dir = dirpath[len(destdir):]
             if not dir:
                 # /
                 continue
             elif dir in SYSTEM_DIRS:
                 for fn in filenames + dirnames:
                     full = os.path.join(dirpath, fn)
                     file = full[len(destdir):]
                     if file not in SYSTEM_DIRS:
                         files.add(file)
             else:
                 for file in files:
                     if dir.startswith(file):
                         break
                 else:
                     files.add(dir)

        logger.debug('%%files in specfile:\n%s', '\n'.join(sorted(files)))

        with open(specfile, 'w', encoding='utf-8') as spec:
            spec.write('Summary: %s\n' % short_desc)
            spec.write('Name: %s\n' % package.name)
            spec.write('Version: %s\n' % package.version)
            spec.write('Url: %s\n' % url)
            spec.write('Release: %s\n' % release)
            spec.write('License: Commercial\n')
            if DISTRO == 'mageia':
                spec.write('Packager: game-data-packager\n')
                spec.write('Group: Games/%s\n' % self.game.genre)
            else:
                spec.write('Group: Amusements/Games\n')
            spec.write('BuildArch: %s\n' % architecture)

            for p in self.__merge_relations(package, 'provides'):
                spec.write('Provides: %s\n' % p)

                if package.mutually_exclusive:
                    spec.write('Conflicts: %s\n' % p)

            if package.expansion_for:
                spec.write('Requires: %s\n' % package.expansion_for)
            else:
                engine = self.packaging.substitute(
                        package.engine or self.game.engine,
                        package.name)

                if engine and len(engine.split()) == 1:
                    spec.write('Requires: %s\n' % engine)

            for p in self.__merge_relations(package, 'depends'):
                spec.write('Requires: %s\n' % p)

            for p in (self.__merge_relations(package, 'conflicts') |
                    self.__merge_relations(package, 'breaks')):
                spec.write('Conflicts: %s\n' % p)

            for p in self.__merge_relations(package, 'recommends'):
                # FIXME: some RPM distributions do have recommends;
                # which ones?
                pass

            for p in self.__merge_relations(package, 'suggests'):
                # FIXME: likewise
                pass

            # FIXME: replaces?

            if not compress or not self.compress_deb or package.rip_cd:
                spec.write('%define _binary_payload w0.gzdio\n')
            elif self.compress_deb == ['-Zgzip', '-z1']:
                spec.write('%define _binary_payload w1.gzdio\n')
            spec.write('%description\n')
            spec.write('%s\n' % long_desc)
            spec.write('%files\n')
            spec.write('\n'.join(files))
            spec.write('\n\n')

            spec.write('%changelog\n')
            try:
                login = os.getlogin()
            except FileNotFoundError:
                login = 'game-data-packager'
            spec.write('* %s %s@%s - %s-%s\n' %
                        (time.strftime("%a %b %d %Y", time.gmtime()),
                         login, os.uname()[1], package.version, release))
            spec.write('- Package generated by game-data-packager'
                       ' for local use only\n')

        return specfile

    def fill_dest_dir_deb(self, package, destdir):
        if package.component == 'local':
             self.packaging.override_lintian(destdir, package.name,
                     'unknown-section', 'local/%s' % package.section)

        # same output as in dh_md5sums

        # we only compute here the md5 we don't have yet,
        # for the (small) GDP-generated files
        for dirpath, dirnames, filenames in os.walk(destdir):
            if os.path.basename(dirpath) == 'DEBIAN':
                continue
            for fn in filenames:
                full = os.path.join(dirpath, fn)
                if os.path.islink(full):
                    continue
                file = full[len(destdir)+1:]
                if file not in package.md5sums:
                    with open(full, 'rb') as opened:
                        hf = HashedFile.from_file(full, opened)
                        package.md5sums[file] = hf.md5

        debdir = os.path.join(destdir, 'DEBIAN')
        mkdir_p(debdir)
        md5sums = os.path.join(destdir, 'DEBIAN/md5sums')
        with open(md5sums, 'w', encoding='utf8') as outfile:
            for file in sorted(package.md5sums.keys()):
                outfile.write('%s  %s\n' % (package.md5sums[file], file))
        os.chmod(md5sums, 0o644)

        try:
            control_in = open(self.get_control_template(package),
                    encoding='utf-8')
            control = Deb822(control_in)
        except FileNotFoundError:
            control = Deb822()
        self.modify_control_template(control, package, destdir)
        control.dump(fd=open(os.path.join(debdir, 'control'), 'wb'),
                encoding='utf-8')
        os.chmod(os.path.join(debdir, 'control'), 0o644)

    def fill_dest_dir(self, package, destdir):
        if not self.check_complete(package, log=True):
            return False

        pkgdocdir = os.path.join(self.packaging.DOCDIR, package.name)
        dest_pkgdocdir = os.path.join(destdir, pkgdocdir)
        mkdir_p(dest_pkgdocdir)
        shutil.copyfile(os.path.join(DATADIR, 'changelog.gz'),
                os.path.join(destdir, pkgdocdir, 'changelog.gz'))

        self.fill_docs(package, destdir, pkgdocdir)

        for wanted in (package.install_files | package.optional_files):
            install_as = wanted.install_as

            if wanted.name in self.found:
                copy_from = self.found[wanted.name]
                md5 = wanted.md5
            else:
                for alt in wanted.alternatives:
                    if alt in self.found:
                        copy_from = self.found[alt]
                        md5 = self.game.files[alt].md5
                        if wanted.install_as == '$alternative':
                            install_as = self.game.files[alt].install_as
                        break
                else:
                    if wanted not in package.install_files:
                        logger.debug('optional file %r is missing, ignoring',
                                wanted.name)
                        continue

                    raise AssertionError('we already checked that %s exists' %
                            (wanted.name))

            # cp it into place
            with TemporaryUmask(0o22):
                logger.debug('Found %s at %s', wanted.name, copy_from)

                install_to = self.packaging.substitute(package.install_to,
                        package.name).lstrip('/')

                if wanted.install_to is not None:
                    install_to = self.packaging.substitute(wanted.install_to,
                            package.name, install_to=install_to)

                copy_to = os.path.join(destdir, install_to, install_as)
                copy_to_dir = os.path.dirname(copy_to)
                logger.debug('Copying to %s', copy_to)
                if not os.path.isdir(copy_to_dir):
                    mkdir_p(copy_to_dir)
                # Use cp(1) so we can make a reflink if source and
                # destination happen to be the same btrfs volume
                subprocess.check_call(['cp', '--reflink=auto',
                    '--preserve=timestamps', copy_from, copy_to])

                if wanted.executable:
                    os.chmod(copy_to, 0o755)
                else:
                    os.chmod(copy_to, 0o644)

                fullname = os.path.join(install_to, install_as)
                package.md5sums[fullname] = md5

        install_to = self.packaging.substitute(package.install_to,
                package.name).lstrip('/')

        for symlink, real_file in package.symlinks.items():
            symlink = self.packaging.substitute(symlink, package.name,
                    install_to=install_to)
            real_file = self.packaging.substitute(real_file, package.name,
                    install_to=install_to)

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

        if package.rip_cd and self.cd_tracks.get(package.name):
            for i, copy_from in self.cd_tracks[package.name].items():
                logger.debug('Found CD track %d at %s', i, copy_from)
                install_as = package.rip_cd['filename_format'] % i
                copy_to = os.path.join(destdir, install_to, install_as)
                copy_to_dir = os.path.dirname(copy_to)
                if not os.path.isdir(copy_to_dir):
                    mkdir_p(copy_to_dir)
                check_call(['cp', '--reflink=auto',
                    '--preserve=timestamps', copy_from, copy_to])

        self.fill_extra_files(package, destdir)

        return True

    def our_dh_fixperms(self, destdir):
        for dirpath, dirnames, filenames in os.walk(destdir):
            for fn in filenames + dirnames:
                full = os.path.join(dirpath, fn)
                stat_res = os.lstat(full)
                if stat.S_ISLNK(stat_res.st_mode):
                    continue
                elif stat.S_ISDIR(stat_res.st_mode):
                    # make directories rwxr-xr-x
                    os.chmod(full, 0o755)
                elif (stat.S_IMODE(stat_res.st_mode) & 0o111) != 0:
                    # make executable files rwxr-xr-x
                    os.chmod(full, 0o755)
                else:
                    # make other files rw-r--r--
                    os.chmod(full, 0o644)

    def modify_control_template(self, control, package, destdir):
        for key in control.keys():
            assert key == 'Description', 'specify "%s" only in YAML' % key
        control['Package'] = package.name
        control['Version'] = package.version
        control['Priority'] = 'optional'
        control['Maintainer'] = 'Debian Games Team <pkg-games-devel@lists.alioth.debian.org>'

        installed_size = 0
        # algorithm from https://bugs.debian.org/650077 designed to be
        # filesystem-independent
        for dirpath, dirnames, filenames in os.walk(destdir):
            if dirpath == destdir and 'DEBIAN' in dirnames:
                dirnames.remove('DEBIAN')
            # estimate 1 KiB per directory
            installed_size += len(dirnames)
            for f in filenames:
                stat_res = os.lstat(os.path.join(dirpath, f))
                if (stat.S_ISLNK(stat_res.st_mode) or
                        stat.S_ISREG(stat_res.st_mode)):
                    # take the real size and round up to next 1 KiB
                    installed_size += ((stat_res.st_size + 1023) // 1024)
                else:
                    # this will probably never happen in gdp, but assume
                    # 1 KiB per non-regular, non-directory, non-symlink file
                    installed_size += 1
        control['Installed-Size'] = str(installed_size)

        if package.component == 'main':
            control['Section'] = package.section
        else:
            control['Section'] = package.component + '/' + package.section

        if package.architecture == 'all':
            control['Architecture'] = 'all'
            control['Multi-Arch'] = 'foreign'
        else:
            control['Architecture'] = self.packaging.get_architecture(package.architecture)

        dep = dict()

        for rel in package.relations:
            if rel == 'build_depends':
                continue

            dep[rel] = self.__merge_relations(package, rel)
            logger.debug('%s %s %s', package.name, rel, ', '.join(dep[rel]))

        if package.mutually_exclusive:
            dep['conflicts'] |= package.demo_for
            dep['conflicts'] |= package.better_versions

        if package.mutually_exclusive:
            dep['replaces'] |= dep['provides']

        engine = self.packaging.substitute(
                package.engine or self.game.engine,
                package.name)

        if engine and '>=' in engine:
            engine, ver = engine.split(maxsplit=1)
            ver = ver.strip('(>=) ')
            dep['breaks'].add('%s (<< %s~)' % (engine, ver))

        # We only 'recommends' & not 'depends'; to avoid
        # that GDP-generated packages get removed
        # if engine goes through some gcc/png/ffmpeg/... migration
        # and must be temporarily removed.
        # It's not like 'apt-get install ...' can revert this removal;
        # user may need to dig again for the original media....
        if package.engine:
            dep['recommends'].add(engine)
        elif not package.expansion_for and self.game.engine:
            dep['recommends'].add(engine)

        if package.expansion_for:
            # check if default heuristic has been overriden in yaml
            for p in dep['depends']:
                if package.expansion_for == p.split()[0]:
                    break
            else:
                dep['depends'].add(package.expansion_for)

        # dependencies derived from *other* package's data
        for other_package in self.game.packages.values():
            if other_package.expansion_for:
                if package.name == other_package.expansion_for:
                    dep['suggests'].add(other_package.name)
                else:
                    for p in package.relations['provides']:
                        if p.package == other_package.expansion_for:
                            dep['suggests'].add(other_package.name)

            if other_package.mutually_exclusive:
                if package.name in other_package.better_versions:
                    dep['replaces'].add(other_package.name)

                if package.name in other_package.demo_for:
                    dep['replaces'].add(other_package.name)

        # Shortcut: if A Replaces B, A automatically Conflicts B
        dep['conflicts'] |= dep['replaces']

        # keep only strongest depedency
        dep['recommends'] -= dep['depends']
        dep['suggests'] -= dep['recommends']
        dep['suggests'] -= dep['depends']

        for k, v in dep.items():
            if v:
                control[k.title()] = ', '.join(sorted(v))

        if 'Description' not in control:
            short_desc, long_desc = self.generate_description(package)
            control['Description'] = short_desc + '\n ' + long_desc.replace('\n', '\n ')

    def generate_description(self, package):
        longname = package.longname or self.game.longname

        if package.short_description is not None:
            short_desc = package.short_description
        elif package.section == 'games':
            short_desc = 'game %s for %s' % (package.data_type, longname)
        else:
            short_desc = longname

        if package.long_description is not None:
            long_desc = package.long_description
            long_desc = long_desc.rstrip('\n')
            return (short_desc, long_desc)

        long_desc =  'This package was built using game-data-packager.\n'
        if package.component == 'local':
            long_desc += 'It contains proprietary game data and must not be redistributed.\n'
            long_desc += '.\n'
        elif package.component == 'non-free':
            long_desc += 'It contains proprietary game data that may be redistributed\n'
            long_desc += 'only under some conditions.\n'
            long_desc += '.\n'
        else:
            long_desc += 'It contains free game data and may be redistributed.\n'
            long_desc += '.\n'

        if package.description:
            for line in package.description.splitlines():
                line = line.rstrip() or '.'
                long_desc += (line + '\n')
            long_desc += '.\n'

        if self.game.genre:
            long_desc += ' Genre: ' + self.game.genre + '\n'

        if package.section == 'doc':
            long_desc += ' Documentation: ' + longname + '\n'
        elif package.expansion_for and package.expansion_for in self.game.packages:
            game_name = (self.game.packages[package.expansion_for].longname
                         or self.game.longname)
            long_desc += ' Game: ' + game_name + '\n'
            long_desc += ' Expansion: ' + longname + '\n'
        else:
            long_desc += ' Game: ' + longname + '\n'

        copyright = package.copyright or self.game.copyright
        long_desc += ' Published by: ' + copyright.split(' ', 2)[2]

        engine = self.packaging.substitute(
                package.engine or self.game.engine,
                package.name)

        if engine and package.section == 'games':
            long_desc += '\n.\n'
            if '|' in engine:
                virtual = engine.split('|')[-1].strip()
                has_virtual = (virtual.split('-')[-1] == 'engine')
            else:
                has_virtual = False
            engine = engine.split('|')[0].split('(')[0].strip()
            if engine.startswith('gemrb'):
                engine = 'gemrb'
            if has_virtual:
                long_desc += 'Intended for use with some ' + virtual + ',\n'
                long_desc += 'such as for example: ' + engine
            else:
                long_desc += 'Intended for use with: ' + engine

        if package.used_sources:
            long_desc += '\nBuilt from: ' + ', '.join(package.used_sources)

        return (short_desc, long_desc)

    def get_control_template(self, package):
        return os.path.join(DATADIR, package.name + '.control.in')

    def look_for_engines(self, packages, force=False):
        engines = set()

        for p in packages:
            engines.add(self.packaging.substitute(p.engine or self.game.engine,
                    p.name))

        engines.discard(None)

        if not engines:
            return

        # XXX: handle complex cases too (e.g. Inherit the Earth DE vs EN)
        status = FillResult.UNDETERMINED
        for engine_alternative in engines:
            for engine in reversed(engine_alternative.split('|')):
                engine = engine.strip()
                status |= self.look_for_engine(engine)

        if status is FillResult.IMPOSSIBLE:
            if force:
                logger.warning('Engine "%s" is not available, '
                               'proceeding anyway' % engine)
            else:
                logger.error('Engine "%s" is not (yet) available, '
                             'aborting' % engine)
                raise SystemExit(1)
        elif status is FillResult.UPGRADE_NEEDED:
            if force:
                logger.warning('Engine "%s" is not up-to-date, '
                               'proceeding anyway' % engine)
            else:
                logger.error('Engine "%s" is not up-to-date, '
                             'aborting' % engine)
                raise SystemExit(1)

    def look_for_engine(self, engine):
        if '(' in engine:
            engine, ver = engine.split(maxsplit=1)
            ver = ver.strip('(>=) ') + BACKPORT_SUFFIX
        else:
            ver = None

        # check engine
        is_installed = self.packaging.is_installed(engine)
        if not is_installed and not self.packaging.is_available(engine):
            return FillResult.IMPOSSIBLE
        if ver is None:
            if is_installed:
                return FillResult.COMPLETE
            else:
                return FillResult.DOWNLOAD_NEEDED

        # check version
        if is_installed:
            current_ver = self.packaging.current_version(engine)
        else:
            current_ver = self.packaging.available_version(engine)

        if current_ver and Version(current_ver) >= Version(ver):
            return FillResult.COMPLETE
        else:
            return FillResult.UPGRADE_NEEDED

    def iter_extra_paths(self, packages):
        return []

    def look_for_files(self, paths=(), search=True, packages=None,
            binary_executables=False):
        paths = list(paths)

        if self.game.binary_executables:
            if not binary_executables:
                logger.error('%s requires binary-only executables which are '
                        'currently disallowed', self.game.longname)
                logger.info('Use the --binary-executables option to allow this, '
                        'at your own risk')
                raise BinaryExecutablesNotAllowed()

        if self.game.binary_executables and self.game.binary_executables != 'all':
            # 'all' means that this is well a binary without source,
            # but it can be emulated on any host architecture (e.g. DOSBox games)
            if self.packaging.get_architecture(self.game.binary_executables) not in \
                    self.game.binary_executables.split():
                logger.error('%s requires binary-only executables which are '
                        'only available for %s', self.game.longname,
                        ', '.join(self.game.binary_executables.split()))
                logger.info('If your CPU can run one of those architectures, '
                        'use dpkg --add-architecture to enable multiarch')
                raise NoPackagesPossible()

        if self.save_downloads is not None and self.save_downloads not in paths:
            paths.append(self.save_downloads)

        if packages is None:
            packages = self.game.packages.values()

        if search:
            for path in self.game.try_repack_from:
                path = os.path.expanduser(path)
                if os.path.isdir(path) and path not in paths:
                    paths.append(path)

            for package in packages:
                path = '/' + self.packaging.substitute(package.install_to,
                        package.name).lstrip('/')

                if os.path.isdir(path) and path not in paths:
                    paths.append(path)
                path = '/' + self.packaging.DOCDIR + '/' + package.name
                if os.path.isdir(path) and path not in paths:
                    paths.append(path)

            for path in self.iter_steam_paths():
                if path not in paths:
                    paths.append(path)

            for path in self.iter_gog_paths():
                if path not in paths:
                    paths.append(path)

            for path in self.iter_origin_paths():
                if path not in paths:
                    paths.append(path)

            for path in self.iter_extra_paths(packages):
                if path not in paths:
                    paths.append(path)

        for arg in paths:
            logger.debug('%s...', arg)
            self.consider_file_or_dir(arg)

    def run_command_line(self, args):
        if logging.getLogger().isEnabledFor(logging.DEBUG):
            logger.debug('package description:\n%s',
                    yaml.safe_dump(self.game.to_data(expand=False)))
            logger.debug('package description after expansion:\n%s',
                    yaml.safe_dump(self.game.to_data(expand=True)))

        self.verbose = getattr(args, 'verbose', False)

        preserve_debs = (getattr(args, 'destination', None) is not None)
        install_debs = getattr(args, 'install', True)

        if getattr(args, 'compress', None) is None:
            # default to not compressing if we aren't going to install it
            # anyway
            args.compress = preserve_debs

        self.save_downloads = args.save_downloads

        for package in self.game.packages.values():
            if args.shortname in package.aliases:
                args.shortname = package.name
                break

        if (args.shortname != self.game.shortname and
                args.shortname in self.game.packages):
            if args.packages and args.packages != [args.shortname]:
                not_the_one = [p for p in args.packages if p != args.shortname]
                logger.error('--package="%s" is not consistent with '
                        'selecting "%s"', not_the_one, args.shortname)
                raise SystemExit(1)

            args.demo = True
            args.packages = [args.shortname]
            packages = set([self.game.packages[args.shortname]])
        elif args.packages:
            args.demo = True
            packages = set()
            for p in args.packages:
                if p not in self.game.packages:
                    logger.error('--package="%s" is not part of game '
                            '"%s"', p, args.shortname)
                    raise SystemExit(1)
                packages.add(self.game.packages[p])
        else:
            # if no packages were specified, we require --demo to build
            # a demo if we have its corresponding full game
            packages = set(self.game.packages.values())

        self.look_for_engines(packages, force=not args.install)

        try:
            self.look_for_files(paths=args.paths, search=args.search,
                    packages=packages,
                    binary_executables=args.binary_executables)
        except BinaryExecutablesNotAllowed:
            raise SystemExit(1)
        except NoPackagesPossible:
            raise SystemExit(1)

        try:
            ready = self.prepare_packages(packages,
                    build_demos=args.demo, download=args.download,
                    search=args.search, log_immediately=bool(args.packages))
        except NoPackagesPossible:
            logger.error('Unable to complete any packages.')
            if self.missing_tools:
                # we already logged warnings about the files as they came up
                self.log_missing_tools()
                raise SystemExit(1)

            # probably not enough files supplied?
            # print the help text, maybe that helps the user to determine
            # what they should have added
            if not os.environ.get('DEBUG') and not os.environ.get('GDP_DEBUG'):
                self.game.argument_parser.print_help()
            raise SystemExit(1)
        except DownloadNotAllowed:
            logger.error('Unable to complete any packages because ' +
                    'downloading missing files was not allowed.')
            raise SystemExit(1)
        except DownloadsFailed:
            # we already logged an error
            logger.error('Unable to complete any packages because downloads failed.')
            raise SystemExit(1)
        except CDRipFailed:
            logger.error('Unable to rip CD audio')
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
            self.packaging.install_packages(debs, method=args.install_method,
                    gain_root=args.gain_root_command)


        engines_alt = set()

        for p in ready:
            engines_alt.add(self.packaging.substitute(p.engine or self.game.engine,
                    p.name))

        engines_alt.discard(None)
        engines = set()

        for engine_alt in engines_alt:
            for engine in reversed(engine_alt.split('|')):
                engine = engine.split('(')[0].strip()
                if self.packaging.is_installed(engine):
                    break
            else:
                engines.add(engine)

        if engines:
            print('it is recommended to also install this game engine: %s' % ', '.join(engines))

        if logger.isEnabledFor(logging.DEBUG) and which(self.packaging.CHECK_CMD):
            print('Now running %s...' % self.packaging.CHECK_CMD.title())
            for deb in debs:
                subprocess.call([self.packaging.CHECK_CMD, deb])

    def rip_cd(self, package):
        cd_device = self.cd_device
        if cd_device is None:
            cd_device = '/dev/cdrom'

        logger.info('Ripping CD tracks %d+ from %s for %s',
                package.rip_cd.get('first_track', 2), cd_device, package.name)

        assert package.rip_cd['encoding'] == 'vorbis', package.name
        for tool in ('cdparanoia', 'oggenc'):
            if which(tool) is None:
                logger.error('cannot rip CD "%s" for package "%s": ' +
                        '%s is not installed', cd_device, package.name,
                        tool)
                raise CDRipFailed()

        mkdir_p(os.path.join(self.get_workdir(), 'tmp'))
        tmp_wav = os.path.join(self.get_workdir(), 'tmp', 'rip.wav')

        self.cd_tracks[package.name] = {}

        for i in range(package.rip_cd.get('first_track', 2), 100):
            track = os.path.join(self.get_workdir(), 'tmp', '%d.ogg' % i)
            if subprocess.call(['cdparanoia', '-d', cd_device, str(i),
                    tmp_wav]) != 0:
                break
            check_call(['oggenc', '-o', track, tmp_wav])
            self.cd_tracks[package.name][i] = track
            if os.path.exists(tmp_wav):
                os.remove(tmp_wav)

        if not self.cd_tracks[package.name]:
            logger.error('Did not rip any CD tracks successfully for "%s"',
                    package.name)
            raise CDRipFailed()

    def prepare_packages(self, packages=None, build_demos=False, download=True,
            search=True, log_immediately=True):
        if packages is None:
            packages = self.game.packages.values()

        possible = set()
        possible_with_lgogdownloader = set()
        possible_with_steamcmd = set()

        if self.cd_device is not None:
            rip_cd_packages = self.rip_cd_packages & packages
            if rip_cd_packages:
                if len(rip_cd_packages) > 1:
                    logger.error('cannot rip the same CD for more than one ' +
                            'music package, please specify one with ' +
                            '--package: %s',
                            ', '.join(sorted([p.name
                                for p in rip_cd_packages])))
                    raise CDRipFailed()
                self.rip_cd(rip_cd_packages.pop())

        for package in packages:
            gog_id = self.game.gog_download_name(package)
            steam_id = package.steam.get('id') or self.game.steam.get('id')
            if package.rip_cd and not self.cd_tracks.get(package.name):
                logger.debug('no CD tracks found for %s', package.name)
            elif self.fill_gaps(package,
                    log=log_immediately) is not FillResult.IMPOSSIBLE:
                logger.debug('%s is possible', package.name)
                possible.add(package)
            # download game if it is already owned by user's GOG.com account
            # user must have used 'lgogdownloader' at least once to make this work
            elif gog_id and gog_id in GOG.owned_games():
                if which('innoextract') or GOG.is_native(gog_id):
                    if lang_score(package.lang) == 0:
                        logger.debug('%s can be downloaded with lgogdownloader', package.name)
                    else:
                        logger.info('%s can be downloaded with lgogdownloader', package.name)
                    possible.add(package)
                    possible_with_lgogdownloader.add(package.name)
                else:
                    self.missing_tools.add('innoextract')
            # don't download "http://steamcommunity.com/profiles/<steam_id>/games?xml=1"
            # if downloads are disabled
            elif steam_id and download and search and which('steamcmd'):
                # avoid import loop
                from .steam import (owned_steam_games,get_steam_account)
                for g in owned_steam_games():
                    if steam_id == g[0]:
                        logger.info('%s can be downloaded with steamcmd', package.name)
                        possible.add(package)
                        possible_with_steamcmd.add(package.name)
                        break
            else:
                logger.debug('%s is impossible', package.name)

        if not possible:
            logger.debug('No packages were possible')

            if log_immediately:
                # we already logged the errors so just give up
                raise NoPackagesPossible()

            # Repeat the process for the first (hopefully only)
            # demo/shareware package, so we can log its errors.
            for package in self.game.packages.values():
                if package.demo_for:
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
                for package in self.game.packages.values():
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

        # copy the set so we can alter the original while iterating
        for package in set(possible):
            if package.architecture == 'all':
                continue
            elif package.architecture == 'any':
                # we'll need this later, cache it
                self.packaging.get_architecture()
            else:
                archs = package.architecture.split()
                arch = self.packaging.get_architecture(package.architecture)
                if arch not in archs:
                    logger.warning('cannot produce "%s" on architecture %s',
                            package.name, arch)
                    possible.discard(package)

        for package in set(possible):
            build_depends = self.__merge_relations(package, 'build_depends')
            for tool in build_depends:
                tool = tool.strip()

                if not which(tool) and not self.packaging.is_installed(tool):
                    logger.error('package "%s" is needed to build "%s"' %
                                 (tool, package.name))
                    possible.discard(package)
                    self.missing_tools.add(tool)

        logger.debug('possible packages: %r', set(p.name for p in possible))
        if not possible:
            raise NoPackagesPossible()

        # this fancy algorithm will be overiden by '--package' argument
        if not log_immediately:
            # this check is done before the language check to avoid to end up with
            # simon-the-sorcerer1-fr-data + simon-the-sorcerer1-dos-en-data
            for package in set(possible):
                for v in package.better_versions:
                    if self.game.packages[v] in possible:
                        logger.info('will not produce "%s" because better '
                                'version "%s" is also available',
                                package.name, v)
                        possible.discard(package)
                        break

            for package in set(possible):
                score = max(set(lang_score(l) for l in package.langs))
                if score == 0:
                    logger.info('will not produce "%s" '
                                'because "%s" is not in LANGUAGE selection',
                                package.name, package.lang)
                    possible.discard(package)
                    continue

                # keep only preferred language for this virtual package
                provides = self.__merge_relations(package, 'provides')

                if provides:
                    for other_p in possible:
                        if other_p.name == package.name:
                            continue
                        other_provides = self.__merge_relations(other_p,
                                'provides')
                        if other_provides - provides:
                            # it provides something this one doesn't
                            continue
                        if score < lang_score(other_p.lang):
                            logger.info('will not produce "%s" '
                                        'because "%s" is preferred language',
                                        package.name, other_p.lang)
                            possible.discard(package)
                            break
            if not possible:
                raise NoPackagesPossible()

        for package in set(possible):
            if (package.expansion_for
              and (package.expansion_for not in self.game.packages
                   or  self.game.packages[package.expansion_for] not in possible)
              and not self.packaging.is_installed(package.expansion_for)):
                for fullgame in possible:
                    if fullgame.type == 'full':
                        logger.warning("won't generate '%s' expansion, because "
                          'full game "%s" is neither available nor already installed;'
                          ' and we are packaging "%s" instead.',
                          package.name, package.expansion_for, fullgame.name)
                        possible.discard(package)
                        break
                else:
                  logger.warning('will generate "%s" expansion, but full game '
                     '"%s" is neither available nor already installed.',
                     package.name, package.expansion_for)

            if not build_demos and package.demo_for:
                for p in set(possible):
                    if p.type == 'full':
                        # no point in packaging a demo if we have any full
                        # version
                        logger.info('will not produce "%s" because we have '
                            'the full version "%s"', package.name, p.name)
                        possible.discard(package)
        if not possible:
            raise NoPackagesPossible()

        ready = set()
        lgogdownloaded = set()
        steam_password = None

        external_download = possible_with_lgogdownloader | possible_with_steamcmd
        for package in possible:
            logger.debug('will produce %s', package.name)
            result = self.fill_gaps(package=package, download=download,
              log=package.name not in external_download,
              recheck=package.name in external_download)
            if result is FillResult.COMPLETE:
                ready.add(package)
            elif download and package.name in possible_with_lgogdownloader:
                gog_id = self.game.gog_download_name(package)
                if gog_id in lgogdownloaded:
                    # something went bad, G-D-P will complain a lot anyway
                    continue
                lgogdownloaded.add(gog_id)
                tmpdir = os.path.join(self.get_workdir(), gog_id)
                mkdir_p(tmpdir)
                try:
                    check_call(['lgogdownloader',
                                       '--download',
                                       '--include', 'installers',
                                       '--directory', tmpdir,
                                       '--subdir-game', '',
                                       '--platform', 'linux,windows',
                                       '--language', package.lang,
                                       '--game', '^' + gog_id + '$'])
                    # consider *.bin before the .exe file
                    main_archive = None
                    archives = []
                    for dirpath, dirnames, filenames in os.walk(tmpdir):
                        for fn in filenames:
                            archive = os.path.join(dirpath, fn)
                            archives.append(archive)
                            if os.path.splitext(fn)[1] in ('.exe', '.sh'):
                                main_archive = archive
                            else:
                                self.consider_file(archive, True, trusted=True)
                    if main_archive:
                        self.consider_file(main_archive, True, trusted=True)

                    # recheck file status
                    if self.fill_gaps(package, log=True, download=True,
                       recheck=True) is not FillResult.IMPOSSIBLE:
                       ready.add(package)
                    if self.save_downloads:
                        for archive in archives:
                            try:
                                shutil.move(archive, self.save_downloads)
                            except shutil.Error:
                                # file was already there, but not trusted
                                pass
                except subprocess.CalledProcessError:
                    pass
            elif package.name in possible_with_steamcmd:
                steam_id = package.steam.get('id') or self.game.steam.get('id')
                steam_account = get_steam_account()
                if not steam_password:
                    import getpass
                    steam_password = getpass.getpass("Please provided password"
                                                     " for Steam account %s:" %
                                                      steam_account)
                # this should be guessed automatically like for GOG
                # and not needed to be encoded in individual YAML files
                if package.steam.get('native') or self.game.steam.get('native'):
                    platform = []
                else:
                    platform = ['+@sSteamCmdForcePlatformType', 'windows']

                try:
                    check_call(['steamcmd'] + platform + [
                                '+login', steam_account, steam_password,
                                '+app_update', '%s' % steam_id, 'validate',
                                '+quit'])
                except subprocess.CalledProcessError:
                    pass
                for path in set(self.iter_steam_paths(packages=(package,))):
                    self.consider_file_or_dir(path)
                if self.fill_gaps(package, log=True, download=True,
                    recheck=True) is not FillResult.IMPOSSIBLE:
                    ready.add(package)
            elif (result is FillResult.DOWNLOAD_NEEDED or
                  package.name in possible_with_lgogdownloader) and not download:
                logger.warning('As requested, not downloading necessary ' +
                        'files for %s', package.name)
            else:
                logger.error('Failed to download necessary files for %s',
                        package.name)

        if not ready:
            if not download:
                raise DownloadNotAllowed()
            raise DownloadsFailed()

        logger.debug('packages ready for building: %r', set(p.name for p in ready))
        return ready

    def build_packages(self, ready, destination, compress):
        packages = set()

        for package in ready:
            arch = package.architecture
            if arch != 'all':
                arch = self.packaging.get_architecture(arch)
            arch = self.packaging.ARCH_DECODE.get(arch, arch)

            if FORMAT == 'deb':
                pkg = self.build_deb(package, arch, destination, compress=compress)
            elif FORMAT == 'rpm':
                pkg = self.build_rpm(package, arch, compress=compress)
            elif FORMAT == 'arch':
                pkg = self.build_arch(package, arch, destination, compress=compress)

            if pkg is None:
                raise SystemExit(1)

            packages.add(pkg)

        return packages

    def locate_steam_icon(self, package):
        id = package.steam.get('id') or self.game.steam.get('id')
        if not id:
            return
        for res in (128, 96, 64, 32):
            icon = '~/.local/share/icons/hicolor/%dx%d/apps/steam_icon_%d.png'
            icon = os.path.expanduser(icon % (res, res, id))
            if os.path.isfile(icon):
                logger.info('found icon provided by native Steam client at %s.' % icon)
                return icon
        return

    def iter_gog_paths(self, packages=None):
        if packages is None:
            packages = self.game.packages.values()

        dirnames = set()
        for p in list(packages) + [self.game]:
            if p.gog == False:
                continue
            # some games seem to list more than one installation path :-(
            path = p.gog.get('path')
            if isinstance(path, list):
                dirnames |= set(path)
            else:
                dirnames.add(path)
        dirnames.discard(None)
        if not dirnames:
            return

        for prefix in ('/opt/GOG Games', os.path.expanduser('~/GOG Games')):
            try:
                # We look for anything starting with an element of dirnames,
                # so that we'll pick up names like "Inherit The Earth German".
                for name in os.listdir(prefix):
                    for target in dirnames:
                        try:
                            if name.startswith(target):
                                path = os.path.join(prefix, name)
                                if os.path.isdir(path):
                                    logger.debug('possible %r found at %r',
                                            self.game.shortname, path)
                                    yield os.path.realpath(path)
                        except OSError:
                            continue
            except OSError:
                continue

    def iter_steam_paths(self, packages=None):
        if packages is None:
            packages = self.game.packages.values()

        suffixes = set(p.steam.get('path') for p in packages)
        suffixes.add(self.game.steam.get('path'))
        suffixes.discard(None)
        if not suffixes:
            return

        for prefix in (
                os.path.expanduser('~/.steam'),
                os.path.join(os.environ.get('XDG_DATA_HOME', os.path.expanduser('~/.local/share')),
                    'wineprefixes/steam/drive_c/Program Files/Steam'),
                os.path.expanduser('~/Steam'),
                os.path.expanduser('~/.wine/drive_c/Program Files/Steam'),
                os.path.expanduser('~/.PlayOnLinux/wineprefix/Steam/drive_c/Program Files/Steam'),
                ) + tuple(iter_fat_mounts('Steam')):
            if not os.path.isdir(prefix):
                continue

            logger.debug('possible Steam root directory at %s', prefix)

            for middle in ('steamapps', 'steam/steamapps', 'SteamApps',
                    'steam/SteamApps'):
                for suffix in suffixes:
                    path = os.path.join(prefix, middle, suffix)
                    if os.path.isdir(path):
                        logger.debug('possible %s found in Steam at %s',
                                self.game.shortname, path)
                        yield os.path.realpath(path)

    def iter_origin_paths(self, packages=None):
        if packages is None:
            packages = self.game.packages.values()

        suffixes = set(p.origin.get('path') for p in packages)
        suffixes.add(self.game.origin.get('path'))
        suffixes.discard(None)
        if not suffixes:
            return

        for prefix in (
                os.path.expanduser('~/.wine/drive_c/Program Files/Origin Games'),
                ) + tuple(iter_fat_mounts('Origin Games')):
            if not os.path.isdir(prefix):
                continue

            logger.debug('possible Origin root directory at %s', prefix)

            for suffix in suffixes:
                path = os.path.join(prefix, suffix)
                if os.path.isdir(path):
                    logger.debug('possible %s found in Origin at %s',
                            self.game.shortname, path)
                    yield path

    def check_component(self, package):
        # redistributable packages are redistributable as long as their
        # optional license file is present
        if package.component == 'local':
            return
        for f in package.optional_files:
             if not f.license:
                 continue

             if self.file_status[f.name] is not FillResult.COMPLETE:
                 package.component = 'local'
                 return
        return

    def build_deb(self, package, arch, destination, compress=True):
        """
        If we have all the necessary files for package, build the .deb
        and return the output filename in destination. Otherwise return None.
        """
        destdir = os.path.join(self.get_workdir(), '%s.deb.d' % package.name)

        self.check_component(package)
        if not self.fill_dest_dir(package, destdir):
            # FIXME: probably better as an exception?
            return None

        self.fill_dest_dir_deb(package, destdir)
        self.our_dh_fixperms(destdir)

        # it had better have a /usr and a DEBIAN directory or
        # something has gone very wrong
        assert os.path.isdir(os.path.join(destdir, 'usr')), destdir
        assert os.path.isdir(os.path.join(destdir, 'DEBIAN')), destdir

        deb_basename = '%s_%s_%s.deb' % (package.name, package.version, arch)

        outfile = os.path.join(os.path.abspath(destination), deb_basename)

        # only compress if the caller says we should, the YAML
        # says it's worthwhile, and this isn't a ripped CD (Vorbis
        # is already compressed)
        if not compress or not self.compress_deb or package.rip_cd:
            dpkg_deb_args = ['-Znone']
        elif self.compress_deb is True:
            dpkg_deb_args = []
        elif isinstance(self.compress_deb, str):
            dpkg_deb_args = ['-Z' + self.compress_deb]
        elif isinstance(self.compress_deb, list):
            dpkg_deb_args = self.compress_deb

        try:
            logger.info('generating package %s', package.name)
            check_output(['fakeroot', 'dpkg-deb'] +
                    dpkg_deb_args +
                    ['-b', '%s.deb.d' % package.name, outfile],
                    cwd=self.get_workdir())
        except subprocess.CalledProcessError as cpe:
            print(cpe.output)
            raise

        rm_rf(destdir)
        return outfile


    def build_arch(self, package, arch, destination, compress=True):
        destdir = os.path.join(self.get_workdir(), '%s.pkg.d' % package.name)

        if not self.fill_dest_dir(package, destdir):
            return None

        self.fill_dest_dir_arch(package, destdir, compress, arch)
        self.our_dh_fixperms(destdir)

        assert os.path.isdir(os.path.join(destdir, 'usr')), destdir
        assert os.path.isfile(os.path.join(destdir, '.PKGINFO')), destdir
        assert os.path.isfile(os.path.join(destdir, '.MTREE')), destdir

        pkg_basename = '%s-%s-1-%s.pkg.tar.xz' % (package.name, package.version, arch)
        outfile = os.path.join(os.path.abspath(destination), pkg_basename)

        try:
            logger.info('generating package %s', package.name)
            files = set()
            for dirpath, dirnames, filenames in os.walk(destdir):
                for fn in filenames:
                    full = os.path.join(dirpath, fn)
                    full = full[len(destdir)+1:]
                    files.add(full)
            check_output(['fakeroot', 'bsdtar', 'cfJ', outfile] + sorted(files),
                         cwd=destdir, env={'LANG':'C'})
        except subprocess.CalledProcessError as cpe:
            print(cpe.output)
            raise

        rm_rf(destdir)
        return outfile

    def build_rpm(self, package, arch, compress=True):
        destdir = os.path.join(self.get_workdir(), '%s.rpm.d' % package.name)

        if not self.fill_dest_dir(package, destdir):
            return None

        if arch == 'noarch':
            setarch = []
        else:
            setarch = ['setarch', arch]

        # increase local 'release' number on repacking
        if not self.packaging.is_installed(package.name):
            release = '0'
        elif Version(package.version) > Version(self.packaging.current_version(package.name)):
            release = '0'
        else:
            try:
                release = check_output(['rpm', '-q', '--qf' ,'%{RELEASE}',
                                         package.name]).decode('ascii')
                release = str(int(release) + 1)
            except (subprocess.CalledProcessError, ValueError):
                release = '0'

        specfile = self.fill_dest_dir_rpm(package, destdir, compress,
                                          arch, release)
        self.our_dh_fixperms(destdir)

        assert os.path.isdir(os.path.join(destdir, 'usr')), destdir

        try:
            logger.info('generating package %s', package.name)
            check_output(setarch  + ['rpmbuild',
                         '--buildroot', destdir,
                         '-bb', '-v', specfile],
                         cwd=self.get_workdir())
        except subprocess.CalledProcessError as cpe:
            print(cpe.output)
            raise

        return(os.path.expanduser('~/rpmbuild/RPMS/') + arch + '/'
                + package.name + '-'
                + package.version + '-' + release + '.' + arch + '.rpm')

    def check_unpacker(self, wanted):
        if not wanted.unpack:
            return True

        if wanted.name in self.unpack_tried:
            return False

        fmt = wanted.unpack['format']

        # builtins
        if fmt in ('cat', 'dos2unix', 'tar.*', 'tar.gz', 'tar.bz2', 'tar.xz', 'umod', 'zip'):
            return True

        if fmt == 'deb':
            if FORMAT == 'deb':
                return True
            else:
                fmt = 'dpkg-deb'

        if which(fmt) is not None:
            return True

        if fmt == 'unzip' and (which('7z') or which('unar')):
            return True

        # unace-nonfree package diverts /usr/bin/unace from unace package
        if (fmt == 'unace-nonfree' and
                self.packaging.is_installed('unace-nonfree')):
            return True

        logger.warning('cannot unpack "%s": tool "%s" is not ' +
                       'installed', wanted.name, fmt)
        self.missing_tools.add(fmt)
        self.unpack_tried.add(wanted.name)
        return False

    def log_missing_tools(self):
        if not self.missing_tools:
            return False

        packages = set()

        for t in self.missing_tools:
            p = self.packaging.package_for_tool(t)
            if p is not None:
                packages.add(p)

        if packages:
            logger.warning('installing these packages might help:\n' +
                '%s %s', ' '.join(self.packaging.INSTALL_CMD),
                ' '.join(sorted(packages)))

    def __ensure_hashes(self, hashes, path, size):
        if hashes is not None:
            return hashes

        return HashedFile.from_file(path, open(path, 'rb'), size=size,
                progress=self.progress_factory(info='identifying %s' % path))
