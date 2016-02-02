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

# a small tool to create or verify a mirror
# of downloadable files needed by GDP

# call it this way:
#   GDP_UNINSTALLED=1 python3 -m tools.mirror

# this tool will never remove any bad file,
# you'll have to investigate by yourself

KEEP_FREE_SPACE = 250 * 1024 * 1024

import argparse
import os
import subprocess

from game_data_packager import (load_games)
from game_data_packager.build import (choose_mirror)
from game_data_packager.command_line import (TerminalProgress)
from game_data_packager.data import (HashedFile)

archives = []

os.environ.pop('GDP_MIRROR', None)

parser = argparse.ArgumentParser()
parser.add_argument('--destination', default='/var/www/html')
args = parser.parse_args()

print('loading game definitions...')

for gamename, game in load_games().items():
    game.load_file_data()
    for filename, file in game.files.items():
        if file.unsuitable:
            # quake2-rogue-2.00.tar.xz could have been tagged this way
            archive = os.path.join(args.destination, filename)
            if os.path.isfile(archive):
                print('Obsolete archive: %s (%s)' % (archive, file.unsuitable))
        elif filename == 'tnt31fix.zip?repack':
            continue
        elif file.download:
            url = choose_mirror(file)[0]
            if '?' not in url:
                destname = os.path.basename(url)
            elif '?' not in filename:
                destname = filename
            elif url.endswith('?download'):
                destname = os.path.basename(url)
                destname = destname[0:len(destname)-len('?download')]
            else:
                exit("Can't compute filename for %s = %s" % (filename, url))
            archives.append({
             'name': destname,
             'size': file.size,
             'md5': file.md5,
             'sha1': file.sha1,
             'download': url,
             })

archives = sorted(archives, key=lambda k: (k['size']))

for a in archives:
   archive = os.path.join(args.destination, a['name'])

   if not os.path.isfile(archive):
       statvfs = os.statvfs(args.destination)
       freespace = statvfs.f_frsize * statvfs.f_bavail
       if a['size'] > freespace - KEEP_FREE_SPACE:
           print('out of space, can not download %s' % a['name'])
           continue
       subprocess.check_call(['wget', a['download'],
                              '-O', a['name']],
                              cwd=args.destination)

   if os.path.getsize(archive) == 0:
       exit("%s is empty !!!" % archive)
   if os.path.getsize(archive) != a['size']:
       exit("%s has the wrong size !!!" % archive)
   print('checking %s ...' % archive)
   hf = HashedFile.from_file(archive, open(archive, 'rb'),
        size=a['size'], progress=TerminalProgress())
   if a['md5'] and a['md5'] != hf.md5:
       exit("md5 doesn't match for %s !!!" % archive)
   if a['sha1'] and a['sha1'] != hf.sha1:
       exit("sha1 doesn't match for %s !!!" % archive)
