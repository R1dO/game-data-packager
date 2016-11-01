#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2014-2016 Simon McVittie <smcv@debian.org>
#           © 2015-2016 Alexandre Detiste <alexandre@detiste.be>
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

import logging
import os
import stat
import subprocess


try:
    from debian.deb822 import Deb822
    from debian.debian_support import Version
except ImportError:
    # make check
    from distutils.version import LooseVersion as Version
    Deb822 = None

from . import (PackagingSystem)
from ..data import (HashedFile)
from ..paths import (DATADIR)
from ..util import (
        check_output,
        mkdir_p,
        normalize_permissions,
        rm_rf,
        run_as_root)

logger = logging.getLogger(__name__)

class DebPackaging(PackagingSystem):
    BINDIR = '$prefix/games'
    ASSETS = '$datadir/games'
    CHECK_CMD = 'lintian'
    INSTALL_CMD = ['apt-get', 'install']
    PACKAGE_MAP = {
                  'id-shr-extract': 'dynamite',
                  'lha': 'lhasa',
                  '7z': 'p7zip-full',
                  'unrar-nonfree': 'unrar',
                  'zoom': 'zoom-player',
                  'doom': 'doom-engine',
                  'boom': 'boom-engine',
                  'heretic': 'heretic-engine',
                  'hexen': 'hexen-engine',
                  'doomsday-compat': 'doomsday',
                  }
    RENAME_PACKAGES = {
            'libSDL-1.2.so.0': 'libsdl1.2debian',
            'libgcc_s.so.1': 'libgcc1',
            'libjpeg.so.62': 'libjpeg62-turbo | libjpeg62',
    }

    def __init__(self):
        super(DebPackaging, self).__init__()
        self.__installed = None
        self.__available = None
        self._contexts = ('deb', 'generic')

    def read_architecture(self):
        self._architecture = check_output(['dpkg',
                '--print-architecture']).strip().decode('ascii')
        self._foreign_architectures = set(check_output(['dpkg',
                '--print-foreign-architectures']
                    ).strip().decode('ascii').split())

    def is_installed(self, package):
        # FIXME: this shouldn't be hard-coded
        if package == 'doom-engine':
            return (self.is_installed('chocolate-doom')
                 or self.is_installed('prboom-plus')
                 or self.is_installed('doomsday'))
        if package == 'boom-engine':
            return (self.is_installed('prboom-plus')
                 or self.is_installed('doomsday'))
        if package == 'heretic-engine':
            return (self.is_installed('chocolate-heretic')
                 or self.is_installed('doomsday'))
        if package == 'hexen-engine':
            return (self.is_installed('chocolate-hexen')
                 or self.is_installed('doomsday'))

        if os.path.isdir(os.path.join('/usr/share/doc', package)):
            return True

        if self.__installed is None:
            try:
                proc = subprocess.Popen(['dpkg-query', '--show',
                            '--showformat', '${Package}\\n'],
                        universal_newlines=True,
                        stdout=subprocess.PIPE)
            except FileNotFoundError:
                return False

            cache = set()
            for line in proc.stdout:
                cache.add(line.rstrip())
            self.__installed = cache

        return package in self.__installed

    def is_available(self, package):
        if self.__available is None:
            try:
                proc = subprocess.Popen(['apt-cache', 'pkgnames'],
                        universal_newlines=True,
                        stdout=subprocess.PIPE)
            except FileNotFoundError:
                return False

            cache = set()
            for line in proc.stdout:
                cache.add(line.rstrip())
            self.__available = cache

        return package in self.__available

    def current_version(self, package):
        # 'dpkg-query: no packages found matching $package'
        # will leak on stderr if called with an unknown package,
        # but that should never happen
        try:
            return check_output(['dpkg-query', '--show',
              '--showformat', '${Version}', package], universal_newlines=True)
        except FileNotFoundError:
            return None
        except subprocess.CalledProcessError:
            return None

    def available_version(self, package):
        try:
            current_ver = check_output(['apt-cache', 'madison', package],
                                        universal_newlines=True)
        except FileNotFoundError:
            return None
        current_ver = current_ver.splitlines()[0]
        current_ver = current_ver.split('|')[1].strip()
        return current_ver

    def install_packages(self, debs, method=None, gain_root='su'):
        if method and method not in (
                'apt', 'dpkg',
                'gdebi', 'gdebi-gtk', 'gdebi-kde',
                ):
            logger.warning(('Unknown installation method %r, using apt or ' +
                'dpkg instead') % method)
            method = None

        if not method:
            apt_ver = self.current_version('apt')
            if Version(apt_ver.strip()) >= Version('1.1~0'):
                method = 'apt'
            else:
                method = 'dpkg'

        if method == 'apt':
            run_as_root(['apt-get', 'install', '--install-recommends'] +
                    list(debs), gain_root)
        elif method == 'dpkg':
            run_as_root(['dpkg', '-i'] + list(debs), gain_root)
        elif method == 'gdebi':
            run_as_root(['gdebi'] + list(debs), gain_root)
        else:
            # gdebi-gtk etc.
            subprocess.call([method] + list(debs))

    def rename_package(self, p):
        mapped = super(DebPackaging, self).rename_package(p)

        if mapped != p:
            return mapped

        p = p.lower().replace('_', '-')

        if '.so.' in p:
            lib, version = p.split('.so.', 1)

            if lib[-1] in '012345679':
                lib += '-'

            return lib + version

        return p

    def override_lintian(self, destdir, package, tag, args):
        assert type(package) is str
        lintiandir = os.path.join(destdir, 'usr/share/lintian/overrides')
        mkdir_p(lintiandir)
        with open(os.path.join(lintiandir, package), 'a', encoding='utf-8') as l:
            l.write('%s: %s %s\n' % (package, tag, args))

    def format_relation(self, pr):
        assert not pr.contextual

        if pr.alternatives:
            return ' | '.join([self.format_relation(p)
                for p in pr.alternatives])

        if pr.version is not None:
            # foo (>= 1.0)
            return '%s (%s %s)' % (self.rename_package(pr.package),
                    pr.version_operator, pr.version)

        return self.rename_package(pr.package)

    def __generate_control(self, game, package, destdir):
        if Deb822 is None:
            raise FileNotFoundError('Cannot generate .deb packages without '
                    'python3-debian')

        try:
            control_in = open(os.path.join(DATADIR,
                              package.name + '.control.in'), encoding='utf-8')
            control = Deb822(control_in)
            for key in control.keys():
                assert key == 'Description', 'specify "%s" only in YAML' % key
        except FileNotFoundError:
            control = Deb822()

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
            control['Architecture'] = self.get_architecture(
                    package.architecture)

        dep = dict()

        for rel in package.relations:
            if rel == 'build_depends':
                continue

            dep[rel] = self.merge_relations(package, rel)
            logger.debug('%s %s %s', package.name, rel, ', '.join(dep[rel]))

        if package.mutually_exclusive:
            dep['conflicts'] |= package.demo_for
            dep['conflicts'] |= package.better_versions

        if package.mutually_exclusive:
            dep['replaces'] |= dep['provides']

        engine = self.substitute(
                package.engine or game.engine,
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
        elif not package.expansion_for and game.engine:
            dep['recommends'].add(engine)

        if package.expansion_for:
            # check if default heuristic has been overriden in yaml
            for p in dep['depends']:
                if package.expansion_for == p.split()[0]:
                    break
            else:
                dep['depends'].add(package.expansion_for)

        # dependencies derived from *other* package's data
        for other_package in game.packages.values():
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
            short_desc, long_desc = self.generate_description(game, package)
            control['Description'] = short_desc + '\n ' + long_desc.replace('\n', '\n ')

        return control

    def __fill_dest_dir_deb(self, game, package, destdir, md5sums=None):
        if package.component == 'local':
             self.override_lintian(destdir, package.name,
                     'unknown-section', 'local/%s' % package.section)

        # same output as in dh_md5sums
        if md5sums is None:
            md5sums = {}

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
                if file not in md5sums:
                    with open(full, 'rb') as opened:
                        hf = HashedFile.from_file(full, opened)
                        md5sums[file] = hf.md5

        debdir = os.path.join(destdir, 'DEBIAN')
        mkdir_p(debdir)
        md5sums_path = os.path.join(destdir, 'DEBIAN/md5sums')
        with open(md5sums_path, 'w', encoding='utf8') as outfile:
            for file in sorted(md5sums.keys()):
                outfile.write('%s  %s\n' % (md5sums[file], file))
        os.chmod(md5sums_path, 0o644)

        control = os.path.join(destdir, 'DEBIAN/control')
        self.__generate_control(game, package, destdir).dump(
                fd=open(control, 'wb'), encoding='utf-8')
        os.chmod(control, 0o644)

    def build_package(self, per_package_dir, game, package, destination,
            compress=True, md5sums=None):
        destdir = os.path.join(per_package_dir, 'DESTDIR')
        arch = self.get_effective_architecture(package)
        self.__fill_dest_dir_deb(game, package, destdir, md5sums)
        normalize_permissions(destdir)

        # it had better have a /usr and a DEBIAN directory or
        # something has gone very wrong
        assert os.path.isdir(os.path.join(destdir, 'usr')), destdir
        assert os.path.isdir(os.path.join(destdir, 'DEBIAN')), destdir

        deb_basename = '%s_%s_%s.deb' % (package.name, package.version, arch)

        outfile = os.path.join(os.path.abspath(destination), deb_basename)

        # only compress if the caller says we should, the YAML
        # says it's worthwhile, and this isn't a ripped CD (Vorbis
        # is already compressed)
        if not compress or not game.compress_deb or package.rip_cd:
            dpkg_deb_args = ['-Znone']
        elif game.compress_deb is True:
            dpkg_deb_args = []
        elif isinstance(game.compress_deb, str):
            dpkg_deb_args = ['-Z' + game.compress_deb]
        elif isinstance(game.compress_deb, list):
            dpkg_deb_args = game.compress_deb

        try:
            logger.info('generating package %s', package.name)
            check_output(['fakeroot', 'dpkg-deb'] +
                    dpkg_deb_args +
                    ['-b', 'DESTDIR', outfile],
                    cwd=per_package_dir)
        except subprocess.CalledProcessError as cpe:
            print(cpe.output)
            raise

        rm_rf(destdir)
        return outfile

def get_packaging_system(distro=None):
    return DebPackaging()
