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

print('FAKE LGOGDOWNLOADER:')

parser = argparse.ArgumentParser(prog='lgogdownloader',
            description='Fake lgogdownloader.')
parser.add_argument('--download', action='store_true')
parser.add_argument('--no-extra', action='store_true')
parser.add_argument('--directory', metavar='DIR')
parser.add_argument('--subdir-game', type=str)
parser.add_argument('--platform', type=str)
parser.add_argument('--include', type=str)
parser.add_argument('--language', type=str)
parser.add_argument('--game', type=str)
args = parser.parse_args()

assert args.directory, 'Must specify --directory'
assert args.game, 'Must specifiy --game'

game = args.game.lstrip('^').rstrip('$')

archives = {
          'descent#en': ['setup_descent_2.1.0.8.exe'],
          'legend_of_kyrandia#en': ['setup_legend_of_kyrandia_2.1.0.14.exe'],
          'legend_of_kyrandia#de': ['setup_legend_of_kyrandia_german_2.1.0.14.exe'],
          'legend_of_kyrandia#fr': ['setup_legend_of_kyrandia_french_2.1.0.14.exe'],
          'loom#en': ['setup_loom_2.0.0.4.exe'],
          'rise_of_the_triad__dark_war#en': ['setup_rise_of_the_triad_2.0.0.5.exe'],
          #'rise_of_the_triad__dark_war#en': ['gog_rise_of_the_triad_dark_war_2.0.0.8.sh'],
          'the_feeble_files#en': ['setup_the_feeble_files_2.0.0.5.exe',
                                  'setup_the_feeble_files_2.0.0.5-1.bin',
                                  'setup_the_feeble_files_2.0.0.5-2.bin'],
          'toonstruck#en': ['gog_toonstruck_2.0.0.4.sh'],
          'wolfenstein_3d#en': ['setup_wolfenstein3d_2.0.0.4.exe'],
          'wolfenstein_spear_of_destiny#en': ['setup_spear_of_destiny_2.0.0.6.exe'],
          }.get(game + '#' + (args.language or 'en'))

if archives is None:
    exit('Unknown game %s' % game)

for archive in archives:
    try:
        locate = subprocess.check_output(['locate', '-e', archive], universal_newlines=True)
    except subprocess.CalledProcessError:
        exit('Archive %s not found in "locate" database' % archive)
    for file in locate.splitlines():
        if file.endswith(archive):
           break
    else:
        exit('Archive %s not found in "locate" database' % archive)
    subprocess.check_call(['ln', '-s', '-v', file, args.directory])
