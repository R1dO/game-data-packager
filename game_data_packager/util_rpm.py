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

logger = logging.getLogger('game-data-packager.util_rpm')

class PackageCache:
    available = None

    def is_installed(self, package):
        return 0 == subprocess.call(['rpm', '-q', package],
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)

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

    def current_version(self, package):
        try:
            return check_output(['rpm', '-q',
              '--qf', '%{VERSION}', package], universal_newlines=True)
        except subprocess.CalledProcessError:
            return

    def available_version(self, package):
        proc = subprocess.Popen(['dnf', 'list', package],
                                 universal_newlines=True,
                                 stderr=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE)
        # keep only last line
        for line in proc.stdout:
            pass
        return line.split()[1]

PACKAGE_CACHE = PackageCache()

def install_packages(debs, method, gain_root='su'):
    """Install one or more packages (a list of filenames)."""
    run_as_root(['dnf', 'install'] + list(debs), gain_root)
