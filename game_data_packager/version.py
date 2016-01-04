# encoding=utf-8

# This version of this file is only used when run uninstalled. It is replaced
# with a generated version during installation.

import os

if os.path.isfile('/etc/debian_version'):
    FORMAT = 'deb'
    DISTRO = 'generic'
    BINDIR = 'usr/games'
    ASSETS = 'usr/share/games'
    LICENSEDIR = 'usr/share/doc'

    from debian.changelog import Changelog
    cl = Changelog(open('debian/changelog', encoding='utf-8'), strict=False)
    GAME_PACKAGE_VERSION = str(cl.full_version)

elif os.path.isfile('/etc/redhat-release'):
    FORMAT = 'rpm'
    DISTRO = 'fedora'
    BINDIR = 'usr/bin'
    ASSETS = 'usr/share'
    LICENSEDIR = 'usr/share/licenses'

    cl = open('debian/changelog', encoding='utf-8').readline()
    GAME_PACKAGE_VERSION = cl.split('(')[1].split(')')[0]

elif os.path.isfile('/etc/SuSE-release'):
    FORMAT = 'rpm'
    DISTRO = 'suse'
    BINDIR = 'usr/bin'
    ASSETS = 'usr/share'
    LICENSEDIR = 'usr/share/licenses'

    cl = open('debian/changelog', encoding='utf-8').readline()
    GAME_PACKAGE_VERSION = cl.split('(')[1].split(')')[0]

elif os.path.isfile('/etc/arch-release'):
    FORMAT = 'arch'
    DISTRO = 'arch'
    BINDIR = 'usr/bin'
    ASSETS = 'usr/share'
    LICENSEDIR = 'usr/share/doc'

    cl = open('debian/changelog', encoding='utf-8').readline()
    GAME_PACKAGE_VERSION = cl.split('(')[1].split(')')[0]
