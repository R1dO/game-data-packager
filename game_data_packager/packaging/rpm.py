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
    LICENSEDIR = 'usr/share/licenses'

    def is_installed(self, package):
        return 0 == subprocess.call(['rpm', '-q', package],
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)

    def current_version(self, package):
        try:
            return check_output(['rpm', '-q',
              '--qf', '%{VERSION}', package], universal_newlines=True)
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

        if method is None:
            method = 'rpm'

        if method == 'dnf':
            run_as_root(['dnf', 'install'] + list(rpms), gain_root)
        elif method == 'zypper':
            run_as_root(['zypper', 'install'] + list(rpms), gain_root)
        elif method == 'rpm':
            run_as_root(['rpm', '-U'] + list(rpms), gain_root)

class DnfPackaging(RpmPackaging):
    def __init__(self):
        self.available = None

    def read_architecture(self):
        super(DnfPackaging, self).read_architecture()
        if self._architecture == 'amd64':
            self._foreign_architectures = set(['i386'])

    def is_available(self, package):
        if self.available is None:
            cache = set()
            proc = subprocess.Popen(['dnf', 'list'],
                    universal_newlines=True,
                    stdout=subprocess.PIPE)
            for line in proc.stdout:
                if '.' in line:
                    cache.add(line.split('.')[0])
            self.available = cache

        return package in self.available

    def available_version(self, package):
        proc = subprocess.Popen(['dnf', 'list', package],
                                 universal_newlines=True,
                                 stderr=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE)
        # keep only last line
        for line in proc.stdout:
            pass
        return line.split()[1]

    def install_packages(self, rpms, method='dnf', gain_root='su'):
        super(DnfPackaging, self).install_packages(rpms, method=method,
                gain_root=gain_root)

class ZypperPackaging(RpmPackaging):
    def is_available(self, package):
        proc = subprocess.Popen(['zypper', 'info', package],
                universal_newlines=True,
                stdout=subprocess.PIPE,
                env={'LANG':'C'})
        for line in proc.stdout:
            if ':' not in line:
                continue
            k, _, v = line.split(maxsplit=2)
            if k == 'Version':
                return True
        return False

    def available_version(self, package):
        proc = subprocess.Popen(['zypper', 'info', package],
                universal_newlines=True,
                stdout=subprocess.PIPE,
                env={'LANG':'C'})
        for line in proc.stdout:
            if ':' not in line:
                continue
            k, _, v = line.split(maxsplit=2)
            if k == 'Version':
                return v

    def install_packages(self, rpms, method='zypper', gain_root='su'):
        super(ZypperPackaging, self).install_packages(rpms, method=method,
                gain_root=gain_root)

def get_distro_packaging():
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
