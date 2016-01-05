# encoding=utf-8

# This version of this file is only used when run uninstalled. It is replaced
# with a generated version during installation.

import os

with open('debian/changelog', encoding='utf-8') as cl:
    try:
        from debian.changelog import ChangeLog
    except ImportError:
        GAME_PACKAGE_VERSION = cl.readline().split('(', 1)[1].split(')', 1)[0]
    else:
        cl = ChangeLog(cl, strict=False)
        GAME_PACKAGE_VERSION = str(cl.full_version)

if os.path.isfile('/etc/debian_version'):
    FORMAT = 'deb'
    DISTRO = 'generic'

elif os.path.isfile('/etc/redhat-release'):
    FORMAT = 'rpm'
    DISTRO = 'fedora'

elif os.path.isfile('/etc/SuSE-release'):
    FORMAT = 'rpm'
    DISTRO = 'suse'

elif os.path.isfile('/etc/arch-release'):
    FORMAT = 'arch'
    DISTRO = 'arch'
