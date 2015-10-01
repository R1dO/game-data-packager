#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2014-2015 Simon McVittie <smcv@debian.org>
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

from enum import Enum
import logging

logging.basicConfig()
logger = logging.getLogger('game-data-packager.build')

class FillResult(Enum):
    UNDETERMINED = 0
    IMPOSSIBLE = 1
    DOWNLOAD_NEEDED = 2
    COMPLETE = 3
    UPGRADE_NEEDED = 4

    def __and__(self, other):
        if other is FillResult.UNDETERMINED:
            return self

        if self is FillResult.UNDETERMINED:
            return other

        if other is FillResult.IMPOSSIBLE or self is FillResult.IMPOSSIBLE:
            return FillResult.IMPOSSIBLE

        if other is FillResult.UPGRADE_NEEDED or self is FillResult.UPGRADE_NEEDED:
            return FillResult.UPGRADE_NEEDED

        if other is FillResult.DOWNLOAD_NEEDED or self is FillResult.DOWNLOAD_NEEDED:
            return FillResult.DOWNLOAD_NEEDED

        return FillResult.COMPLETE

    def __or__(self, other):
        if other is FillResult.UNDETERMINED:
            return self

        if self is FillResult.UNDETERMINED:
            return other

        if other is FillResult.COMPLETE or self is FillResult.COMPLETE:
            return FillResult.COMPLETE

        if other is FillResult.DOWNLOAD_NEEDED or self is FillResult.DOWNLOAD_NEEDED:
            return FillResult.DOWNLOAD_NEEDED

        if other is FillResult.UPGRADE_NEEDED or self is FillResult.UPGRADE_NEEDED:
            return FillResult.UPGRADE_NEEDED

        return FillResult.IMPOSSIBLE

class NoPackagesPossible(Exception):
    pass

class DownloadsFailed(Exception):
    pass

class DownloadNotAllowed(Exception):
    pass

class CDRipFailed(Exception):
    pass
