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
import subprocess


try:
    from debian.debian_support import Version
except ImportError:
    # make check
    from distutils.version import LooseVersion as Version

from . import (PackagingSystem)
from ..util import (check_output, mkdir_p, run_as_root)

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

def get_packaging_system(distro=None):
    return DebPackaging()
