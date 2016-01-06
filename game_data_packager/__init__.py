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
import glob
import importlib
import io
import json
import logging
import os
import random
import re
import sys
import zipfile

import yaml

from .build import (HashedFile,
        PackagingTask)
from .config import read_config
from .gog import run_gog_meta_mode
from .paths import (DATADIR, USE_VFS)
from .util import ascii_safe
from .steam import run_steam_meta_mode
from .version import (DISTRO, FORMAT, GAME_PACKAGE_VERSION)

logging.basicConfig()
logger = logging.getLogger('game-data-packager')

# For now, we're given these by the shell script wrapper.

if os.environ.get('DEBUG') or os.environ.get('GDP_DEBUG'):
    logging.getLogger().setLevel(logging.DEBUG)
else:
    logging.getLogger().setLevel(logging.INFO)

MD5SUM_DIVIDER = re.compile(r' [ *]?')

class WantedFile(HashedFile):
    def __init__(self, name):
        super(WantedFile, self).__init__(name)
        self.alternatives = []
        self.doc = False
        self.group_members = None
        self._depends = set()
        self._distinctive_name = None
        self.distinctive_size = False
        self.download = None
        self.executable = False
        self.filename = name.split('?')[0]
        self.install_as = self.filename
        self._install_to = None
        self.license = False
        self._look_for = None
        self._provides = set()
        self.provides_files = None
        self._size = None
        self.unpack = None
        self.unsuitable = None

    def apply_group_attributes(self, attributes):
        for k, v in attributes.items():
            assert hasattr(self, k)
            setattr(self, k, v)

    @property
    def distinctive_name(self):
        if self._distinctive_name is not None:
            return self._distinctive_name
        return not self.license
    @distinctive_name.setter
    def distinctive_name(self, value):
        self._distinctive_name = value

    @property
    def install_to(self):
        if self._install_to is not None:
            return self._install_to
        if self.doc:
            return '$pkgdocdir'
        if self.license:
            return '$pkglicensedir'
        return None
    @install_to.setter
    def install_to(self, value):
        self._install_to = value

    @property
    def look_for(self):
        if self.alternatives:
            return set([])
        if self._look_for is not None:
            return self._look_for
        return set([self.filename.lower(), self.install_as.lower()])
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

    def to_yaml(self, expand=True):
        ret = {
            'name': self.name,
        }

        for k in (
                'alternatives',
                'distinctive_size',
                'executable',
                'license',
                'skip_hash_matching',
                ):
            v = getattr(self, k)
            if v:
                if isinstance(v, set):
                    ret[k] = sorted(v)
                else:
                    ret[k] = v

        if expand:
            if self.provides_files:
                ret['provides'] = sorted(f.name for f in self.provides_files)
        else:
            if self.provides:
                ret['provides'] = sorted(self.provides)

        for k in (
                'download',
                'group_members',
                'install_as',
                'size',
                'unsuitable',
                'unpack',
                ):
            v = getattr(self, k)
            if v is not None:
                if isinstance(v, set):
                    ret[k] = sorted(v)
                else:
                    ret[k] = v

        for k in (
                'distinctive_name',
                'install_to',
                'look_for',
                ):
            if expand:
                # use derived value
                v = getattr(self, k)
            else:
                v = getattr(self, '_' + k)

            if v is not None:
                if isinstance(v, set):
                    ret[k] = sorted(v)
                else:
                    ret[k] = v

        return ret

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
        # use this to group together dubs
        self.provides = None
        # use this for games with demo_for/better_version/provides
        self.mutually_exclusive = False
        # expansion for a package outside of this yaml file;
        # may be another GDP package or a package not made by GDP
        self.expansion_for_ext = None

        # distro-agnostic depedencies inside the same .yaml file
        # that can't be handled with expansion_for heuristics
        # *) on Fedora this maps to 'Requires:'
        self._depends = set()

        # The optional marketing name of this version
        self.longname = None

        # This word is used to build package description
        # 'data' / 'PWAD' / 'IWAD' / 'binaries'
        self.data_type = 'data'

        # if not None, override the description completely
        self.long_description = None

        # extra blurb of text added to .deb long description
        self.description = None

        # first line of .deb description, or None to construct one from
        # longname
        self.short_description = None

        # This optional value will overide the game global copyright
        self.copyright = None

        # A blurb of text that is used to build debian/copyright
        self.copyright_notice = None

        # Languages, list of ISO-639 codes
        self.langs = ['en']

        # Where we install files.
        # For instance, if this is 'usr/share/games/quake3' and we have
        # a WantedFile with install_as='baseq3/pak1.pk3' then we would
        # put 'usr/share/games/quake3/baseq3/pak1.pk3' in the .deb.
        # The default is 'usr/share/games/' plus the binary package's name.
        if name.endswith('-data'):
            self.install_to = '$assets/' + name[:len(name) - 5]
        else:
            self.install_to = '$assets/' + name

        # If true, this package is allowed to be empty
        self.empty = False

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

        # format- and distribution-specific overrides
        self.specifics = {}

        # set of names of WantedFile instances to be installed
        self._install = set()

        # set of names of WantedFile instances to be optionally installed
        self._optional = set()

        # set of WantedFile instances for install, with groups expanded
        # only available after load_file_data()
        self.install_files = None
        # set of WantedFile instances for optional, with groups expanded
        self.optional_files = None

        self.version = GAME_PACKAGE_VERSION

        # if not None, install every file provided by the files with
        # these names
        self._install_contents_of = set()

        # CD audio stuff from YAML
        self.rip_cd = {}

        # possible override for disks: tag at top level
        # e.g.: Feeble Files had 2-CD releases too
        self.disks = None

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
    def depends(self):
        return self._depends
    @depends.setter
    def depends(self, value):
        if type(value) is str:
            self._depends = set([value])
        else:
            self._depends = set(value)

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

    def to_yaml(self, expand=True):
        ret = {
            'architecture': self.architecture,
            'component': self.component,
            'install_to': self.install_to,
            'name': self.name,
            'section': self.section,
            'type': self.type,
            'version': self.version,
        }

        for k in (
                'aliases',
                'demo_for',
                'dotemu',
                'gog',
                'origin',
                'rip_cd',
                'specifics',
                'steam',
                'symlinks',
                ):
            v = getattr(self, k)
            if v:
                if isinstance(v, set):
                    ret[k] = sorted(v)
                else:
                    ret[k] = v

        if expand and self.install_files is not None:
            if self.install_files:
                ret['install'] = sorted(f.name for f in self.install_files)
            if self.optional_files:
                ret['optional'] = sorted(f.name for f in self.optional_files)
        else:
            if self.install:
                ret['install'] = sorted(self.install)
            if self.optional:
                ret['optional'] = sorted(self.optional)

        for k in (
                'better_version',
                'copyright',
                'copyright_notice',
                'depends',
                'description',
                'disks',
                'engine',
                'expansion_for',
                'expansion_for_ext',
                'longname',
                'long_description',
                'short_description',
                'url_misc',
                'wiki',
                ):
            v = getattr(self, k)
            if v is not None:
                ret[k] = v

        return ret

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

        # A blurb of text that is used to build debian/copyright
        self.copyright_notice = None

        # Tag fanmade games so they don't screw up year * size regression
        self.fanmade = False

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

        # Number of CD the full game was sold on
        self.disks = None

        self.help_text = ''

        # Extra directories where we might find game files
        self.try_repack_from = []

        # If non-empty, the game requires binary executables which are only
        # available for the given architectures (typically i386)
        self.binary_executables = ''

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

        for k in ('longname', 'copyright', 'compress_deb', 'help_text', 'disks', 'fanmade',
                  'engine', 'genre', 'missing_langs', 'franchise', 'wiki', 'wikibase',
                  'steam', 'gog', 'dotemu', 'origin', 'url_misc', 'wikipedia',
                  'binary_executables', 'copyright_notice'):
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
            assert 'sha1sums' not in data, binary
            assert 'sha256sums' not in data, binary

            if ('DISABLED' in data and
                    not (os.environ.get('DEBUG') or
                        os.environ.get('GDP_DEBUG'))):
                continue
            package = self.construct_package(binary)
            self.packages[binary] = package
            self._populate_package(package, data)

        if 'groups' in self.data:
            groups = self.data['groups']
            assert isinstance(groups, dict), self.shortname
            for group_name, group_data in groups.items():
                attrs = {}
                if isinstance(group_data, dict):
                    members = group_data['group_members']
                    for k, v in group_data.items():
                        if k != 'group_members':
                            attrs[k] = v
                elif isinstance(group_data, (str, list)):
                    members = group_data
                else:
                    raise AssertionError('group %r should be dict, str or list' % group_name)

                group = self._ensure_file(group_name)
                if group.group_members is None:
                    group.group_members = set()
                group.apply_group_attributes(attrs)

                if isinstance(members, str):
                    for line in members.splitlines():
                        f = self._add_hash(line.rstrip('\n'), 'size_and_md5')
                        if f is not None:
                            f.apply_group_attributes(attrs)
                            group.group_members.add(f.name)
                elif isinstance(members, list):
                    for member_name in members:
                        f = self._ensure_file(member_name)
                        f.apply_group_attributes(attrs)
                        group.group_members.add(member_name)
                else:
                    raise AssertionError('group %r members should be str or list' % group_name)

        if 'size_and_md5' in self.data:
            for line in self.data['size_and_md5'].splitlines():
                self._add_hash(line, 'size_and_md5')

        for alg in ('sha1', 'sha256'):
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
            if package.gog:
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
        help_text = ''

        if len(self.packages) > 1 or self.disks:
            help_text = '\npackages possible for this game:\n'
            help = []
            has_multi_cd = False
            for package in self.packages.values():
                disks = package.disks or self.disks or 1
                longname = package.longname or self.longname
                if disks > 1:
                    has_multi_cd = True
                    longname += ' (%dCD)' % disks
                game_type = { 'demo' : 1,
                              'full' : 2,
                              'expansion' : 3}.get(package.type)
                help.append({ 'type' : game_type,
                              'year' : package.copyright or self.copyright,
                              'name' : package.name,
                              'longname': longname})
            for h in sorted(help, key=lambda k: (k['type'], k['year'][2:6], k['name'])):
                help_text += "  %-40s %s\n" % (h['name'],h['longname'])
            if has_multi_cd and self.shortname != 'zork-inquisitor':
                help_text += "\nWARNING: for multi-cd games, you'll first need to ensure that all the data\n"
                help_text += "         is accessible simultaneously, e.g. copy data from CD1 to CD3 in /tmp/cd{1-3}\n"
                help_text += "         and let CD4 *mounted* in the drive.\n\n"
                help_text += "         It's important to first mkdir '/tmp/cd1 /tmp/cd2 /tmp/cd3' because for some\n"
                help_text += "         games there are different files across the disks with the same name that\n"
                help_text += "         would be overwriten.\n\n"
                help_text += "         If /tmp/ is on a tmpfs and you don't have something like 16GB of RAM,\n"
                help_text += "         you'll likely need to store the files somewhere else.\n\n"
                help_text += "         The game can then be packaged this way:\n"
                help_text += "         $ game-data-packager {game} /tmp/cd1 /tmp/cd2 /tmp/cd3 /media/cdrom0\n\n"

        if self.help_text:
            help_text += '\n' + self.help_text

        if self.missing_langs:
            help_text += ('\nThe following languages are not '
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
            help_text += '\nThis game can be bought online here:\n  '
            help_text += '\n  '.join(www)

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
            help_text += '\nExternal links:\n  '
            help_text += '\n  '.join(wikis)

        return help_text

    def to_yaml(self, expand=True):
        files = {}
        groups = {}
        packages = {}
        ret = {}

        def sort_set_values(d):
            ret = {}
            for k, v in d.items():
                assert isinstance(v, set), (repr(k), repr(v))
                ret[k] = sorted(v)
            return ret

        for filename, f in self.files.items():
            if f.group_members is not None:
                groups[filename] = f.to_yaml(expand=expand)
            else:
                files[filename] = f.to_yaml(expand=expand)

        for name, package in self.packages.items():
            packages[name] = package.to_yaml(expand=expand)

        if files:
            ret['files'] = files

        if groups:
            ret['groups'] = groups

        if packages:
            ret['packages'] = packages

        for k in (
                'known_filenames',
                'known_md5s',
                'known_sha1s',
                'known_sha256s',
                'known_sizes',
                'providers',
                ):
            v = getattr(self, k)
            if v:
                ret[k] = sort_set_values(v)

        for k in (
                'copyright_notice',
                'help_text',
                ):
            v = getattr(self, k)
            if v is not None:
                ret[k] = v

        return ret

    def size(self, package):
        size_min = 0
        size_max = 0
        for filename in package._install:
           file = self.files[filename]
           if file.alternatives:
               # 'or 0' is a workaround for the files without known size
               size_min += min(set(self.files[a].size or 0 for a in file.alternatives))
               size_max += max(set(self.files[a].size or 0 for a in file.alternatives))
           elif file.size:
               size_min += file.size
               size_max += file.size
        for filename in package._optional:
           file = self.files[filename]
           if file.alternatives:
               size_max += max(set(self.files[a].size for a in file.alternatives))
           elif file.size:
               size_max += file.size
        return (size_min, size_max)

    def _populate_package(self, package, d):
        for k in ('expansion_for', 'expansion_for_ext', 'longname', 'symlinks', 'install_to',
                'install_contents_of', 'description', 'depends',
                'rip_cd', 'architecture', 'aliases', 'better_version', 'langs', 'mutually_exclusive',
                'copyright', 'engine', 'lang', 'component', 'section', 'disks', 'provides',
                'steam', 'gog', 'dotemu', 'origin', 'url_misc', 'wiki', 'copyright_notice',
                'short_description', 'long_description', 'empty'):
            if k in d:
                setattr(package, k, d[k])

        for port in (
                # packaging formats (we treat "debian" as "any dpkg-based"
                # for historical reasons)
                'debian', 'rpm',
                # specific distributions
                'arch', 'fedora', 'suse',
                ):
            if port in d:
                package.specifics[port] = d[port]

            # FIXME: this object's contents should be 1:1 mapped from the
            # YAML, and not format- or distribution-specific.
            # Distribution-specific stuff should be done in the PackagingTask
            # or PackagingSystem
            if port in d and (FORMAT == port or DISTRO == port or
                    (FORMAT == 'deb' and port == 'debian')):
                for k in ('engine', 'install_to', 'description', 'provides'):
                    if k in d[port]:
                        setattr(package, k, d[port][k])

        # Fedora doesn't handle alternatives, everything must be handled with
        # virtual packages
        if FORMAT == 'rpm':
            for dep in package.depends:
                assert '|' not in dep, (package.name, package.depends)

        assert self.copyright or package.copyright, package.name
        assert package.component in ('main', 'contrib', 'non-free', 'local')
        assert package.component == 'local' or 'license' in d
        assert package.section in ('games', 'doc'), 'unsupported'
        assert type(package.langs) is list
        assert type(package.mutually_exclusive) is bool

        if 'debian' in d:
            debian = d['debian']
            assert type(debian) is dict
            for k, v in debian.items():
                assert k in ('breaks', 'conflicts', 'depends', 'provides',
                             'recommends', 'replaces', 'suggests',
                             'build-depends'), (package.name, debian)
                assert type(v) in (str, list), (package.name, debian)
                if type(v) == str:
                    assert ',' not in v, (package.name, debian)
                    package.specifics['debian'][k] = [v]
                assert package.name not in v, \
                   "A package shouldn't extraneously %s itself" % k

        if 'provides' in d:
            assert type(package.provides) is str
            assert package.name != package.provides, \
               "A package shouldn't extraneously provide itself"

        if 'install_to' in d:
            assert '$assets/' + package.name != d['install_to'] + '-data', \
                "install_to %s is extraneous" % package.name

        if 'demo_for' in d:
            if package.disks is None:
                package.disks = 1
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

        if package.mutually_exclusive:
            assert package.demo_for or package.better_version or package.provides

        if 'expansion_for' in d:
            if package.disks is None:
                package.disks = 1
            assert package.name != d['expansion_for'], \
                   "a game can't be an expansion for itself"
            if 'demo_for' in d:
                raise AssertionError("%r can't be both a demo of %r and an " +
                        "expansion for %r" % (package.name, d.demo_for,
                            d.expansion_for))

        if 'install' in d:
            for filename in d['install']:
                package.install.add(filename)

        if 'optional' in d:
            assert isinstance(d['optional'], list), package.name
            for filename in d['optional']:
                package.optional.add(filename)

        if 'doc' in d:
            assert isinstance(d['doc'], list), package.name
            for filename in d['doc']:
                package.optional.add(filename)

        if 'license' in d:
            assert isinstance(d['license'], list), package.name
            for filename in d['license']:
                package.optional.add(filename)

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
                    'executable',
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

        parser = parsers.add_parser(self.shortname,
                help=longname, aliases=aliases,
                description='Package data files for %s.' % longname,
                epilog=ascii_safe(self.edit_help_text()),
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

        if alg == 'size_and_md5':
            size, hexdigest, filename = line.split(None, 2)
            alg = 'md5'
        else:
            size = None
            hexdigest, filename = MD5SUM_DIVIDER.split(line, 1)

        f = self._ensure_file(filename)

        if size is not None and size != '_':
            f.size = int(size)

        if hexdigest is not None and hexdigest != '_':
            setattr(f, alg, hexdigest)

        return f

    def _populate_groups(self, stream):
        current_group = None
        attributes = {}

        for line in stream:
            stripped = line.strip()
            if stripped == '' or stripped.startswith('#'):
                continue

            if stripped.startswith('['):
                assert stripped.endswith(']'), repr(stripped)
                current_group = self._ensure_file(stripped[1:-1])
                if current_group.group_members is None:
                    current_group.group_members = set()
                attributes = {}
            elif stripped.startswith('{'):
                attributes = {}
                attributes = json.loads(stripped)
                assert current_group is not None
                current_group.apply_group_attributes(attributes)
            else:
                f = self._add_hash(stripped, 'size_and_md5')
                f.apply_group_attributes(attributes)
                assert current_group is not None
                current_group.group_members.add(f.name)

    def load_file_data(self, use_vfs=USE_VFS):
        if self.loaded_file_data:
            return

        logger.debug('loading full data')

        if use_vfs:
            if isinstance(use_vfs, str):
                zip = use_vfs
            else:
                zip = os.path.join(DATADIR, 'vfs.zip')
            with zipfile.ZipFile(zip, 'r') as zf:
                files = zf.namelist()
                filename = '%s.files' % self.shortname
                if filename in files:
                    logger.debug('... %s/%s', zip, filename)
                    jsondata = zf.open(filename).read().decode('utf-8')
                    data = json.loads(jsondata)
                    self._populate_files(data)

                filename = '%s.groups' % self.shortname
                if filename in files:
                    logger.debug('... %s/%s', zip, filename)
                    stream = io.TextIOWrapper(zf.open(filename), encoding='utf-8')
                    self._populate_groups(stream)

                for alg in ('sha1', 'sha256', 'size_and_md5'):
                    filename = '%s.%s%s' % (self.shortname, alg,
                            '' if alg == 'size_and_md5' else 'sums')
                    if filename in files:
                        logger.debug('... %s/%s', zip, filename)
                        rawdata = zf.open(filename).read().decode('utf-8')
                        for line in rawdata.splitlines():
                            self._add_hash(line.rstrip('\n'), alg)
        else:
            vfs = os.path.join(DATADIR, 'vfs')

            if not os.path.isdir(vfs):
                vfs = DATADIR


            filename = os.path.join(vfs, '%s.files' % self.shortname)
            if os.path.isfile(filename):
                logger.debug('... %s', filename)
                data = json.load(open(filename, encoding='utf-8'))
                self._populate_files(data)

            filename = os.path.join(vfs, '%s.groups' % self.shortname)
            if os.path.isfile(filename):
                logger.debug('... %s', filename)
                stream = open(filename, encoding='utf-8')
                self._populate_groups(stream)

            for alg in ('sha1', 'sha256', 'size_and_md5'):
                filename = os.path.join(vfs, '%s.%s%s' %
                        (self.shortname, alg,
                            '' if alg == 'size_and_md5' else 'sums'))
                if os.path.isfile(filename):
                    logger.debug('... %s', filename)
                    with open(filename) as f:
                        for line in f:
                            self._add_hash(line.rstrip('\n'), alg)

        self.loaded_file_data = True

        for package in self.packages.values():
            d = self.data['packages'][package.name]

            for filename in d.get('doc', ()):
                f = self._ensure_file(filename)
                f.doc = True

            for filename in d.get('license', ()):
                f = self._ensure_file(filename)
                f.license = True

            package.install_files = set(self._iter_expand_groups(package.install))
            package.optional_files = set(self._iter_expand_groups(package.optional))

            for provider in package.install_contents_of:
                for f in self._iter_expand_groups(self.files[provider].provides):
                    if f not in package.optional_files:
                        package.install_files.add(f)

        # _iter_expand_groups could change the contents of self.files
        for filename, f in list(self.files.items()):
            f.provides_files = set(self._iter_expand_groups(f.provides))

        for filename, f in self.files.items():
            f.provides_files = set(self._iter_expand_groups(f.provides))

            for provided in f.provides_files:
                self.providers.setdefault(provided.name, set()).add(filename)

            if f.alternatives or f.group_members is not None:
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

        # check for different files that shares same md5 & look_for
        for file in self.known_md5s:
            if len(self.known_md5s[file]) == 1:
                continue
            all_lf = set()
            for f in self.known_md5s[file]:
                assert not all_lf.intersection(self.files[f].look_for),(
                       'duplicate file description in %s: %s' %
                       (self.shortname, ', '.join(self.known_md5s[file])) )
                all_lf |= self.files[f].look_for

        # consistency check
        for package in self.packages.values():
            for provider in package.install_contents_of:
                assert provider in self.files, (package.name, provider)
                for f in self.files[provider].provides_files:
                    assert (f in package.install_files or
                            f in package.optional_files), (package.name, f.name)

            if package.rip_cd:
                # we only support Ogg Vorbis for now
                assert package.rip_cd['encoding'] == 'vorbis', package.name
                self.rip_cd_packages.add(package)

            # there had better be something it wants to install, unless
            # specifically marked as empty
            if package.empty:
                assert not package.install_files, package.name
                assert not package.rip_cd, package.name
            else:
                assert package.install_files or package.rip_cd, \
                    package.name

            # check internal depedencies
            for demo_for_item in package.demo_for:
                assert demo_for_item in self.packages, demo_for_item
            if package.expansion_for:
                if package.expansion_for not in self.packages:
                    for p in self.packages.values():
                        if package.expansion_for == p.provides:
                            break
                    else:
                        raise Exception('virtual pkg %s not found' % package.expansion_for)
            assert (not package.better_version or
              package.better_version in self.packages), package.better_version

            # check for stale missing_langs
            if not package.demo_for:
                assert not set(package.langs).intersection(self.missing_langs)

            # check for missing 'version:'
            for file in package.install_files:
                if self.files[file.name].filename == 'version':
                    assert package.version != GAME_PACKAGE_VERSION, package.name

        for filename, wanted in self.files.items():
            if wanted.unpack:
                assert 'format' in wanted.unpack, filename
                assert wanted.provides_files, filename
                for f in wanted.provides_files:
                    assert f.alternatives == [], (filename, f.name)
                if wanted.unpack['format'] == 'cat':
                    assert len(wanted.provides) == 1, filename
                    assert isinstance(wanted.unpack['other_parts'],
                            list), filename
                    for other_part in wanted.unpack['other_parts']:
                        assert other_part in self.files, (filename, other_part)
                elif wanted.unpack['format'] == 'xdelta':
                    assert len(wanted.provides) == 1, filename
                    assert len(wanted.unpack['other_parts']) == 1, filename
                    assert isinstance(wanted.unpack['other_parts'][0], str), filename
                    assert wanted.unpack['other_parts'][0] in self.files, filename

            if wanted.alternatives:
                for alt_name in wanted.alternatives:
                    alt = self.files[alt_name]
                    # an alternative can't be a placeholder for alternatives
                    assert not alt.alternatives, alt_name
                    # an alternative can't be a placeholder for a group
                    assert alt.group_members is None, alt_name

                # if this is a placeholder for a bunch of alternatives, then
                # it doesn't make sense for it to have a defined checksum
                # or size
                assert wanted.md5 is None, wanted.name
                assert wanted.sha1 is None, wanted.name
                assert wanted.sha256 is None, wanted.name
                assert wanted.size is None, wanted.name

                # a placeholder for alternatives can't also be a placeholder
                # for a group
                assert wanted.group_members is None, wanted.name
            elif wanted.group_members is not None:
                for member_name in wanted.group_members:
                    assert member_name in self.files

                assert wanted.md5 is None, wanted.name
                assert wanted.sha1 is None, wanted.name
                assert wanted.sha256 is None, wanted.name
                assert wanted.size is None, wanted.name
                assert not wanted.unpack, wanted.unpack
            else:
                assert (wanted.size is not None or filename in
                        self.data.get('unknown_sizes', ())
                        ), (self.shortname, wanted.name)

    def _iter_expand_groups(self, grouped):
        """Given a set of strings that are either filenames or groups,
        yield the WantedFile instances for those names or the members of
        those groups, recursively.
        """
        for filename in grouped:
            wanted = self._ensure_file(filename)
            if wanted.group_members is not None:
                for x in self._iter_expand_groups(wanted.group_members):
                    yield x
            else:
                yield wanted

    def construct_task(self, **kwargs):
        self.load_file_data()
        return PackagingTask(self, **kwargs)

    def construct_package(self, binary):
        return GameDataPackage(binary)

    def gog_download_name(self, package):
        if package.gog == False:
            return
        gog = package.gog or self.gog
        return gog.get('game') or gog.get('url')

def load_games(game='*', use_vfs=USE_VFS, use_yaml=False):
    progress = (game == '*' and sys.stderr.isatty() and
            not logger.isEnabledFor(logging.DEBUG))
    games = {}

    if use_vfs:
        if isinstance(use_vfs, str):
            zip = use_vfs
        else:
            zip = os.path.join(DATADIR, 'vfs.zip')

        with zipfile.ZipFile(zip, 'r') as zf:
            if game == '*':
                for entry in zf.infolist():
                    if entry.filename.split('.')[-1] == 'json':
                        jsonfile = '%s/%s' % (zip, entry.filename)
                        jsondata = zf.open(entry).read().decode('utf-8')
                        load_game(progress, games, jsonfile, jsondata)
            else:
                jsonfile = game + '.json'
                jsondata = zf.open(jsonfile).read().decode('utf-8')
                load_game(progress, games, '%s/%s' % (zip, jsonfile), jsondata)
    elif use_yaml:
        for yamlfile in glob.glob(os.path.join('data/', game + '.yaml')):
            yamldata = open(yamlfile, encoding='utf-8').read()
            load_game(progress, games, yamlfile, yamldata)
    else:
        vfs = os.path.join(DATADIR, 'vfs')

        if not os.path.isdir(vfs):
            vfs = DATADIR

        for jsonfile in glob.glob(os.path.join(vfs, game + '.json')):
            jsondata = open(jsonfile, encoding='utf-8').read()
            load_game(progress, games, jsonfile, jsondata)

    if progress:
        print('\r%s\r' % (' ' * (len(games) // 4 + 1)), end='', flush=True, file=sys.stderr)

    return games

def load_game(progress, games, filename, content):
        if progress:
            animation = ['.','-','*','#']
            modulo = int(load_game.counter) % len(animation)
            if modulo > 0:
                print('\b', end='', flush=True, file=sys.stderr)
            print(animation[modulo], end='', flush=True, file=sys.stderr)
            load_game.counter += 1
        try:
            g = os.path.basename(filename)
            g = g[:len(g) - 5]

            if filename.endswith('.yaml'):
                data = yaml.load(content, Loader=yaml.CSafeLoader)
            else:
                data = json.loads(content)

            plugin = data.get('plugin', g)
            plugin = plugin.replace('-', '_')

            try:
                plugin = importlib.import_module('game_data_packager.games.%s' %
                        plugin)
                game_data_constructor = plugin.GAME_DATA_SUBCLASS
            except (ImportError, AttributeError) as e:
                logger.debug('No special code for %s: %s', g, e)
                assert 'game_data_packager.games' in e.msg, e
                game_data_constructor = GameData

            games[g] = game_data_constructor(g, data)
        except:
            print('Error loading %s:\n' % filename)
            raise

load_game.counter = 0

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
        task.run_command_line(parsed)
