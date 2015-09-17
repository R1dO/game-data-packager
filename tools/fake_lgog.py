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

# fake lgogdownloader to symlink in ~/bin

import argparse
import subprocess

parser = argparse.ArgumentParser(prog='lgogdownloader',
            description='Fake lgogdownloader.')
parser.add_argument('--download', action='store_true')
parser.add_argument('--no-extra', action='store_true')
parser.add_argument('--directory', metavar='DIR')
parser.add_argument('--subdir-game', type=str)
parser.add_argument('--platform', type=str)
parser.add_argument('--platform-priority', type=str)
parser.add_argument('--language', type=str)
parser.add_argument('--game', type=str)
args = parser.parse_args()

assert args.directory, 'Must specify --directory'
assert args.game, 'Must specifiy --game'

game = args.game.lstrip('^').rstrip('$')

archive = {
          'descent#en': 'setup_descent_2.1.0.8.exe',
          'legend_of_kyrandia#en': 'setup_legend_of_kyrandia_2.1.0.14.exe',
          'legend_of_kyrandia#de': 'setup_legend_of_kyrandia_german_2.1.0.14.exe',
          'legend_of_kyrandia#fr': 'setup_legend_of_kyrandia_french_2.1.0.14.exe',
          'loom#en': 'setup_loom_2.0.0.4.exe',
          'rise_of_the_triad__dark_war#en': 'setup_rise_of_the_triad_2.0.0.5.exe',
          }.get(game + '#' + (args.language or 'en'))

if archive is None:
    exit('Unknown game %s' % game)

locate = subprocess.check_output(['locate', archive], universal_newlines=True)
for file in locate.splitlines():
    if file.endswith(archive):
       break
else:
    exit('archive %s not found in "locate" database' % archive)

subprocess.check_call(['cp', '--reflink=auto', '-v', file, args.directory])
