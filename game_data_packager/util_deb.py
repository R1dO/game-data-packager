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

from .util import (mkdir_p)

logger = logging.getLogger('game-data-packager.util_deb')

def lintian_license(destdir, package, file):
    assert type(package) is str
    lintiandir = os.path.join(destdir, 'usr/share/lintian/overrides')
    mkdir_p(lintiandir)
    with open(os.path.join(lintiandir, package), 'a', encoding='utf-8') as l:
        l.write('%s: extra-license-file usr/share/doc/%s/%s\n'
                % (package, package, file))

def lintian_desktop(destdir, package, program):
    assert type(package) is str
    lintiandir = os.path.join(destdir, 'usr/share/lintian/overrides')
    mkdir_p(lintiandir)
    with open(os.path.join(lintiandir, package), 'a', encoding='utf-8') as l:
        l.write('%s: desktop-command-not-in-package '
                'usr/share/applications/%s.desktop %s\n'
                 % (package, package, program))
