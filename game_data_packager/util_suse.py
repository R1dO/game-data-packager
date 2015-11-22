#!/usr/bin/python3
# encoding=utf-8
#
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

import logging
import subprocess

from .util import (run_as_root)
from .util_rpm import (RPM_PackageCache)

logger = logging.getLogger('game-data-packager.util_suse')

class PackageCache(RPM_PackageCache):
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

PACKAGE_CACHE = PackageCache()

def install_packages(rpms, method, gain_root='su'):
    """Install one or more packages (a list of filenames)."""
    run_as_root(['zypper', 'install'] + list(rpms), gain_root)
