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
#
# You can find the GPL license text on a Debian system under
# /usr/share/common-licenses/GPL-2.

import os
import subprocess
import time

today = time.strftime('%Y%m%d')

BASE = '/home/tchet/git'
GDP = os.path.join(BASE, 'game-data-packager')

subprocess.check_call(['git', 'checkout', 'debian/changelog'],
                       cwd = GDP)

with open('/usr/share/distro-info/ubuntu.csv', 'r') as data:
    for line in data.readlines():
       version, _, release, _, date, _ = line.split(',', 5)
       if version == 'version':
          continue
       if time.strptime(date, '%Y-%m-%d') > time.localtime():
          continue
       current = release
       if 'LTS' in version:
          lts = release
version = subprocess.check_output(['dpkg-parsechangelog',
                                  '-l', os.path.join(GDP, 'debian/changelog'),
                                  '-S', 'Version'],
                                  universal_newlines = True).strip()
releases = sorted(set([lts, current]))

for release in releases:
    snapshot = version + '~git' + today + '+' + release
    subprocess.check_call(['dch', '-b',
                           '-D', release,
                           '-v', snapshot,
                           "Git snapshot"],
                          cwd = GDP)
    subprocess.check_call(['debuild', '-S', '-i'],cwd = GDP)
    subprocess.check_call(['dput', 'my-ppa',
                           'game-data-packager_%s_source.changes' % snapshot],
                           cwd = BASE)
    subprocess.check_call(['git', 'checkout', 'debian/changelog'],
                          cwd = GDP)
    for file in ('.tar.xz',
                 '.dsc',
                 '_source.build',
                 '_source.changes',
                 '_source.my-ppa.upload'):
        subprocess.check_call(['rm', '-v',
                               'game-data-packager_%s%s' % (snapshot, file)],
                              cwd = BASE)
