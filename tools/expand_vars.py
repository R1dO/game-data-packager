#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2016 Simon McVittie <smcv@debian.org>
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
import sys

from game_data_packager.packaging import (get_native_packaging_system)

def main(f, out):
    data = open(f, encoding='utf-8').read()
    data = get_native_packaging_system().substitute(data,
            'unknown-package-name')
    open(out + '.tmp', 'w', encoding='utf-8').write(data)
    os.rename(out + '.tmp', out)

if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])

