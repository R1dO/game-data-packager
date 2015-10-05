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

import argparse
import glob
import importlib
import json
import logging
import os
import random
import re
import sys

from .build import (HashedFile,
        PackagingTask)
from .config import read_config
from .gog import run_gog_meta_mode
from .paths import DATADIR
from .util import ascii_safe
from .steam import run_steam_meta_mode
from .version import GAME_PACKAGE_VERSION

logging.basicConfig()
logger = logging.getLogger('game-data-packager')

# For now, we're given these by the shell script wrapper.

if os.environ.get('DEBUG'):
    logging.getLogger().setLevel(logging.DEBUG)
else:
    logging.getLogger().setLevel(logging.INFO)

MD5SUM_DIVIDER = re.compile(r' [ *]?')

class WantedFile(HashedFile):
    def __init__(self, name):
        super(WantedFile, self).__init__(name)
        self.alternatives = []
        self.distinctive_name = True
        self.distinctive_size = False
        self.download = None
        self.filename = name.split('?')[0]
        self.install_as = self.filename
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
            self._look_for = set([self.filename.lower(), self.install_as.lower()])
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

        # expansion's dedicated Wiki page, appended to GameData.wikibase
        self.wiki = None

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

        # archives actually used to built a package
        self.used_sources = set()

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
    def __init__(self, shortname, data):
        # The name of the game for command-line purposes, e.g. quake3
        self.shortname = shortname

        # Other command-line names for this game
        self.aliases = set()

        # The formal name of the game, e.g. Quake III Arena
        self.longname = shortname.title()

        # Engine's wiki base URL, provided by engine plugin
        self.wikibase = ''
        # Game page on engine's wiki
        self.wiki = None

        # Wikipedia page, linked from per-engine wikis
        self.wikipedia = None

        # The franchise this game belongs to.
        # this is used to loosely ties various .yaml files
        self.franchise = None

        # The one-line copyright notice used to build debian/copyright
        self.copyright = None

        # The game engine used to run the game (package name)
        self.engine = None

        # Game translations known to exists, but missing in 'packages:'
        # list of ISO-639 codes
        self.missing_langs = []

        # The game genre, as seen in existing .desktop files or
        # http://en.wikipedia.org/wiki/List_of_video_game_genres
        self.genre = None

        # binary package name => GameDataPackage
        self.packages = {}

        # Subset of packages.values() with nonempty rip_cd
        self.rip_cd_packages = set()

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

        # How to compress the .deb:
        # True: dpkg-deb's default
        # False: -Znone
        # str: -Zstr (gzip, xz or none)
        # list: arbitrary options (e.g. -z9 -Zgz -Sfixed)
        self.compress_deb = True

        for k in ('longname', 'copyright', 'compress_deb', 'help_text', 
                  'engine', 'genre', 'missing_langs', 'franchise', 'wiki', 'wikibase',
                  'steam', 'gog', 'dotemu', 'origin', 'url_misc', 'wikipedia'):
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

        # True if the lazy load of full file info has been done
        self.loaded_file_data = False

        # Map from WantedFile name to instance.
        # { 'baseq3/pak1.pk3': WantedFile instance }
        self.files = {}

        # Map from WantedFile name to a set of names of WantedFile instances
        # from which the file named in the key can be extracted or generated.
        # { 'baseq3/pak1.pk3': set(['linuxq3apoint-1.32b-3.x86.run']) }
        self.providers = {}

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

        if 'size_and_md5' in self.data:
            for line in self.data['size_and_md5'].splitlines():
                self._add_hash(line, 'size_and_md5')

        for alg in ('ck', 'md5', 'sha1', 'sha256'):
            if alg + 'sums' in self.data:
                for line in self.data[alg + 'sums'].splitlines():
                    self._add_hash(line, alg)

        # compute webshop URL's
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
        if steam_id:
            self.url_steam = 'http://store.steampowered.com/app/%s/' % min(steam_id)
        if gog_url:
            self.url_gog = 'http://www.gog.com/game/' + gog_url + '?pp=' + gog_pp
        if dotemu_id:
            self.url_dotemu = 'http://www.dotemu.com/affiliate/%s/node/%d' % (
                              dotemu_pp, dotemu_id)

    def edit_help_text(self):
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
        www = list()
        if self.url_steam and '://store.steampowered.com/' not in self.help_text:
                www.append(self.url_steam)
        if self.url_gog and '://www.gog.com/' not in self.help_text:
                www.append(self.url_gog)
        if self.url_dotemu:
            www.append(self.url_dotemu)
        if self.url_misc:
            www.append(self.url_misc)
        if www:
            random.shuffle(www)
            self.help_text += '\nThis game can be bought online here:\n  '
            self.help_text += '\n  '.join(www)

        wikis = list()
        if self.wiki:
            wikis.append(self.wikibase + self.wiki)
        for p in sorted(self.packages.keys()):
            package = self.packages[p]
            if package.wiki:
                wikis.append(self.wikibase + package.wiki)
        if self.wikipedia:
            wikis.append(self.wikipedia)
        if wikis:
            self.help_text += '\nExternal links:\n  '
            self.help_text += '\n  '.join(wikis)

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
                'steam', 'gog', 'dotemu', 'origin', 'url_misc', 'wiki'):
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

    def add_parser(self, parsers, base_parser, **kwargs):
        aliases = self.aliases

        longname = ascii_safe(self.longname)

        self.edit_help_text()

        parser = parsers.add_parser(self.shortname,
                help=longname, aliases=aliases,
                description='Package data files for %s.' % longname,
                epilog=ascii_safe(self.help_text),
                formatter_class=argparse.RawDescriptionHelpFormatter,
                parents=(base_parser,),
                **kwargs)

        group = parser.add_mutually_exclusive_group()
        group.add_argument('--search', action='store_true', default=True,
            help='look for installed files in Steam and other likely places ' +
                '(default)')
        group.add_argument('--no-search', action='store_false',
            dest='search',
            help='only look in paths provided on the command line')

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

    def _add_hash(self, line, alg):
        """Parse one line from md5sums-style data."""

        stripped = line.strip()
        if stripped == '' or stripped.startswith('#'):
            return

        if alg == 'ck':
            _, size, filename = line.split(None, 2)
            hexdigest = None
        elif alg == 'size_and_md5':
            size, hexdigest, filename = line.split(None, 2)
            alg = 'md5'
        else:
            size = None
            hexdigest, filename = MD5SUM_DIVIDER.split(line, 1)

        f = self._ensure_file(filename)

        if size is not None:
            f.size = int(size)

        if hexdigest is not None:
            setattr(f, alg, hexdigest)

    def load_file_data(self):
        if self.loaded_file_data:
            return

        logger.debug('loading full data')

        filename = os.path.join(DATADIR, '%s.files' % self.shortname)
        if os.path.isfile(filename):
            logger.debug('... %s', filename)
            data = json.load(open(filename, encoding='utf-8'))
            self._populate_files(data)

        for  alg in ('ck', 'md5', 'sha1', 'sha256', 'size_and_md5'):
            filename = os.path.join(DATADIR, '%s.%s%s' %
                    (self.shortname, alg,
                        '' if alg == 'size_and_md5' else 'sums'))
            if os.path.isfile(filename):
                logger.debug('... %s', filename)
                with open(filename) as f:
                    for line in f:
                        self._add_hash(line.rstrip('\n'), alg)

        self.loaded_file_data = True

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
                   'hipnotic/pak0.pak?qdq_glquake_compat',
                   'resource.1?106_cd',
                   'vox0000.lab?unpatched',
                   ), (self.shortname, wanted.name)

    def construct_task(self, **kwargs):
        self.load_file_data()
        return PackagingTask(self, **kwargs)

    def construct_package(self, binary):
        return GameDataPackage(binary)

    def gog_download_name(self, package):
        gog = package.gog or self.gog
        if not gog:
            return
        return gog.get('game', gog['url'])

def load_games(game='*'):
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

            games[g] = game_data_constructor(g, data)
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

    base_parser.add_argument('--install-method', metavar='METHOD',
            dest='install_method',
            help='Use METHOD (apt, dpkg, gdebi, gdebi-gtk, gdebi-kde) ' +
                'to install packages')

    base_parser.add_argument('--gain-root-command', metavar='METHOD',
            dest='gain_root_command',
            help='Use METHOD (su, sudo, pkexec) to gain root if needed')

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

    class DumbParser(argparse.ArgumentParser):
        def error(self, message):
            pass

    dumb_parser = DumbParser(parents=(base_parser,),add_help=False)
    dumb_parser.add_argument('game', type=str, nargs='?')
    dumb_parser.add_argument('paths', type=str, nargs='*')
    dumb_parser.add_argument('-h', '--help', action='store_true', dest='h')
    g = dumb_parser.parse_args().game
    if g is None:
        games = load_games()
    elif '-h' in sys.argv or '--help' in sys.argv:
        games = load_games()
    elif os.path.isfile(os.path.join(DATADIR, '%s.json' % g)):
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
        task.run_command_line(parsed)
