# encoding=utf-8

# This version of this file is only used when run uninstalled. It is replaced
# with a generated version during installation.

from debian.changelog import Changelog

cl = Changelog(open('debian/changelog', encoding='utf-8'), strict=False)
GAME_PACKAGE_VERSION = str(cl.full_version)
