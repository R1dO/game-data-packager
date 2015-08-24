#!/usr/bin/python3
# encoding=utf-8
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

from collections import defaultdict
from enum import Enum
import argparse
import glob
import hashlib
import importlib
import io
import json
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
import time
import urllib.request
import zipfile

from debian.deb822 import Deb822
import yaml

from .config import read_config
from .paths import DATADIR, ETCDIR
from .util import (MEBIBYTE,
        TemporaryUmask,
        copy_with_substitutions,
        mkdir_p,
        rm_rf,
        human_size,
        PACKAGE_CACHE,
        lang_score,
        ascii_safe,
        which)
from .version import GAME_PACKAGE_VERSION

AGENT = ('Debian Game-Data-Packager/%s (%s %s;'
         ' +http://wiki.debian.org/Games/GameDataPackager)' %
        (GAME_PACKAGE_VERSION, os.uname()[0], os.uname()[4]) )

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

class NoPackagesPossible(Exception):
    pass

class DownloadsFailed(Exception):
    pass

class DownloadNotAllowed(Exception):
    pass

class CDRipFailed(Exception):
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
                ts = time.time()
                if ts < update_progress.ts + 0.2 and not s.startswith('100%'):
                    return
                update_progress.ts = ts
                if len(pad[0]) <= len(s):
                    pad[0] = ' ' * len(s)
                print(' %s \r %s\r' % (pad[0], s), end='', file=sys.stderr)
            update_progress.ts = time.time()
        else:
            update_progress = lambda s: None

        for f in fs:
            while True:
                if size is None:
                    update_progress(human_size(done))
                else:
                    update_progress('%.0f%% %s/%s' % (
                                100 * done / size if size != 0 else 100,
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
        self.license = False
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
            'license': self.license,
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

        # Other names for this binary package
        self._aliases = set()

        # Names of relative packages
        self.demo_for = set()
        self.better_version = None
        self.expansion_for = None
        # expansion for a package outside of this yaml file;
        # may be another GDP package or a package not made by GDP
        self.expansion_for_ext = None

        # The optional marketing name of this version
        self.longname = None

        # This word is used to build package description
        # 'data' / 'PWAD' / 'IWAD'
        self.data_type = 'data'

        # This optional value will overide the game global copyright
        self.copyright = None

        # Languages, list of ISO-639 codes
        self.langs = ['en']

        # Where we install files.
        # For instance, if this is 'usr/share/games/quake3' and we have
        # a WantedFile with install_as='baseq3/pak1.pk3' then we would
        # put 'usr/share/games/quake3/baseq3/pak1.pk3' in the .deb.
        # The default is 'usr/share/games/' plus the binary package's name.
        if name.endswith('-data'):
            self.install_to = 'usr/share/games/' + name[:len(name) - 5]
        else:
            self.install_to = 'usr/share/games/' + name

        # Prefixes of files that get installed to /usr/share/doc/PACKAGE
        # instead
        self.install_to_docdir = []

        # symlink => real file (the opposite way round that debhelper does it,
        # because the links must be unique but the real files are not
        # necessarily)
        self.symlinks = {}

        # online stores metadata
        self.steam = {}
        self.gog = {}
        self.dotemu = {}
        self.origin = {}
        self.url_misc = None

        # overide the game engine when needed
        self.engine = None

        # depedency information needed to build the debian/control file
        self.debian = {}

        # set of names of WantedFile instances to be installed
        self._install = set()

        # set of names of WantedFile instances to be optionally installed
        self._optional = set()

        self.version = GAME_PACKAGE_VERSION

        # if not None, install every file provided by the files with
        # these names
        self._install_contents_of = set()

        # CD audio stuff from YAML
        self.rip_cd = {}

        # Debian architecture(s)
        self.architecture = 'all'

        # Component (archive area): main, contrib, non-free, local
        # We use "local" to mean "not distributable"; the others correspond
        # to components in the Debian archive
        self.component = 'local'
        self.section = 'games'

        # show output of external tools?
        self.verbose = False

    @property
    def aliases(self):
        return self._aliases
    @aliases.setter
    def aliases(self, value):
        self._aliases = set(value)

    @property
    def install(self):
        return self._install
    @install.setter
    def install(self, value):
        self._install = set(value)

    @property
    def only_file(self):
        if len(self._install) == 1:
            return list(self._install)[0]
        else:
            return None

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
        """type of package: full, demo or expansion

        full packages include quake-registered, quake2-full-data, quake3-data
        demo packages include quake-shareware, quake2-demo-data
        expansion packages include quake-armagon, quake-music, quake2-rogue
        """
        if self.demo_for:
            return 'demo'
        if self.expansion_for or self.expansion_for_ext:
            return 'expansion'
        return 'full'

    @property
    def lang(self):
        return self.langs[0]

    @lang.setter
    def lang(self, value):
        assert type(value) is str
        self.langs = [value]

    def to_yaml(self):
        return {
            'architecture': self.architecture,
            'demo_for': sorted(self.demo_for),
            'better_version': self.better_version,
            'expansion_for': self.expansion_for,
            'install': sorted(self.install),
            'install_to': self.install_to,
            'install_to_docdir': self.install_to_docdir,
            'name': self.name,
            'optional': sorted(self.optional),
            'rip_cd': self.rip_cd,
            'steam': self.steam,
            'gog': self.gog,
            'origin': self.origin,
            'symlinks': self.symlinks,
            'type': self.type,
        }

class GameData(object):
    def __init__(self,
            shortname,
            data,
            workdir=None):
        # The name of the game for command-line purposes, e.g. quake3
        self.shortname = shortname

        # Other command-line names for this game
        self.aliases = set()

        # The formal name of the game, e.g. Quake III Arena
        self.longname = shortname.title()

        # The one-line copyright notice used to build debian/copyright
        self.copyright = None

        # The game engine used to run the game (package name)
        self.engine = None

        # Game translations known to exists, but missing in 'packages:'
        # list of ISO-639 codes
        self.missing_langs = []

        # The game genre
        # http://en.wikipedia.org/wiki/List_of_video_game_genres
        self.genre = None

        # A temporary directory.
        self.workdir = workdir

        # Clean up these directories on exit.
        self._cleanup_dirs = set()

        # binary package name => GameDataPackage
        self.packages = {}

        # Subset of packages.values() with nonempty rip_cd
        self.rip_cd_packages = set()

        # How to compress the .deb:
        # True: dpkg-deb's default
        # False: -Znone
        # str: -Zstr (gzip, xz or none)
        # list: arbitrary options (e.g. -z9 -Zgz -Sfixed)
        self.compress_deb = True

        self.help_text = ''

        # Extra directories where we might find game files
        self.try_repack_from = []

        # online stores metadata
        self.steam = {}
        self.gog = {}
        self.dotemu = {}
        self.origin = {}

        # full url of online game shops
        self.url_steam = None
        self.url_gog = None
        self.url_dotemu = None
        self.url_misc = None

        self.data = data

        self.argument_parser = None

        for k in ('longname', 'copyright', 'compress_deb', 'help_text', 
                  'engine', 'genre', 'missing_langs',
                  'steam', 'gog', 'dotemu', 'origin', 'url_misc'):
            if k in self.data:
                setattr(self, k, self.data[k])

        assert type(self.missing_langs) is list

        if 'aliases' in self.data:
            self.aliases = set(self.data['aliases'])

        if 'try_repack_from' in self.data:
            paths = self.data['try_repack_from']
            if isinstance(paths, list):
                self.try_repack_from = paths
            elif isinstance(paths, str):
                self.try_repack_from = [paths]
            else:
                raise AssertionError('try_repack_from should be str or list')

        # these should be per-package
        assert 'install_files' not in self.data
        assert 'package' not in self.data
        assert 'symlinks' not in self.data
        assert 'install_files_from_cksums' not in self.data

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

        # None or an existing directory in which to save downloaded files.
        self.save_downloads = None

        # Block device from which to rip audio
        self.cd_device = None

        # Found CD tracks
        # e.g. { 'quake-music': { 2: '/usr/.../id1/music/track02.ogg' } }
        self.cd_tracks = {}

        # Debian architecture
        self._architecture = None

        self._populate_files(self.data.get('files'))

        assert 'packages' in self.data

        for binary, data in self.data['packages'].items():
            # these should only be at top level, since they are global
            assert 'cksums' not in data, binary
            assert 'md5sums' not in data, binary
            assert 'sha1sums' not in data, binary
            assert 'sha256sums' not in data, binary

            if 'DISABLED' in data and not os.environ.get('DEBUG'):
                continue
            package = self.construct_package(binary)
            self.packages[binary] = package
            self._populate_package(package, data)

        if 'cksums' in self.data:
            for line in self.data['cksums'].splitlines():
                stripped = line.strip()
                if stripped == '' or stripped.startswith('#'):
                    continue

                _, size, filename = line.split(None, 2)
                f = self._ensure_file(filename)
                f.size = int(size)

        if 'size_and_md5' in self.data:
            for line in self.data['size_and_md5'].splitlines():
                stripped = line.strip()
                if stripped == '' or stripped.startswith('#'):
                    continue

                size, md5, filename = line.split(None, 2)
                f = self._ensure_file(filename)
                f.size = int(size)
                f.md5 = md5

        for alg in ('md5', 'sha1', 'sha256'):
            if alg + 'sums' in self.data:
                for line in self.data[alg + 'sums'].splitlines():
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

        # consistency check
        for package in self.packages.values():
            for provider in package.install_contents_of:
                assert provider in self.files, (package.name, provider)
                for filename in self.files[provider].provides:
                    assert filename in self.files, (package.name, provider,
                            filename)
                    if filename not in package.optional:
                        package.install.add(filename)

            if package.rip_cd:
                # we only support Ogg Vorbis for now
                assert package.rip_cd['encoding'] == 'vorbis', package.name
                self.rip_cd_packages.add(package)

            # there had better be something it wants to install
            assert package.install or package.rip_cd, package.name
            for installable in package.install:
                assert installable in self.files, installable
            for installable in package.optional:
                assert installable in self.files, installable

            # check internal depedencies
            for demo_for_item in package.demo_for:
                assert demo_for_item in self.packages, demo_for_item
            assert (not package.expansion_for or
              package.expansion_for in self.packages), package.expansion_for
            assert (not package.better_version or
              package.better_version in self.packages), package.better_version

            # check for stale missing_langs
            if not package.demo_for:
                assert not set(package.langs).intersection(self.missing_langs)

        for filename, wanted in self.files.items():
            if wanted.unpack:
                assert 'format' in wanted.unpack, filename
                assert wanted.provides, filename
                if wanted.unpack['format'] == 'cat':
                    assert len(wanted.provides) == 1, filename
                    assert isinstance(wanted.unpack['other_parts'],
                            list), filename
                if 'include' in wanted.unpack:
                    assert isinstance(wanted.unpack['include'],
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
            # FIXME: find out file size and add to yaml
            else:
                assert wanted.size is not None or filename in (
                   'hipnotic/pak0.pak_qdq_glquake_compat',
                   'resource.1_106_cd',
                   'vox0000.lab_unpatched',
                   ), (self.shortname, wanted.name)

        if len(self.packages) > 1:
            prepend = '\npackages possible for this game:\n'
            help = []
            for package in self.packages.values():
                game_type = { 'demo' : 1,
                              'full' : 2,
                              'expansion' : 3}.get(package.type)
                help.append({ 'type' : game_type,
                              'year' : package.copyright or self.copyright,
                              'name' : package.name,
                              'longname': package.longname or self.longname})
            for h in sorted(help, key=lambda k: (k['type'], k['year'][2:6], k['name'])):
                prepend += "  %-40s %s\n" % (h['name'],h['longname'])
            self.help_text = prepend + '\n' + self.help_text

        if self.missing_langs:
            self.help_text += ('\nThe following languages are not '
                               'yet supported: %s\n' %
                               ','.join(self.missing_langs))

        # advertise where to buy games
        # if it's not already in the help_text
        gog_url = self.gog.get('url')
        gog_pp = '22d200f8670dbdb3e253a90eee5098477c95c23d' # ScummVM
        steam_id = {self.steam.get('id')}
        dotemu_id = self.dotemu.get('id')
        dotemu_pp = '32202' # ScummVM
        for p in sorted(self.packages.keys(), reverse=True):
            package = self.packages[p]
            gog_url = package.gog.get('url', gog_url)
            gog_pp = package.gog.get('pp', gog_pp)
            steam_id.add(package.steam.get('id'))
            dotemu_id = package.dotemu.get('id', dotemu_id)
            dotemu_pp = package.dotemu.get('pp', dotemu_pp)
            if package.url_misc:
                self.url_misc = package.url_misc
        steam_id.discard(None)
        www = list()
        if steam_id:
            self.url_steam = 'http://store.steampowered.com/app/%s/' % min(steam_id)
            if '://store.steampowered.com/' not in self.help_text:
                www.append(self.url_steam)
        if gog_url:
            self.url_gog = 'http://www.gog.com/game/' + gog_url + '?pp=' + gog_pp
            if '://www.gog.com/' not in self.help_text:
                www.append(self.url_gog)
        if dotemu_id:
            self.url_dotemu = 'http://www.dotemu.com/affiliate/%s/node/%d' % (
                              dotemu_pp, dotemu_id)
            www.append(self.url_dotemu)
        if self.url_misc:
            www.append(self.url_misc)
        if www:
            random.shuffle(www)
            self.help_text += '\nThis game can be bought online here:\n  '
            self.help_text += '\n  '.join(www)

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
        for k in ('expansion_for', 'expansion_for_ext', 'longname', 'symlinks', 'install_to',
                'install_to_docdir', 'install_contents_of', 'debian',
                'rip_cd', 'architecture', 'aliases', 'better_version', 'langs',
                'copyright', 'engine', 'lang', 'component', 'section',
                'steam', 'gog', 'dotemu', 'origin', 'url_misc'):
            if k in d:
                setattr(package, k, d[k])

        assert self.copyright or package.copyright, package.name
        assert package.component in ('main', 'contrib', 'non-free', 'local')
        assert package.component == 'local' or 'license' in d
        assert package.section in ('games', 'doc'), 'unsupported'
        assert type(package.langs) is list

        if 'install_to' in d:
            assert 'usr/share/games/' + package.name != d['install_to'] + '-data', \
                "install_to %s is extraneous" % package.name

        if 'demo_for' in d:
            if type(d['demo_for']) is str:
                package.demo_for.add(d['demo_for'])
            else:
                package.demo_for |= set(d['demo_for'])
            assert package.name != d['demo_for'], "a game can't be a demo for itself"
            if not package.longname:
                package.longname = self.longname + ' (demo)'
        else:
            assert 'demo' not in package.name or len(self.packages) == 1, \
                package.name + ' miss a demo_for tag.'
            if not package.longname and package.lang != 'en':
                package.longname = self.longname + ' (%s)' % package.lang

        if 'expansion_for' in d:
            assert package.name != d['expansion_for'], \
                   "a game can't be an expansion for itself"
            if 'demo_for' in d:
                raise AssertionError("%r can't be both a demo of %r and an " +
                        "expansion for %r" % (package.name, d.demo_for,
                            d.expansion_for))

        if 'install' in d:
            for filename in d['install']:
                f = self._ensure_file(filename)
                package.install.add(filename)

        if 'optional' in d:
            assert isinstance(d['optional'], list), package.name
            for filename in d['optional']:
                f = self._ensure_file(filename)
                package.optional.add(filename)

        if 'license' in d:
            assert isinstance(d['license'], list), package.name
            for filename in d['license']:
                f = self._ensure_file(filename)
                f.license = True
                f.install_to = '$docdir'
                f.distinctive_name = False
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

        if 'version' in d:
            package.version = d['version'] + '+' + GAME_PACKAGE_VERSION

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

            assert 'optional' not in data, filename
            if 'look_for' in data and 'install_as' in data:
                assert data['look_for'] != [data['install_as']], filename
            for k in (
                    'alternatives',
                    'distinctive_name',
                    'distinctive_size',
                    'download',
                    'install_as',
                    'install_to',
                    'license',
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
            # always silence warning if several files have same
            # look_for & same size: e.g. wolf3d, spear, dune2, ...
            if log:
                sizes = []
                for lf in wanted.look_for:
                    for filename in self.known_filenames[lf]:
                        size = self.files[filename].size
                        if size in sizes:
                            log = False
                            break
                        sizes.append(size)

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

        for p in self.rip_cd_packages:
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
            # ... still G-D-P should try to process any random .zip
            # file thrown at it, like the .zip provided by GamersHell
            if os.path.splitext(path)[1].lower() in ('.zip', '.apk'):
                with zipfile.ZipFile(path, 'r') as zf:
                    self.consider_zip(path, zf)

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
        st = os.stat(path)

        if stat.S_ISREG(st.st_mode):
            self.consider_file(path, True)
        elif stat.S_ISDIR(st.st_mode):
            for dirpath, dirnames, filenames in os.walk(path):
                for fn in filenames:
                    self.consider_file(os.path.join(dirpath, fn), False)
        elif stat.S_ISBLK(st.st_mode):
            if self.rip_cd_packages:
                self.cd_device = path
            else:
                logger.warning('"%s" does not have a package containing CD '
                        'audio, ignoring block device "%s"',
                        self.shortname, path)
        else:
            logger.warning('file "%s" does not exist or is not a file, ' +
                    'directory or CD block device', path)

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

        # search first for files that have only one provider,
        # to avoid extraneous downloads
        unique_provider = list()
        multi_provider = list()
        for filename in (package.install | package.optional):
            if len(self.providers.get(filename,[])) == 1:
                unique_provider.append(filename)
            else:
                multi_provider.append(filename)

        for filename in unique_provider + multi_provider:
            if filename not in self.found:
                wanted = self.files[filename]
                # updates file_status as a side-effect
                self.fill_gap(package, wanted, download=download,
                        log=(log and filename in package.install))

            logger.debug('%s: %s', filename, self.file_status[filename])

            if filename in package.install:
                # it is mandatory
                result &= self.file_status[filename]

        self.package_status[package.name] = result
        logger.debug('%s: %s', package.name, result)
        return result

    def consider_zip(self, name, zf, provider=None):
        if provider is None:
            try_to_unpack = self.files
            should_provide = set()
            distinctive_dirs = False
        else:
            try_to_unpack = provider.provides
            should_provide = set(try_to_unpack)
            distinctive_dirs = provider.unpack.get('distinctive_dirs', True)

        for entry in zf.infolist():
            if not entry.file_size:
                continue

            for filename in try_to_unpack:
                wanted = self.files.get(filename)

                if wanted is None:
                    continue

                if wanted.alternatives:
                    continue

                if wanted.size is not None and wanted.size != entry.file_size:
                    continue

                match_path = '/' + entry.filename.lower()

                for lf in wanted.look_for:
                    if not distinctive_dirs:
                        lf = os.path.basename(lf)
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
                        orig_time = time.mktime(entry.date_time + (0, 0, -1))
                        os.utime(tmp, (orig_time, orig_time))

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
                        os.utime(tmp, (entry.mtime, entry.mtime))

                        if not self.use_file(wanted, tmp, hf):
                            os.remove(tmp)

        if should_provide:
            for missing in sorted(should_provide):
                logger.error('%s should have provided %s but did not',
                        name, missing)

    def choose_mirror(self, wanted):
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
            mirrors = [mirror + wanted.name]
            url_basename = os.path.basename(wanted.download)
            if url_basename != wanted.name and '?' not in url_basename:
                mirrors.append(mirror + url_basename)
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
            mirrors.insert(0, mirror + wanted.name)
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
            orig_time = os.stat(self.found[provider.name]).st_mtime
            os.utime(path, (orig_time, orig_time))
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
                        rf = urllib.request.urlopen(urllib.request.Request(
                                         url,headers={'User-Agent': AGENT}))
                        if rf is None:
                            continue

                        if self.save_downloads is not None:
                            tmp = os.path.join(self.save_downloads,
                                    wanted.name)
                        else:
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
                            # file corrupted or something
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
                                    id_diz = subprocess.check_output(['unzip', '-c','-q',
                                     found_name, 'FILE_ID.DIZ']).decode(encoding, 'replace')
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
                elif fmt == 'deb':
                    with subprocess.Popen(['dpkg-deb', '--fsys-tarfile', found_name],
                                stdout=subprocess.PIPE) as fsys_process:
                        with tarfile.open(found_name + '//data.tar.*', mode='r|',
                               fileobj=fsys_process.stdout) as tar:
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
                    arg = 'x' if self.verbose else 'xq'
                    subprocess.check_call(['lha', arg,
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
                    # this format doesn't store a timestamp, so the extracted
                    # files will instead inherit the archive's timestamp
                    orig_time = os.stat(found_name).st_mtime
                    for f in to_unpack:
                        tmp = os.path.join(tmpdir, f)
                        os.utime(tmp, (orig_time, orig_time))
                        self.consider_file(tmp, True)
                elif fmt == 'cabextract':
                    to_unpack = provider.unpack.get('unpack', provider.provides)
                    logger.debug('Extracting %r from %s',
                            to_unpack, found_name)
                    tmpdir = os.path.join(self.get_workdir(), 'tmp',
                            provider_name + '.d')
                    mkdir_p(tmpdir)
                    quiet = [] if self.verbose else ['-q']
                    subprocess.check_call(['cabextract'] + quiet + ['-L',
                                os.path.abspath(found_name)], cwd=tmpdir)
                    self.consider_file_or_dir(tmpdir)
                elif fmt == 'unace-nonfree':
                    to_unpack = provider.unpack.get('unpack', provider.provides)
                    logger.debug('Extracting %r from %s',
                            to_unpack, found_name)
                    tmpdir = os.path.join(self.get_workdir(), 'tmp',
                            provider_name + '.d')
                    mkdir_p(tmpdir)
                    subprocess.check_call(['unace', 'x',
                             os.path.abspath(found_name)] +
                             list(to_unpack), cwd=tmpdir)
                    self.consider_file_or_dir(tmpdir)
                elif fmt == 'unrar-nonfree':
                    to_unpack = provider.unpack.get('unpack', provider.provides)
                    logger.debug('Extracting %r from %s',
                            to_unpack, found_name)
                    tmpdir = os.path.join(self.get_workdir(), 'tmp',
                            provider_name + '.d')
                    mkdir_p(tmpdir)
                    quiet = [] if self.verbose else ['-inul']
                    subprocess.check_call(['unrar-nonfree', 'x'] + quiet +
                             [os.path.abspath(found_name)] +
                             list(to_unpack), cwd=tmpdir)
                    self.consider_file_or_dir(tmpdir)
                elif fmt == 'innoextract':
                    to_unpack = provider.unpack.get('unpack', provider.provides)
                    logger.debug('Extracting %r from %s',
                            to_unpack, found_name)
                    tmpdir = os.path.join(self.get_workdir(), 'tmp',
                            provider_name + '.d')
                    mkdir_p(tmpdir)
                    cmdline = ['innoextract',
                               '--language', 'english',
                               '-T', 'local',
                               '--lowercase',
                               '-d', tmpdir,
                               os.path.abspath(found_name)]
                    if not self.verbose:
                        cmdline.append('--silent')
                    version = subprocess.check_output(['innoextract', '-v', '-s'],
                                                      universal_newlines=True)
                    if version != '1.4' and 'FIXME' not in to_unpack:
                        prefix = provider.unpack.get('prefix', '')
                        suffix = provider.unpack.get('suffix', '')
                        if prefix and not prefix.endswith('/'):
                            prefix += '/'
                        if '$provides' in to_unpack:
                            to_unpack.remove('$provides')
                            to_unpack += provider.provides
                        for i in to_unpack:
                            cmdline.append('-I')
                            if prefix and i[0] != '/':
                                i = prefix + i
                            if suffix and i.endswith(suffix):
                                i = i[:len(i)-len(suffix)]
                            cmdline.append(i.lower())
                    subprocess.check_call(cmdline)
                    # for at least Theme Hospital the files we want are
                    # actually in subdirectories, so we search recursively
                    self.consider_file_or_dir(tmpdir)
                elif fmt == 'unzip' and which('unzip'):
                    to_unpack = provider.unpack.get('unpack', provider.provides)
                    logger.debug('Extracting %r from %s',
                            to_unpack, found_name)
                    tmpdir = os.path.join(self.get_workdir(), 'tmp',
                            provider_name + '.d')
                    mkdir_p(tmpdir)
                    quiet = ['-q'] if self.verbose else ['-qq']
                    subprocess.check_call(['unzip', '-j', '-C'] +
                                quiet + [os.path.abspath(found_name)] +
                            list(to_unpack), cwd=tmpdir)
                    # -j junk paths
                    # -C use case-insensitive matching
                    self.consider_file_or_dir(tmpdir)
                elif fmt in ('7z', 'unzip'):
                    to_unpack = provider.unpack.get('unpack', provider.provides)
                    logger.debug('Extracting %r from %s',
                            to_unpack, found_name)
                    tmpdir = os.path.join(self.get_workdir(), 'tmp',
                            provider_name + '.d')
                    mkdir_p(tmpdir)
                    flags = provider.unpack.get('flags', [])
                    if not self.verbose:
                        flags.append('-bd')
                    subprocess.check_call(['7z', 'x'] + flags +
                                [os.path.abspath(found_name)] +
                                list(to_unpack), cwd=tmpdir)
                    self.consider_file_or_dir(tmpdir)
                elif fmt in ('unar', 'unzip'):
                    to_unpack = provider.unpack.get('unpack', provider.provides)
                    logger.debug('Extracting %r from %s', to_unpack, found_name)
                    tmpdir = os.path.join(self.get_workdir(), 'tmp',
                            provider_name + '.d')
                    mkdir_p(tmpdir)
                    quiet = [] if self.verbose else ['-q']
                    subprocess.check_call(['unar', '-D'] +
                               quiet + [os.path.abspath(found_name)] +
                               list(to_unpack), cwd=tmpdir)
                    self.consider_file_or_dir(tmpdir)
                elif fmt == 'unshield':
                    other_parts = provider.unpack['other_parts']
                    for p in other_parts:
                        self.fill_gap(package, self.files[p], download=False, log=True)
                        if p not in self.found:
                            # can't concatenate: one of the bits is missing
                            break
                    else:
                        to_unpack = provider.unpack.get('unpack', provider.provides)
                        logger.debug('Extracting %r from %s',
                                to_unpack, found_name)
                        tmpdir = os.path.join(self.get_workdir(), 'tmp',
                                provider_name + '.d')
                        mkdir_p(tmpdir)
                        # we can't specify individual files to extract
                        # but we can narrow down to 'groups'
                        groups = provider.unpack.get('groups')
                        if groups:
                            # unshield only take last '-g' into account
                            for group in groups:
                                subprocess.check_call(['unshield', '-g', group,
                                   'x', os.path.abspath(found_name)], cwd=tmpdir)
                        else:
                            subprocess.check_call(['unshield', 'x',
                                     os.path.abspath(found_name)], cwd=tmpdir)

                        # this format doesn't store a timestamp, so the extracted
                        # files will instead inherit the archive's timestamp
                        orig_time = os.stat(found_name).st_mtime
                        for dirpath, dirnames, filenames in os.walk(tmpdir):
                            for fn in filenames:
                                full = os.path.join(dirpath, fn)
                                os.utime(full, (orig_time, orig_time))
                        self.consider_file_or_dir(tmpdir)
                elif fmt == 'arj':
                    other_parts = set(provider.unpack.get('other_parts'))
                    other_parts.discard(None)
                    for p in other_parts:
                        self.fill_gap(package, self.files[p], download=False, log=True)
                        if p not in self.found:
                            # can't concatenate: one of the bits is missing
                            break
                    else:
                        to_unpack = provider.unpack.get('unpack', provider.provides)
                        logger.debug('Extracting %r from %s',
                                to_unpack, found_name)
                        tmpdir = os.path.join(self.get_workdir(), 'tmp',
                                provider_name + '.d')
                        mkdir_p(tmpdir)
                        subprocess.check_call(['arj', 'e',
                                  os.path.abspath(found_name)] +
                                  list(to_unpack), cwd=tmpdir)
                        for p in other_parts:
                            subprocess.check_call(['arj', 'e', '-jya',
                                  os.path.join(os.path.dirname(found_name),p)] +
                                  list(to_unpack), cwd=tmpdir)
                        for f in to_unpack:
                            tmp = os.path.join(tmpdir, f)
                            self.consider_file(tmp, True)
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

    def fill_docs(self, package, destdir, docdir):
        copy_to = os.path.join(docdir, 'copyright')
        for n in (package.name, self.shortname):
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
            for f in package.install | package.optional:
                 if self.file_status[f] is not FillResult.COMPLETE:
                     continue
                 if not self.files[f].license:
                     continue
                 license_file = self.files[f].install_as
                 licenses.add("/usr/share/doc/%s/%s" % (package.name, license_file))
                 if os.path.splitext(license_file)[0].lower() == 'license':
                     lintiandir = os.path.join(destdir, 'usr/share/lintian/overrides')
                     mkdir_p(lintiandir)
                     with open(os.path.join(lintiandir, package.name),
                              'a', encoding='utf-8') as l:
                         l.write('%s: extra-license-file usr/share/doc/%s/%s\n'
                                 % (package.name, package.name, license_file))

            if package.component == 'local':
                o.write('It contains proprietary game data '
                        'and must not be redistributed.\n\n')
            elif package.component == 'non-free':
                o.write('It contains proprietary game data '
                        'that may be redistributed\nonly under'
                        'conditions specified in\n')
                o.write(',\n'.join(licenses) + '.\n\n')
            else:
                o.write('It contains free game data and may be\n'
                        'redistributed under conditions specified in\n')
                o.write(',\n'.join(licenses) + '.\n\n')

            count_usr = 0
            exts = set()
            count_doc = 0
            for f in package.install | package.optional:
                 if self.file_status[f] is FillResult.IMPOSSIBLE:
                     continue
                 install_to = self.files[f].install_to
                 if install_to and install_to.startswith('$docdir'):
                     count_doc +=1
                 else:
                     count_usr +=1
                     # doesn't have to be a .wad, ROTT's EXTREME.RTL
                     # or any other one-datafile .deb would qualify too
                     main_wad = self.files[f].install_as
                     exts.add(os.path.splitext(main_wad.lower())[1])

            if count_usr == 0 and count_doc == 1:
                o.write('"/usr/share/doc/%s/%s"\n' % (package.name,
                                                      package.only_file))
            elif count_usr == 1:
                o.write('"/%s/%s"\n' % (package.install_to, main_wad))
            elif len(exts) == 1:
                o.write('The %s files under "/%s/"\n' %
                        (list(exts)[0] ,package.install_to))
            else:
                o.write('The files under "/%s/"\n' % package.install_to)

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

            o.write(package.copyright or self.copyright)
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

    def fill_dest_dir(self, package, destdir):
        if not self.check_complete(package, log=True):
            return False

        docdir = os.path.join(destdir, 'usr/share/doc', package.name)
        mkdir_p(docdir)
        shutil.copyfile(os.path.join(DATADIR, 'changelog.gz'),
                os.path.join(docdir, 'changelog.gz'))

        self.fill_docs(package, destdir, docdir)

        debdir = os.path.join(destdir, 'DEBIAN')
        mkdir_p(debdir)

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
                subprocess.check_call(['cp', '--reflink=auto',
                    '--preserve=timestamps', copy_from, copy_to])

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

        if package.rip_cd and self.cd_tracks.get(package.name):
            for i, copy_from in self.cd_tracks[package.name].items():
                logger.debug('Found CD track %d at %s', i, copy_from)
                install_to = package.install_to
                install_as = package.rip_cd['filename_format'] % i
                copy_to = os.path.join(destdir, install_to, install_as)
                copy_to_dir = os.path.dirname(copy_to)
                if not os.path.isdir(copy_to_dir):
                    mkdir_p(copy_to_dir)
                subprocess.check_call(['cp', '--reflink=auto',
                    '--preserve=timestamps', copy_from, copy_to])

        self.fill_extra_files(package, destdir)

        # adapted from dh_md5sums
        subprocess.check_call("find . -type f ! -regex '\./DEBIAN/.*' " +
                "-printf '%P\\0' | LC_ALL=C sort -z | " +
                "xargs -r0 md5sum > DEBIAN/md5sums",
                shell=True, cwd=destdir)
        os.chmod(os.path.join(destdir, 'DEBIAN/md5sums'), 0o644)

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

        for dirpath, dirnames, filenames in os.walk(destdir):
            for fn in filenames + dirnames:
                full = os.path.join(dirpath, fn)
                stat_res = os.lstat(full)
                if stat.S_ISLNK(stat_res.st_mode):
                    continue
                elif stat.S_ISDIR(stat_res.st_mode):
                    # make directories rwxr-xr-x
                    os.chmod(full, 0o755)
                elif ((stat.S_IMODE(stat_res.st_mode) & 0o111) != 0
                       and (fn.endswith('.sh')
                            or dirpath.endswith('/usr/games')
                            or dirpath.endswith('/DEBIAN'))):
                    # make executable files rwxr-xr-x
                    os.chmod(full, 0o755)
                else:
                    # make other files rw-r--r--
                    os.chmod(full, 0o644)

        return True

    def modify_control_template(self, control, package, destdir):
        if 'Package' in control:
            assert control['Package'] in ('PACKAGE', package.name)
        control['Package'] = package.name

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

        default_values = {
            'Priority' : 'optional',
            'Architecture' : 'all',
            'Maintainer' : 'Debian Games Team <pkg-games-devel@lists.alioth.debian.org>',
        }
        for field in default_values:
            if field not in control:
                control[field] = default_values[field]

        assert 'Section' not in control, 'please specify only in YAML'
        if package.component == 'main':
            control['Section'] = package.section
        else:
            control['Section'] = package.component + '/' + package.section

        if package.architecture != 'all':
            control['Architecture'] = self.get_architecture()

        if control['Architecture'] == 'all' and 'Multi-Arch' not in control:
            control['Multi-Arch'] = 'foreign'

        def read_control_set(package, control, field):
            result = set()
            if field in control:
                for value in control[field].split(','):
                    result.add(value.strip())
            value = package.debian.get(field.lower())
            if isinstance(value, str):
                result.add(value)
            elif isinstance(value, list):
                for x in value:
                    result.add(x)
            elif value is not None:
                raise AssertionError('%s: debian.%s should be str or list' %
                        (package.name, field.lower()))
            return result

        depends = read_control_set(package, control, 'Depends')
        recommends = read_control_set(package, control, 'Recommends')
        suggests = read_control_set(package, control, 'Suggests')
        provides = read_control_set(package, control, 'Provides')
        replaces = read_control_set(package, control, 'Replaces')
        conflicts = read_control_set(package, control, 'Conflicts')
        breaks = read_control_set(package, control, 'Breaks')

        engine = package.engine or self.engine
        if '>=' in engine:
            breaks.add(engine.replace('>=', '<<'))
            engine = engine.split()[0]

        if package.expansion_for:
            # check if default heuristic has been overriden in yaml
            for p in depends:
                if package.expansion_for == p.split()[0]:
                    break
            else:
                depends.add(package.expansion_for)
        if package.engine:
            recommends.add(engine)
        elif not package.expansion_for and self.engine:
            recommends.add(engine)
        for other_package in self.packages.values():
            if other_package.expansion_for == package.name:
                suggests.add(other_package.name)
        assert package.name not in provides, \
               "A package shouldn't extraneously provide itself"

        # Shortcut: if A Replaces B, A automatically Conflicts B
        replace = package.debian.get('replaces')
        if replace:
            if isinstance(replace, str):
                conflicts.add(replace)
            elif isinstance(replace, list):
                for x in replace:
                    conflicts.add(x)

        if depends:
            control['Depends'] = ', '.join(sorted(depends))
        if recommends:
            control['Recommends'] = ', '.join(sorted(recommends))
        if suggests:
            control['Suggests'] = ', '.join(sorted(suggests))
        if provides:
            control['Provides'] = ', '.join(sorted(provides))
        if replaces:
            control['Replaces'] = ', '.join(sorted(replaces))
        if conflicts:
            control['Conflicts'] = ', '.join(sorted(conflicts))
        if breaks:
            control['Breaks'] = ', '.join(sorted(breaks))

        if 'Version' in control:
            package.version = control['Version'].replace('VERSION',
                    GAME_PACKAGE_VERSION)

        control['Version'] = package.version

        if 'Description' not in control:
            longname = package.longname or self.longname

            if package.section == 'games':
                short_desc = package.data_type + ' for "' + longname + '" game'
            else:
                short_desc = longname

            long_desc =  ' This package was built using game-data-packager.\n'
            if package.component == 'local':
                long_desc += ' It contains proprietary game data and must not be redistributed.\n'
                long_desc += ' .\n'
            elif package.component == 'non-free':
                long_desc += ' It contains proprietary game data that may be redistributed\n'
                long_desc += ' only under some conditions.\n'
                long_desc += ' .\n'
            else:
                long_desc += ' It contains free game data and may be redistributed.\n'
                long_desc += ' .\n'

            if self.genre:
                long_desc += '  Genre: ' + self.genre + '\n'

            if package.section == 'doc':
                long_desc += '  Documentation: ' + longname + '\n'
            elif package.expansion_for:
                game_name = self.packages[package.expansion_for].longname or self.longname
                long_desc += '  Game: ' + game_name + '\n'
                long_desc += '  Expansion: ' + longname + '\n'
            else:
                long_desc += '  Game: ' + longname + '\n'

            copyright = package.copyright or self.copyright
            long_desc += '  Published by: ' + copyright.split(' ', 2)[2]

            if engine and package.section == 'games':
                long_desc += '\n .\n'
                if '|' in engine:
                    virtual = engine.split('|')[-1].strip()
                    has_virtual = (virtual.split('-')[-1] == 'engine')
                else:
                    has_virtual = False
                engine = engine.split('|')[0].split('(')[0].strip()
                if has_virtual:
                    long_desc += ' Intended for use with some ' + virtual + ',\n'
                    long_desc += ' such as for example: ' + engine
                else:
                    long_desc += ' Intended for use with: ' + engine

            control['Description'] = short_desc + '\n' + long_desc

    def get_control_template(self, package):
        return os.path.join(DATADIR, package.name + '.control.in')

    def add_parser(self, parsers, base_parser, **kwargs):
        aliases = self.aliases

        longname = ascii_safe(self.longname)

        parser = parsers.add_parser(self.shortname,
                help=longname, aliases=aliases,
                description='Package data files for %s.' % longname,
                epilog=ascii_safe(self.help_text),
                formatter_class=argparse.RawDescriptionHelpFormatter,
                parents=(base_parser,),
                **kwargs)
        parser.add_argument('paths', nargs='*',
                metavar='DIRECTORY|FILE',
                help='Files to use in constructing the .deb')

        # There is only a --demo option if at least one package is a demo
        parser.set_defaults(demo=False)
        for package in self.packages.values():
            if package.demo_for:
                parser.add_argument('--demo', action='store_true',
                        default=False,
                        help='Build demo package even if files for full '
                            + 'version are available')
                break

        self.argument_parser = parser
        return parser

    def look_for_engines(self, packages, force=False):
        engines = set(p.engine or self.engine for p in packages)
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
            ver = ver.strip('(>=) ')
        else:
            ver = None

        # check engine
        is_installed = PACKAGE_CACHE.is_installed(engine)
        if not is_installed and not PACKAGE_CACHE.is_available(engine):
            return FillResult.IMPOSSIBLE
        if ver is None:
            if is_installed:
                return FillResult.COMPLETE
            else:
                return FillResult.DOWNLOAD_NEEDED

        # check version
        if is_installed:
            current_ver = subprocess.check_output(['dpkg-query',
                   '--show', '--showformat', '${Version}', engine],
                    universal_newlines=True)
        else:
            current_ver = subprocess.check_output(['apt-cache',
                   'madison', engine],
                    universal_newlines=True)
            current_ver = current_ver.splitlines()[0]
            current_ver = current_ver.split('|')[1].strip()

        up_to_date = subprocess.call(['dpkg', '--compare-versions',
                    current_ver, '>=', ver]) == 0
        if up_to_date:
            return FillResult.COMPLETE
        else:
            return FillResult.UPGRADE_NEEDED

    def look_for_files(self, paths=(), search=True, packages=None):
        paths = list(paths)

        if self.save_downloads is not None and self.save_downloads not in paths:
            paths.append(self.save_downloads)

        if packages is None:
            packages = self.packages.values()

        if search:
            for path in self.try_repack_from:
                path = os.path.expanduser(path)
                if os.path.isdir(path) and path not in paths:
                    paths.append(path)

            for package in packages:
                path = '/' + package.install_to
                if os.path.isdir(path) and path not in paths:
                    paths.append(path)
                path = '/usr/share/doc/' + package.name
                if os.path.isdir(path) and path not in paths:
                    paths.append(path)

            for path in self.iter_steam_paths():
                if path not in paths:
                    paths.append(path)

            for path in self.iter_origin_paths():
                if path not in paths:
                    paths.append(path)

        for arg in paths:
            logger.debug('%s...', arg)
            self.consider_file_or_dir(arg)

    def run_command_line(self, args):
        logger.debug('package description:\n%s',
                yaml.safe_dump(self.to_yaml()))

        self.verbose = getattr(args, 'verbose', False)

        preserve_debs = (getattr(args, 'destination', None) is not None)
        install_debs = getattr(args, 'install', True)

        if getattr(args, 'compress', None) is None:
            # default to not compressing if we aren't going to install it
            # anyway
            args.compress = preserve_debs

        self.save_downloads = args.save_downloads

        for package in self.packages.values():
            if args.shortname in package.aliases:
                args.shortname = package.name
                break

        if args.shortname in self.packages:
            if args.packages and args.packages != [args.shortname]:
                not_the_one = [p for p in args.packages if p != args.shortname]
                logger.error('--package="%s" is not consistent with '
                        'selecting "%s"', not_the_one, args.shortname)
                raise SystemExit(1)

            args.demo = True
            args.packages = [args.shortname]
            packages = set([self.packages[args.shortname]])
        elif args.packages:
            args.demo = True
            packages = set()
            for p in args.packages:
                if p not in self.packages:
                    logger.error('--package="%s" is not part of game '
                            '"%s"', p, args.shortname)
                    raise SystemExit(1)
                packages.add(self.packages[p])
        else:
            # if no packages were specified, we require --demo to build
            # a demo if we have its corresponding full game
            packages = set(self.packages.values())

        self.look_for_engines(packages, force=not args.install)

        self.look_for_files(paths=args.paths, search=args.search,
                packages=packages)

        try:
            ready = self.prepare_packages(packages,
                    build_demos=args.demo, download=args.download,
                    log_immediately=bool(args.packages))
        except NoPackagesPossible:
            logger.error('Unable to complete any packages.')
            if self.missing_tools:
                # we already logged warnings about the files as they came up
                self.log_missing_tools()
                raise SystemExit(1)

            # probably not enough files supplied?
            # print the help text, maybe that helps the user to determine
            # what they should have added
            if not os.environ.get('DEBUG'):
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
            self.install_packages(debs)

        engines_alt = set((p.engine or self.engine) for p in ready)
        engines_alt.discard(None)
        engines = set()
        for engine_alt in engines_alt:
            for engine in reversed(engine_alt.split('|')):
                engine = engine.split('(')[0].strip()
                if PACKAGE_CACHE.is_installed(engine):
                    break
            else:
                engines.add(engine)
        if engines:
            print('it is recommended to also install this game engine: %s' % ', '.join(engines))

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
            subprocess.check_call(['oggenc', '-o', track, tmp_wav])
            self.cd_tracks[package.name][i] = track
            if os.path.exists(tmp_wav):
                os.remove(tmp_wav)

        if not self.cd_tracks[package.name]:
            logger.error('Did not rip any CD tracks successfully for "%s"',
                    package.name)
            raise CDRipFailed()

    def get_architecture(self):
        if self._architecture is None:
            self._architecture = subprocess.check_output(['dpkg',
                '--print-architecture']).strip().decode('ascii')

        return self._architecture

    def prepare_packages(self, packages, build_demos=False, download=True,
            log_immediately=True):
        possible = set()

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
            if package.rip_cd and not self.cd_tracks.get(package.name):
                logger.debug('no CD tracks found for %s', package.name)
            elif self.fill_gaps(package,
                    log=log_immediately) is not FillResult.IMPOSSIBLE:
                logger.debug('%s is possible', package.name)
                possible.add(package)
            else:
                logger.debug('%s is impossible', package.name)

        if not possible:
            logger.debug('No packages were possible')

            if log_immediately:
                # we already logged the errors so just give up
                raise NoPackagesPossible()

            # Repeat the process for the first (hopefully only)
            # demo/shareware package, so we can log its errors.
            for package in self.packages.values():
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

        # copy the set so we can alter the original while iterating
        for package in set(possible):
            if package.architecture == 'all':
                continue
            elif package.architecture == 'any':
                # we'll need this later, cache it
                self.get_architecture()
            else:
                archs = package.architecture.split()
                if self.get_architecture() not in archs:
                    logger.warning('cannot produce "%s" on architecture %s',
                            package.name, self.get_architecture())
                    possible.discard(package)

        logger.debug('possible packages: %r', set(p.name for p in possible))
        if not possible:
            raise NoPackagesPossible()

        ready = set()

        for package in possible:
            if (package.better_version
                and self.packages[package.better_version] in possible):
                  logger.info('will not produce "%s" because better version '
                     '"%s" is also available',
                     package.name,
                     package.better_version)
                  continue

            abort = False

            if (package.expansion_for
              and self.packages[package.expansion_for] not in possible
              and not PACKAGE_CACHE.is_installed(package.expansion_for)):
                for fullgame in possible:
                    if fullgame.type == 'full':
                        logger.warning("won't generate '%s' expansion, because "
                          'full game "%s" is neither available nor already installed;'
                          ' and we are packaging "%s" instead.',
                          package.name, package.expansion_for, fullgame.name)
                        abort = True
                        break
                else:
                  logger.warning('will generate "%s" expansion, but full game '
                     '"%s" is neither available nor already installed.',
                     package.name, package.expansion_for)

            if not build_demos and package.demo_for:
                for p in possible:
                    if p.type == 'full':
                        # no point in packaging a demo if we have any full
                        # version
                        logger.info('will not produce "%s" because we have '
                            'the full version "%s"', package.name, p.name)
                        abort = True
                        break
            if abort:
                continue

            for previous in ready:
                if previous.debian.get('conflicts') == package.name:
                    logger.error('will not produce "%s" because it '
                       'conflicts with "%s"', package.name, previous.name)
                    abort = True
            if abort:
                continue

            # keep only prefered language for this virtual package
            virtual = package.debian.get('provides')
            if virtual:
                score = lang_score(package.lang)
                if score == 0:
                    logger.info('will not produce "%s" '
                                'because %s is not in LANGUAGE selection',
                                package.name, package.lang)
                    continue
                for other_p in possible:
                    if other_p.name == package.name:
                        continue
                    other_virtual = other_p.debian.get('provides')
                    if other_virtual != virtual:
                        continue
                    other_score = lang_score(other_p.lang)
                    if score < other_score:
                        logger.info('will not produce "%s" '
                                    'because %s is prefered language',
                                     package.name, other_p.lang)
                        abort = True
                        break
            if abort:
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

        logger.debug('packages ready for building: %r', set(p.name for p in ready))
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

    def locate_steam_icon(self, package):
        id = package.steam.get('id') or self.steam.get('id')
        if not id:
            return
        for res in (128, 96, 64, 32):
            icon = '~/.local/share/icons/hicolor/%dx%d/apps/steam_icon_%d.png'
            icon = os.path.expanduser(icon % (res, res, id))
            if os.path.isfile(icon):
                return icon
        return

    def iter_steam_paths(self, packages=None):
        if packages is None:
            packages = self.packages.values()

        suffixes = set(p.steam.get('path') for p in packages)
        suffixes.add(self.steam.get('path'))
        suffixes.discard(None)
        if not suffixes:
            return

        for prefix in (
                os.path.expanduser('~/.steam'),
                os.path.join(os.environ.get('XDG_DATA_HOME', os.path.expanduser('~/.local/share')),
                    'wineprefixes/steam/drive_c/Program Files/Steam'),
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
                                self.shortname, path)
                        yield os.path.realpath(path)

    def iter_origin_paths(self, packages=None):
        if packages is None:
            packages = self.packages.values()

        suffixes = set(p.origin.get('path') for p in packages)
        suffixes.add(self.origin.get('path'))
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
                            self.shortname, path)
                    yield path


    def construct_package(self, binary):
        return GameDataPackage(binary)

    def check_component(self, package):
        # redistributable packages are redistributable as long as their
        # optional license file is present
        if package.component == 'local':
            return
        for f in package.optional:
             if not self.files[f].license:
                 continue
             if self.file_status[f] is not FillResult.COMPLETE:
                 package.component = 'local'
                 return
        return

    def build_deb(self, package, destination, compress=True):
        """
        If we have all the necessary files for package, build the .deb
        and return the output filename in destination. Otherwise return None.
        """
        destdir = os.path.join(self.get_workdir(), '%s.deb.d' % package.name)

        self.check_component(package)
        if not self.fill_dest_dir(package, destdir):
            # FIXME: probably better as an exception?
            return None

        # it had better have a /usr and a DEBIAN directory or
        # something has gone very wrong
        assert os.path.isdir(os.path.join(destdir, 'usr')), destdir
        assert os.path.isdir(os.path.join(destdir, 'DEBIAN')), destdir

        deb_basename = '%s_%s_all.deb' % (package.name, package.version)

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

        # builtins
        if fmt in ('cat', 'dos2unix', 'tar.gz', 'tar.bz2', 'tar.xz', 'deb', 'zip'):
            return True

        if which(fmt) is not None:
            return True

        if fmt == 'unzip' and (which('7z') or which('unar')):
            return True

        # unace-nonfree package diverts /usr/bin/unace from unace package
        if (fmt == 'unace-nonfree' and
                PACKAGE_CACHE.is_installed('unace-nonfree')):
            return True

        logger.warning('cannot unpack "%s": tool "%s" is not ' +
                       'installed', wanted.name, fmt)
        self.missing_tools.add(fmt)
        self.unpack_failed.add(wanted.name)
        return False

    def log_missing_tools(self):
        if not self.missing_tools:
            return False

        package_map = {
                'id-shr-extract': 'dynamite',
                'lha': 'lhasa',
                '7z': 'p7zip-full',
                'unrar-nonfree': 'unrar',
        }
        packages = set()

        for t in self.missing_tools:
            p = package_map.get(t, t)
            if p is not None:
                packages.add(p)

        logger.warning('installing these packages might help:\n' +
                'apt-get install %s',
                ' '.join(sorted(packages)))

def iter_fat_mounts(folder):
    with open('/proc/mounts', 'r', encoding='utf8') as mounts:
        for line in mounts.readlines():
            mount, type = line.split(' ')[1:3]
            if type in ('fat','vfat', 'ntfs'):
                yield os.path.join(mount, 'Program Files', folder)

def load_games(workdir=None,game='*'):
    games = {}

    for jsonfile in glob.glob(os.path.join(DATADIR, game + '.json')):
        if game == '*' and sys.stderr.isatty():
            print('.', end='', flush=True, file=sys.stderr)
        try:
            g = os.path.basename(jsonfile)
            g = g[:len(g) - 5]

            data = json.load(open(jsonfile, encoding='utf-8'))
            plugin = data.get('plugin', g)

            try:
                plugin = importlib.import_module('game_data_packager.games.%s' %
                        plugin)
                game_data_constructor = plugin.GAME_DATA_SUBCLASS
            except (ImportError, AttributeError) as e:
                logger.debug('No special code for %s: %s', g, e)
                game_data_constructor = GameData

            games[g] = game_data_constructor(g, data, workdir=workdir)
        except:
            print('Error loading %s:\n' % jsonfile)
            raise

    print('\r%s\r' % (' ' * len(games)), end='', flush=True, file=sys.stderr)
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

    base_parser.add_argument('--package', '-p', action='append',
            dest='packages', metavar='PACKAGE',
            help='Produce this data package (may be repeated)')

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
    base_parser.add_argument('--save-downloads', metavar='DIR',
            help='save downloaded files to DIR, and look for files there')

    group = base_parser.add_mutually_exclusive_group()
    group.add_argument('--verbose', action='store_true',
            help='show output from external tools')
    group.add_argument('--no-verbose', action='store_false',
            dest='verbose', help='hide output from external '
             'tools (default)')

    class DumbParser(argparse.ArgumentParser):
        def error(self, message):
            pass

    dumb_parser = DumbParser(parents=(base_parser,),add_help=False)
    dumb_parser.add_argument('game', type=str, nargs='?')
    dumb_parser.add_argument('paths', type=str, nargs='*')
    dumb_parser.add_argument('-h', '--help', action='store_true', dest='h')
    g = dumb_parser.parse_args().game
    if g is None:
        games = load_games(None)
    elif '-h' in sys.argv or '--help' in sys.argv:
        games = load_games(None)
    elif os.path.isfile(os.path.join(DATADIR, '%s.json' % g)):
        games = load_games(None, game=g)
    else:
        games = load_games(None)

    parser = argparse.ArgumentParser(prog='game-data-packager',
            description='Package game files.', parents=(base_parser,),
            epilog='Run "game-data-packager GAME --help" to see ' +
                'game-specific arguments.')

    game_parsers = parser.add_subparsers(dest='shortname',
            title='supported games', metavar='GAME')

    for g in sorted(games.keys()):
        games[g].add_parser(game_parsers, base_parser)

    config = read_config()
    parsed = argparse.Namespace(
            compress=None,
            destination=None,
            download=True,
            verbose=False,
            install=False,
            packages=[],
            save_downloads=None,
            search=True,
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

    parser.parse_args(namespace=parsed)
    logger.debug('parsed command-line arguments into: %r', parsed)

    if parsed.destination is None and not parsed.install:
        logger.error('At least one of --install or --destination is required')
        sys.exit(2)

    if parsed.shortname is None:
        parser.print_help()
        sys.exit(0)

    if (parsed.save_downloads is not None and
            not os.path.isdir(parsed.save_downloads)):
        logger.error('argument "%s" to --save-downloads does not exist',
                parsed.save_downloads)
        sys.exit(2)

    if parsed.shortname in games:
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

    with game:
        game.run_command_line(parsed)
