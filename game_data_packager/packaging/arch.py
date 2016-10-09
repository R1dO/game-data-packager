#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2015 Alexandre Detiste <alexandre@detiste.be>
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

import logging
import os
import subprocess

from . import (PackagingSystem)
from ..util import (run_as_root, check_output)

logger = logging.getLogger(__name__)

class ArchPackaging(PackagingSystem):
    LICENSEDIR = '$datadir/licenses'
    CHECK_CMD = 'namcap'
    INSTALL_CMD = ['pacman', '-S']
    PACKAGE_MAP = {
                  'id-shr-extract': None,
                  '7z': 'p7zip',
                  # XXX
                  }
    ARCH_DECODE = {
                  'all': 'any',
                  'amd64': 'x86_64',
                  'i386': 'i686',
                  }

    def __init__(self):
        super(ArchPackaging, self).__init__()
        self._contexts = ('arch', 'generic')

    def read_architecture(self):
        super(ArchPackaging, self).read_architecture()
        # https://wiki.archlinux.org/index.php/Multilib
        if self._architecture == 'amd64' and os.path.exists('/usr/lib32/libc.so'):
            self._foreign_architectures = set(['i386'])

    def is_installed(self, package):
        try:
            return subprocess.call(['pacman', '-Q', package],
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL) == 0
        except FileNotFoundError:
            return False

    def current_version(self, package):
        try:
            return check_output(['pacman', '-Q', package],
                                stderr=subprocess.DEVNULL,
                                universal_newlines=True).split()[1]
        except FileNotFoundError:
            return None
        except subprocess.CalledProcessError:
            return None

    def is_available(self, package):
        try:
            return subprocess.call(['pacman', '-Si', package],
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL) == 0
        except FileNotFoundError:
            return False

    def available_version(self, package):
        try:
            remote_info = check_output(['pacman', '-Si', package],
                                       universal_newlines=True,
                                       env={'LANG':'C'})
            for line in remote_info.splitlines():
                k, _, v = line.split(maxsplit=2)
                if k == 'Version':
                    return v

        except FileNotFoundError:
            return None
        except subprocess.CalledProcessError:
            return None

    def install_packages(self, pkgs, method=None, gain_root='su'):
        run_as_root(['pacman', '-U'] + list(pkgs), gain_root)

    def format_relation(self, pr):
        assert not pr.contextual
        assert not pr.alternatives

        if pr.version is not None:
            op = pr.version_operator

            if op in ('<<', '>>'):
                op = op[0]

            # foo>=1.0
            return '%s%s%s' % (self.rename_package(pr.package), op, pr.version)

        return self.rename_package(pr.package)

    def fill_dest_dir_arch(self, game, package, destdir, compress, arch):
        PKGINFO = os.path.join(destdir, '.PKGINFO')
        short_desc, _ = self.generate_description(game, package)
        size = check_output(['du','-bs','.'], cwd=destdir)
        size = int(size.split()[0])
        with open(PKGINFO, 'w',  encoding='utf-8') as pkginfo:
            pkginfo.write('pkgname = %s\n' % package.name)
            pkginfo.write('pkgver = %s-1\n' % package.version)
            pkginfo.write('pkgdesc = %s\n' % short_desc)
            pkginfo.write('url = https://wiki.debian.org/Games/GameDataPackager\n')
            pkginfo.write('builddate = %i\n' % int(time.time()))
            pkginfo.write('packager = Alexandre Detiste <alexandre@detiste.be>\n')
            pkginfo.write('size = %i\n' % size)
            pkginfo.write('arch = %s\n' % arch)
            if os.path.isdir(os.path.join(destdir, 'usr/share/licenses')):
                pkginfo.write('license = custom\n')
            pkginfo.write('group = games\n')
            if package.expansion_for:
                pkginfo.write('depend = %s\n' % package.expansion_for)
            else:
                engine = self.substitute(
                        package.engine or game.engine,
                        package.name)

                if engine and len(engine.split()) == 1:
                    pkginfo.write('depend = %s\n' % engine)

        files = set()
        for dirpath, dirnames, filenames in os.walk(destdir):
                for fn in filenames:
                    full = os.path.join(dirpath, fn)
                    full = full[len(destdir)+1:]
                    files.add(full)

        MTREE = os.path.join(destdir, '.MTREE')
        subprocess.check_call(['fakeroot', 'bsdtar', '-czf', MTREE, '--format=mtree',
                 '--options=!all,use-set,type,uid,gid,mode,time,size,md5,sha256,link']
                 + sorted(files), env={'LANG':'C'}, cwd=destdir)

def get_packaging_system(distro=None):
    return ArchPackaging()
