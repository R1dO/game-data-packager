#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2015-2016 Alexandre Detiste <alexandre@detiste.be>
# Copyright © 2016 Simon McVittie <smcv@debian.org>
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

from . import (PackagingSystem)
from ..util import (check_output, run_as_root)

logger = logging.getLogger(__name__)

class RpmPackaging(PackagingSystem):
    INSTALL_CMD = ['rpm', '-U']
    CHECK_CMD = 'rpmlint'
    ARCH_DECODE = {
                  'all': 'noarch',
                  'i386': 'i686',
                  'amd64': 'x86_64',
                  }

    def __init__(self, distro):
        super(RpmPackaging, self).__init__()
        self._contexts = (distro, 'rpm', 'generic')

    def is_installed(self, package):
        try:
            return 0 == subprocess.call(['rpm', '-q', package],
                                        stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            return False

    def current_version(self, package):
        try:
            return check_output(['rpm', '-q',
              '--qf', '%{VERSION}', package], universal_newlines=True)
        except FileNotFoundError:
            return None
        except subprocess.CalledProcessError:
            return None

    def is_available(self, package):
        # assume no apt-like system in this base class
        return self.is_installed(package)

    def available_version(self, package):
        # assume no apt-like system in this base class
        return self.current_version(package)

    def install_packages(self, rpms, method=None, gain_root='su'):
        """Install one or more packages (a list of filenames)."""

        if not method:
            method = self.INSTALL_CMD[0]

        if method == 'dnf':
            run_as_root(['dnf', 'install'] + list(rpms), gain_root)
        elif method == 'zypper':
            run_as_root(['zypper', 'install'] + list(rpms), gain_root)
        elif method == 'urpmi':
            run_as_root(['/usr/sbin/urpmi'] + list(rpms), gain_root)
        else:
            if method != 'rpm':
                logger.warning(('Unknown installation method %r,'
                                ' using rpm instead') % method)
            run_as_root(['rpm', '-U'] + list(rpms), gain_root)

    def format_relation(self, pr):
        assert not pr.contextual
        assert not pr.alternatives

        if pr.version is not None:
            op = pr.version_operator

            if op in ('<<', '>>'):
                op = op[0]

            # foo >= 1.0
            return '%s %s %s' % (self.rename_package(pr.package), op,
                    pr.version)

        return self.rename_package(pr.package)

# XXX: dnf is written in python3 and has a stable public api,
#      it is likely faster to use it instead of calling 'dnf' pgm.
#
#      I just can't make sense of it or of these "simple examples"
#
#      http://dnf.readthedocs.org/en/latest/api_base.html
#      https://github.com/timlau/dnf-apiex
#
#      As install_packages() needs root, we need to use the 'dnf' pgm

class DnfPackaging(RpmPackaging):
    LICENSEDIR = '/usr/share/licenses'
    INSTALL_CMD = ['dnf', 'install']
    PACKAGE_MAP = {
                  'dpkg-deb': 'dpkg',
                  'id-shr-extract': None,
                  '7z': 'p7zip-plugins',
                  'unrar-nonfree': 'unrar',
                  }

    def __init__(self):
        super(DnfPackaging, self).__init__('fedora')
        self.available = None

    def read_architecture(self):
        super(DnfPackaging, self).read_architecture()
        if self._architecture == 'amd64':
            self._foreign_architectures = set(['i386'])

    def is_available(self, package):
        if self.available is None:
            try:
                proc = subprocess.Popen(['dnf', 'list'],
                        universal_newlines=True,
                        stderr=subprocess.DEVNULL,
                        stdout=subprocess.PIPE)
            except FileNotFoundError:
                return False
            cache = set()
            for line in proc.stdout:
                if '.' in line:
                    cache.add(line.split('.')[0])
            self.available = cache

        return package in self.available

    def available_version(self, package):
        try:
            proc = subprocess.Popen(['dnf', 'list', package],
                                     universal_newlines=True,
                                     stderr=subprocess.DEVNULL,
                                     stdout=subprocess.PIPE)
        except FileNotFoundError:
            return None
        # keep only last line
        for line in proc.stdout:
            pass
        return line.split()[1]

    def install_packages(self, rpms, method='dnf', gain_root='su'):
        super(DnfPackaging, self).install_packages(rpms, method=method,
                gain_root=gain_root)

class ZypperPackaging(RpmPackaging):
    DOCDIR = '/usr/share/doc/packages'
    LICENSEDIR = '/usr/share/doc/packages'
    INSTALL_CMD = ['zypper', 'install']
    PACKAGE_MAP = {
                  'dpkg-deb': 'dpkg',
                  'id-shr-extract': None,
                  '7z': 'p7zip',
                  'unrar-nonfree': 'unrar',
                  }

    def __init__(self):
        super(ZypperPackaging, self).__init__('suse')

    def is_available(self, package):
        try:
            proc = subprocess.Popen(['zypper', 'info', package],
                    universal_newlines=True,
                    stdout=subprocess.PIPE,
                    env={'LANG':'C'})
        except FileNotFoundError:
            return False
        for line in proc.stdout:
            if line.startswith('Version:'):
                return True
        return False

    def available_version(self, package):
        try:
            proc = subprocess.Popen(['zypper', 'info', package],
                    universal_newlines=True,
                    stdout=subprocess.PIPE,
                    env={'LANG':'C'})
        except FileNotFoundError:
            return None
        for line in proc.stdout:
            if line.startswith('Version:'):
                return line.split(':', maxsplit=1)[1]

    def install_packages(self, rpms, method='zypper', gain_root='su'):
        super(ZypperPackaging, self).install_packages(rpms, method=method,
                gain_root=gain_root)

class UrpmiPackaging(RpmPackaging):
    BINDIR = '/usr/games'
    ASSETS = '/usr/share/games'
    INSTALL_CMD = ['urpmi']
    PACKAGE_MAP = {
                  'dpkg-deb': 'dpkg',
                  'id-shr-extract': None,
                  '7z': 'p7zip',
                  'unrar-nonfree': 'unrar',
                  }

    def __init__(self):
        super(UrpmiPackaging, self).__init__('mageia')

    def is_available(self, package):
        try:
            return 0 == subprocess.call(['urpmq', package],
                                        stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            return False

    def available_version(self, package):
        try:
            line = check_output(['urpmq', '-r', package]).decode('ascii')
            return line.split('-')[-2]
        except FileNotFoundError:
            return None
        except subprocess.CalledProcessError:
            return None

def get_distro_packaging():
    if os.path.isfile('/etc/mageia-release'):
        return UrpmiPackaging()

    if os.path.isfile('/etc/redhat-release'):
        return DnfPackaging()

    if os.path.isfile('/etc/SuSE-release'):
        return ZypperPackaging()

    try:
        maybe = DnfPackaging()

        if maybe.is_available('rpm'):
            return maybe
    except:
        pass

    try:
        maybe = ZypperPackaging()

        if maybe.is_available('rpm'):
            return maybe
    except:
        pass

    return RpmPackaging()
