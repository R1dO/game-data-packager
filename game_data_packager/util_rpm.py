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

from .util import (check_output)

logger = logging.getLogger('game-data-packager.util_rpm')

class RPM_PackageCache:
    def is_installed(self, package):
        return 0 == subprocess.call(['rpm', '-q', package],
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)

    def current_version(self, package):
        try:
            return check_output(['rpm', '-q',
              '--qf', '%{VERSION}', package], universal_newlines=True)
        except subprocess.CalledProcessError:
            return
