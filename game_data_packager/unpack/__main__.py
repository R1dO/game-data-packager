#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2015 Simon McVittie <smcv@debian.org>
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

import argparse
import tarfile
import zipfile

from . import (TarUnpacker, ZipUnpacker)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', '-o', help='extract to OUTPUT',
            default=None)
    parser.add_argument('archive')
    args = parser.parse_args()

    if zipfile.is_zipfile(args.archive):
        unpacker = ZipUnpacker(args.archive)
    elif tarfile.is_tarfile(args.archive):
        unpacker = TarUnpacker(args.archive)
    else:
        raise SystemExit('Cannot work out how to unpack %r' % args.archive)

    if args.output:
        unpacker.extractall(args.output)
    else:
        unpacker.printdir()
