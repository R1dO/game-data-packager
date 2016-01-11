#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2016 Alexandre Detiste <alexandre@detiste.be>
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
# /usr/share/common-licenses/GPL-2

# this goes in "/usr/games/dosgame"

import configparser
import os
import sys
import subprocess

game = os.path.basename(sys.argv[0])

srcroot = '/usr/share/games/dosbox/'
srcdir  = os.path.join(srcroot, game)
inf = os.path.join(srcdir, 'dosgame.inf')

if game == 'dosgame':
    print('Supported games:')
    print('\n'.join(os.listdir(srcroot)))
    exit(0)

config = configparser.ConfigParser()
config.read(inf, encoding='utf-8')
for section in config.sections():
    # this .inf file could also include
    # other sections that would be
    # copied as-is into dosbox.cfg
    assert(section == "Dos Game")
    dir = config[section]['Dir']
    exe = config[section]['Exe']

destroot = os.path.expanduser('~/.dosbox')
destdir = os.path.join(destroot, dir)
autoexec = os.path.join(destdir, 'dosbox.cfg')

# XXX: currenlty only work with games that
#      have all assets in a single directory
#
#      some games needs to be able to write in subdirs
#      and will need extensive linkfarms,
#      while other are ok with symlinked subdirs
if not os.path.isdir(destdir):
    os.makedirs(destdir)
    for dirpath, dirnames, filenames in os.walk(srcdir):
        for fn in filenames:
            if fn == 'dosgame.inf':
                continue
            full = os.path.join(dirpath, fn)
            os.symlink(full, os.path.join(destdir, fn))

if not os.path.isfile(autoexec):
    with open(autoexec, 'w', encoding='ascii') as of:
        of.write('[Autoexec]\n')
        of.write('@ECHO OFF\n')
        of.write('MOUNT C %s\n' % destroot)
        of.write('C:\n')
        of.write('CD %s\n' % dir)
        of.write('%s\n' % exe)
        of.write('EXIT\n')

subprocess.call(['dosbox', '-conf', autoexec])
