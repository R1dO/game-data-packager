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

from .build import (PackagingTask)
from .data import (FileGroup, Package, PackageRelation, WantedFile)
from .paths import (DATADIR, USE_VFS)
from .util import ascii_safe
from .version import (GAME_PACKAGE_VERSION)

logger = logging.getLogger(__name__)

if os.environ.get('DEBUG') or os.environ.get('GDP_DEBUG'):
    logging.getLogger().setLevel(logging.DEBUG)
else:
    logging.getLogger().setLevel(logging.INFO)

MD5SUM_DIVIDER = re.compile(r' [ *]?')

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

        # binary package name => Package
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

        if isinstance(self.engine, dict) and 'generic' not in self.engine:
            self.engine['generic'] = None

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

        # Map from FileGroup name to instance.
        self.groups = {}

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

            if 'DISABLED' in data:
                continue
            package = self.construct_package(binary, data)
            self.packages[binary] = package
            self._populate_package(package, data)

        if 'groups' in self.data:
            groups = self.data['groups']
            assert isinstance(groups, dict), self.shortname

            # Before doing anything else, we do one pass through the list
            # of groups to record that each one is a group, so that when we
            # encounter an entry that is not known to be a group in a
            # group's members, it is definitely a file.
            for group_name in groups:
                self._ensure_group(group_name)

            for group_name, group_data in groups.items():
                group = self.groups[group_name]
                attrs = {}

                if isinstance(group_data, dict):
                    members = group_data['group_members']
                    for k, v in group_data.items():
                        if k != 'group_members':
                            assert hasattr(group, k), k
                            setattr(group, k, v)
                            attrs[k] = v
                elif isinstance(group_data, (str, list)):
                    members = group_data
                else:
                    raise AssertionError('group %r should be dict, str or list' % group_name)

                if isinstance(members, str):
                    for line in members.splitlines():
                        f = self._add_hash(line.rstrip('\n'), 'size_and_md5')
                        if f is not None:
                            # f may be a WantedFile or a FileGroup,
                            # this works for either
                            group.group_members.add(f.name)
                            group.apply_group_attributes(f)

                elif isinstance(members, list):
                    for member_name in members:
                        f = self.groups.get(member_name)

                        if f is None:
                            f = self._ensure_file(member_name)

                        # f may be a WantedFile or a FileGroup,
                        # this works for either
                        group.group_members.add(f.name)
                        group.apply_group_attributes(f)
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

    def to_data(self, expand=True):
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
            files[filename] = f.to_data(expand=expand)

        for name, g in self.groups.items():
            groups[name] = g.to_data(expand=expand)

        for name, package in self.packages.items():
            packages[name] = package.to_data(expand=expand)

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
        for file in package.install_files:
           if file.alternatives:
               # 'or 0' is a workaround for the files without known size
               size_min += min(set(self.files[a].size or 0 for a in file.alternatives))
               size_max += max(set(self.files[a].size or 0 for a in file.alternatives))
           elif file.size:
               size_min += file.size
               size_max += file.size
        for file in package.optional_files:
           if file.alternatives:
               size_max += max(set(self.files[a].size for a in file.alternatives))
           elif file.size:
               size_max += file.size
        return (size_min, size_max)

    def _populate_package(self, package, d):
        for k in ('expansion_for', 'expansion_for_ext', 'longname', 'symlinks', 'install_to',
                'description',
                'rip_cd', 'architecture', 'aliases', 'better_versions', 'langs', 'mutually_exclusive',
                'copyright', 'engine', 'lang', 'component', 'section', 'disks', 'provides',
                'steam', 'gog', 'dotemu', 'origin', 'url_misc', 'wiki', 'copyright_notice',
                'short_description', 'long_description', 'empty'):
            if k in d:
                setattr(package, k, d[k])

        if isinstance(package.engine, dict):
            if isinstance(self.engine, dict):
                for k in self.engine:
                    package.engine.setdefault(k, self.engine[k])
            else:
                package.engine.setdefault('generic', self.engine)

        if isinstance(package.install_to, dict):
            package.install_to.setdefault('generic',
                    package.default_install_to)

        if 'better_version' in d:
            assert 'better_versions' not in d
            package.better_versions = set([d['better_version']])

        for rel in package.relations:
            if rel in d:
                related = d[rel]

                if isinstance(related, (str, dict)):
                    related = [related]
                else:
                    assert isinstance(related, list)

                for x in related:
                    pr = PackageRelation(x)
                    # Fedora doesn't handle alternatives, everything must
                    # be handled with virtual packages. Assume the same is
                    # true for everything except dpkg.
                    assert not pr.alternatives, pr

                    if pr.contextual:
                        for context, specific in pr.contextual.items():
                            assert (context == 'deb' or
                                    not specific.alternatives), pr

                    if pr.package == 'libjpeg.so.62':
                        # we can't really translate versions for libjpeg,
                        # since it could be either libjpeg6b or libjpeg-turbo
                        assert pr.version is None

                    package.relations[rel].append(pr)

        for port in ('debian', 'rpm', 'arch', 'fedora', 'mageia', 'suse'):
            assert port not in d, 'use {deb: foo-dfsg, generic: foo} syntax'

        assert self.copyright or package.copyright, package.name
        assert package.component in ('main', 'contrib', 'non-free', 'local')
        assert package.component == 'local' or 'license' in d
        assert package.section in ('games', 'doc'), 'unsupported'
        assert type(package.langs) is list
        assert type(package.mutually_exclusive) is bool

        for rel, related in package.relations.items():
            for pr in related:
                packages = set()
                if pr.contextual:
                    for p in pr.contextual.values():
                        packages.add(p.package)
                elif pr.alternatives:
                    for p in pr.alternatives:
                        packages.add(p.package)
                else:
                    packages.add(pr.package)
                assert package.name not in packages, \
                   "%s should not be in its own %s set" % (package.name, rel)

        if 'install_to' in d and isinstance(d['install_to'], str):
            assert d['install_to'] != package.default_install_to, \
                "install_to for %s is extraneous" % package.name

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
            assert package.demo_for or package.better_versions or package.provides

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

        if 'rip_cd' in d:
            package.data_type = 'music'
        elif package.section == 'doc':
            package.data_type = 'documentation'

    def _populate_files(self, d, **kwargs):
        if d is None:
            return

        for filename, data in d.items():
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

    def _ensure_group(self, name):
        assert name not in self.files, (self.shortname, name)

        if name not in self.groups:
            logger.debug('Adding group: %s', name)
            self.groups[name] = FileGroup(name)

        return self.groups[name]

    def _ensure_file(self, name):
        assert name not in self.groups, (self.shortname, name)

        if name not in self.files:
            logger.debug('Adding file: %s', name)
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

        if filename in self.groups:
            assert size in (None, '_'), \
                    "%s group %s should not have size" % (
                            self.shortname, filename)
            assert hexdigest in (None, '_'), \
                    "%s group %s should not have hexdigest" % (
                            self.shortname, filename)
            return self.groups[filename]

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

            # The group data starts with a list of groups. This is necessary
            # so we can know whether a group member, encountered later on in
            # the data, is a group or a file.
            if stripped.startswith('*'):
                assert current_group is None
                self._ensure_group(stripped[1:])
            # After that, [Group] opens a section for each group
            elif stripped.startswith('['):
                assert stripped.endswith(']'), repr(stripped)
                current_group = self._ensure_group(stripped[1:-1])
                attributes = {}
            # JSON metadata is on a line with {}
            elif stripped.startswith('{'):
                assert current_group is not None
                attributes = json.loads(stripped)

                for k, v in attributes.items():
                    assert hasattr(current_group, k), k
                    setattr(current_group, k, v)
            # Every other line is a member, either a file or a group
            else:
                f = self._add_hash(stripped, 'size_and_md5')
                # f can either be a WantedFile or a FileGroup here
                assert current_group is not None
                current_group.apply_group_attributes(f)
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

                filename = '%s.groups' % self.shortname
                if filename in files:
                    logger.debug('... %s/%s', zip, filename)
                    stream = io.TextIOWrapper(zf.open(filename), encoding='utf-8')
                    self._populate_groups(stream)

                filename = '%s.files' % self.shortname
                if filename in files:
                    logger.debug('... %s/%s', zip, filename)
                    jsondata = zf.open(filename).read().decode('utf-8')
                    data = json.loads(jsondata)
                    self._populate_files(data)

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

            filename = os.path.join(vfs, '%s.groups' % self.shortname)
            if os.path.isfile(filename):
                logger.debug('... %s', filename)
                stream = open(filename, encoding='utf-8')
                self._populate_groups(stream)

            filename = os.path.join(vfs, '%s.files' % self.shortname)
            if os.path.isfile(filename):
                logger.debug('... %s', filename)
                data = json.load(open(filename, encoding='utf-8'))
                self._populate_files(data)

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
                f = self.groups.get(filename)

                if f is None:
                    f = self._ensure_file(filename)

                # WantedFile and FileGroup both have this
                assert hasattr(f, 'doc')
                f.doc = True

            for filename in d.get('license', ()):
                f = self.groups.get(filename)

                if f is None:
                    f = self._ensure_file(filename)

                # WantedFile and FileGroup both have this
                assert hasattr(f, 'license')
                f.license = True

            package.install_files = set(self._iter_expand_groups(package.install))
            package.optional_files = set(self._iter_expand_groups(package.optional))

        # _iter_expand_groups could change the contents of self.files
        for filename, f in list(self.files.items()):
            f.provides_files = set(self._iter_expand_groups(f.provides))

        for filename, f in self.files.items():
            for provided in f.provides_files:
                self.providers.setdefault(provided.name, set()).add(filename)

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
                    # It needs to be provided on all distributions,
                    # so we can ignore contextual package relations,
                    # which have package = None.
                    #
                    # We also already asserted that distro-independent
                    # relations don't have alternatives (not that they
                    # would be meaningful for provides).
                    provider = None

                    for other in self.packages.values():
                        for provided in other.relations['provides']:
                            if package.expansion_for == provided.package:
                                provider = other
                                break

                        if provider is not None:
                            break
                    else:
                        raise Exception('%s: %s: virtual package %s not found' %
                                (self.shortname, package.name,
                                    package.expansion_for))

            if package.better_versions:
                for v in package.better_versions:
                    assert v in self.packages, v

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

                # if this is a placeholder for a bunch of alternatives, then
                # it doesn't make sense for it to have a defined checksum
                # or size
                assert wanted.md5 is None, wanted.name
                assert wanted.sha1 is None, wanted.name
                assert wanted.sha256 is None, wanted.name
                assert wanted.size is None, wanted.name
            else:
                assert (wanted.size is not None or filename in
                        self.data.get('unknown_sizes', ())
                        ), (self.shortname, wanted.name)

        for name, group in self.groups.items():
            for member_name in group.group_members:
                assert member_name in self.files or member_name in self.groups

    def _iter_expand_groups(self, grouped):
        """Given a set of strings that are either filenames or groups,
        yield the WantedFile instances for those names or the members of
        those groups, recursively.
        """
        for filename in grouped:
            group = self.groups.get(filename)

            if group is not None:
                for x in self._iter_expand_groups(group.group_members):
                    yield x
            else:
                yield self._ensure_file(filename)

    def construct_task(self, **kwargs):
        self.load_file_data()
        return PackagingTask(self, **kwargs)

    def construct_package(self, binary, data):
        return Package(binary, data)

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
