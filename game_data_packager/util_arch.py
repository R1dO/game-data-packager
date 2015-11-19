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

from .util import (run_as_root, check_output)

logger = logging.getLogger('game-data-packager.util_arch')

class PackageCache:
    def is_installed(self, package):
        return subprocess.call(['pacman', '-Q', package],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL) == 0

    def is_available(self, package):
        return subprocess.call(['pacman', '-Si', package],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL) == 0

    def current_version(self, package):
        try:
            return check_output(['pacman', '-Q', package],
                                stderr=subprocess.DEVNULL,
                                universal_newlines=True).split()[1]
        except subprocess.CalledProcessError:
            return

    def available_version(self, package):
        try:
            remote_info = check_output(['pacman', '-Si', package],
                                       universal_newlines=True,
                                       env={'LANG':'C'})
            for line in remote_info.splitlines():
                k, _, v = line.split(maxsplit=2)
                if k == 'Version':
                    return v
                
        except subprocess.CalledProcessError:
            return

PACKAGE_CACHE = PackageCache()

def install_packages(pkgs, method, gain_root='su'):
    """Install one or more packages (a list of filenames)."""
    run_as_root(['pacman', '-U'] + list(pkgs), gain_root)
