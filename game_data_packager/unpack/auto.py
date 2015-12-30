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

import tarfile
import zipfile

from . import (TarUnpacker, ZipUnpacker)

def automatic_unpacker(archive, reader=None):
    if reader is None:
        is_plain_file = True
        reader = open(archive, 'rb')
    else:
        is_plain_file = False

    if reader.seekable():
        if zipfile.is_zipfile(reader):
            return ZipUnpacker(reader)

        if archive.endswith(('.umod', '.exe')):
            from .umod import (Umod, is_umod)
            if is_umod(reader):
                return Umod(reader)

    if is_plain_file and tarfile.is_tarfile(archive):
        return TarUnpacker(archive)

    return None
