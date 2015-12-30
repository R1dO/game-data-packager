#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2015 Simon McVittie <smcv@debian.org>
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

import tarfile
import zipfile

from . import (TarUnpacker, ZipUnpacker)

def get_makeself_offset(archive, reader=None):
    """Sniff Makeself archives, returning the offset to the embedded
    tar file, or 0 if not a makeself archive.

    http://megastep.org/makeself/
    """
    skip = 0
    line_number = 0
    has_makeself = False
    trailer = None

    SHEBANG = bytes('/bin/sh', 'ascii')
    HEADER_V1 = bytes('# This script was generated using Makeself 1.', 'ascii')
    HEADER_V2 = bytes('# This script was generated using Makeself 2.', 'ascii')
    TRAILER_V1 = bytes('END_OF_STUB', 'ascii')
    TRAILER_V2 = bytes('eval $finish; exit $res', 'ascii')

    if reader is None:
        reader = open(archive, 'rb')

    for line in reader:
        line_number += 1
        skip += len(line)

        if line_number == 1 and SHEBANG not in line:
            return 0
        elif has_makeself:
            if trailer in line:
                return skip
        elif HEADER_V1 in line:
            has_makeself = True
            trailer = TRAILER_V1
        elif HEADER_V2 in line:
            has_makeself = True
            trailer = TRAILER_V2
        elif line_number > 3:
            return 0

    return 0

def automatic_unpacker(archive, reader=None):
    if reader is None:
        is_plain_file = True
        reader = open(archive, 'rb')
    else:
        is_plain_file = False

    if reader.seekable():
        skip = get_makeself_offset(archive, reader)

        if skip > 0:
            reader.seek(0)
            return TarUnpacker(archive, reader=reader, skip=skip,
                    compression='gz')

        if zipfile.is_zipfile(reader):
            return ZipUnpacker(reader)

        if archive.endswith(('.umod', '.exe')):
            from .umod import (Umod, is_umod)
            if is_umod(reader):
                return Umod(reader)

    if is_plain_file and tarfile.is_tarfile(archive):
        return TarUnpacker(archive)

    return None
