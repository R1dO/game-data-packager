#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2014-2015 Simon McVittie <smcv@debian.org>
#           © 2015 Alexandre Detiste <alexandre@detiste.be>
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

from .util import (run_as_root, check_output)
from debian.debian_support import Version

logger = logging.getLogger('game-data-packager.util_deb')

class PackageCache:
    installed = None
    available = None

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

        if self.installed is None:
            cache = set()
            proc = subprocess.Popen(['dpkg-query', '--show',
                        '--showformat', '${Package}\\n'],
                    universal_newlines=True,
                    stdout=subprocess.PIPE)
            for line in proc.stdout:
                cache.add(line.rstrip())
            self.installed = cache

        return package in self.installed

    def is_available(self, package):
        if self.available is None:
            cache = set()
            proc = subprocess.Popen(['apt-cache', 'pkgnames'],
                    universal_newlines=True,
                    stdout=subprocess.PIPE)
            for line in proc.stdout:
                cache.add(line.rstrip())
            self.available = cache

        return package in self.available

    def current_version(self, package):
        # 'dpkg-query: no packages found matching $package'
        # will leak on stderr if called with an unknown package,
        # but that should never happen
        try:
            return check_output(['dpkg-query', '--show',
              '--showformat', '${Version}', package], universal_newlines=True)
        except subprocess.CalledProcessError:
            return

    def available_version(self, package):
        current_ver = check_output(['apt-cache', 'madison', package],
                                    universal_newlines=True)
        current_ver = current_ver.splitlines()[0]
        current_ver = current_ver.split('|')[1].strip()
        return current_ver

PACKAGE_CACHE = PackageCache()

def install_packages(debs, method, gain_root='su'):
    """Install one or more packages (a list of filenames)."""

    if method and method not in (
            'apt', 'dpkg',
            'gdebi', 'gdebi-gtk', 'gdebi-kde',
            ):
        logger.warning(('Unknown installation method %r, using apt or dpkg ' +
            'instead') % method)
        method = None

    if not method:
        apt_ver = PACKAGE_CACHE.current_version('apt')
        if Version(apt_ver.strip()) >= Version('1.1~0'):
            method = 'apt'
        else:
            method = 'dpkg'

    if method == 'apt':
        run_as_root(['apt-get', 'install', '--install-recommends'] + list(debs),
                gain_root)
    elif method == 'dpkg':
        run_as_root(['dpkg', '-i'] + list(debs), gain_root)
    elif method == 'gdebi':
        run_as_root(['gdebi'] + list(debs), gain_root)
    else:
        # gdebi-gtk etc.
        subprocess.call([method] + list(debs))
