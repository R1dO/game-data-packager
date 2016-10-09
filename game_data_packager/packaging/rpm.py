#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2015-2016 Alexandre Detiste <alexandre@detiste.be>
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
import time
from distutils.version import LooseVersion as Version

from . import (PackagingSystem)
from ..util import (
        check_output,
        normalize_permissions,
        run_as_root,
        )

logger = logging.getLogger(__name__)

class RpmPackaging(PackagingSystem):
    INSTALL_CMD = ['rpm', '-U']
    CHECK_CMD = 'rpmlint'
    ARCH_DECODE = {
                  'all': 'noarch',
                  'i386': 'i686',
                  'amd64': 'x86_64',
                  }

    def __init__(self, distro=None):
        super(RpmPackaging, self).__init__()
        self.distro = distro
        if distro is None or distro == 'generic':
            self._contexts = ('rpm', 'generic')
        else:
            self._contexts = (distro, 'rpm', 'generic')

    def is_installed(self, package):
        try:
            return 0 == subprocess.call(['rpm', '-q', package],
                                        stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            return False

    def current_version(self, package):
        try:
            return check_output(['rpm', '-q',
              '--qf', '%{VERSION}', package], universal_newlines=True)
        except FileNotFoundError:
            return None
        except subprocess.CalledProcessError:
            return None

    def is_available(self, package):
        # assume no apt-like system in this base class
        return self.is_installed(package)

    def available_version(self, package):
        # assume no apt-like system in this base class
        return self.current_version(package)

    def install_packages(self, rpms, method=None, gain_root='su'):
        """Install one or more packages (a list of filenames)."""

        if not method:
            method = self.INSTALL_CMD[0]

        if method == 'dnf':
            run_as_root(['dnf', 'install'] + list(rpms), gain_root)
        elif method == 'zypper':
            run_as_root(['zypper', 'install'] + list(rpms), gain_root)
        elif method == 'urpmi':
            run_as_root(['/usr/sbin/urpmi'] + list(rpms), gain_root)
        else:
            if method != 'rpm':
                logger.warning(('Unknown installation method %r,'
                                ' using rpm instead') % method)
            run_as_root(['rpm', '-U'] + list(rpms), gain_root)

    def format_relation(self, pr):
        assert not pr.contextual
        assert not pr.alternatives

        if pr.version is not None:
            op = pr.version_operator

            if op in ('<<', '>>'):
                op = op[0]

            # foo >= 1.0
            return '%s %s %s' % (self.rename_package(pr.package), op,
                    pr.version)

        return self.rename_package(pr.package)

    def __fill_dest_dir_rpm(self, game, package, workdir, destdir, compress,
            architecture, release):
        specfile = os.path.join(workdir, '%s.spec' % package.name)
        short_desc, long_desc = self.generate_description(game, package)
        short_desc = short_desc[0].upper() + short_desc[1:]

        if game.wikibase:
            url = game.wikibase + (game.wiki or '')
        elif game.wikipedia:
            url = game.wikipedia
        else:
            url = 'https://wiki.debian.org/Games/GameDataPackager'

        # /usr/games & /usr/share/games should only
        # be seen in rpm's built for Mageia
        SYSTEM_DIRS = set(['/usr',
                           '/usr/bin',
                           '/usr/games',
                           '/usr/lib',
                           '/usr/share',
                           '/usr/share/applications',
                           '/usr/share/doc',
                           '/usr/share/doc/packages',
                           '/usr/share/games',
                           '/usr/share/icons',
                           '/usr/share/icons/hicolor',
                           '/usr/share/icons/hicolor/scalable',
                           '/usr/share/icons/hicolor/scalable/apps',
                           '/usr/share/licenses',
                           '/usr/share/pixmaps'])

        files = set()
        for dirpath, dirnames, filenames in os.walk(destdir):
             dir = dirpath[len(destdir):]
             if not dir:
                 # /
                 continue
             elif dir in SYSTEM_DIRS:
                 for fn in filenames + dirnames:
                     full = os.path.join(dirpath, fn)
                     file = full[len(destdir):]
                     if file not in SYSTEM_DIRS:
                         files.add(file)
             else:
                 for file in files:
                     if dir.startswith(file):
                         break
                 else:
                     files.add(dir)

        logger.debug('%%files in specfile:\n%s', '\n'.join(sorted(files)))

        with open(specfile, 'w', encoding='utf-8') as spec:
            spec.write('Summary: %s\n' % short_desc)
            spec.write('Name: %s\n' % package.name)
            spec.write('Version: %s\n' % package.version)
            spec.write('Url: %s\n' % url)
            spec.write('Release: %s\n' % release)
            spec.write('License: Commercial\n')
            if self.derives_from('mageia'):
                spec.write('Packager: game-data-packager\n')
                spec.write('Group: Games/%s\n' % game.genre)
            else:
                spec.write('Group: Amusements/Games\n')
            spec.write('BuildArch: %s\n' % architecture)

            for p in self.merge_relations(package, 'provides'):
                spec.write('Provides: %s\n' % p)

                if package.mutually_exclusive:
                    spec.write('Conflicts: %s\n' % p)

            if package.expansion_for:
                spec.write('Requires: %s\n' % package.expansion_for)
            else:
                engine = self.substitute(
                        package.engine or game.engine,
                        package.name)

                if engine and len(engine.split()) == 1:
                    spec.write('Requires: %s\n' % engine)

            for p in self.merge_relations(package, 'depends'):
                spec.write('Requires: %s\n' % p)

            for p in (self.merge_relations(package, 'conflicts') |
                    self.merge_relations(package, 'breaks')):
                spec.write('Conflicts: %s\n' % p)

            for p in self.merge_relations(package, 'recommends'):
                # FIXME: some RPM distributions do have recommends;
                # which ones?
                pass

            for p in self.merge_relations(package, 'suggests'):
                # FIXME: likewise
                pass

            # FIXME: replaces?

            if not compress or package.rip_cd:
                spec.write('%define _binary_payload w0.gzdio\n')
            elif compress == ['-Zgzip', '-z1']:
                spec.write('%define _binary_payload w1.gzdio\n')
            spec.write('%description\n')
            spec.write('%s\n' % long_desc)
            spec.write('%files\n')
            spec.write('\n'.join(files))
            spec.write('\n\n')

            spec.write('%changelog\n')
            try:
                login = os.getlogin()
            except FileNotFoundError:
                login = 'game-data-packager'
            spec.write('* %s %s@%s - %s-%s\n' %
                        (time.strftime("%a %b %d %Y", time.gmtime()),
                         login, os.uname()[1], package.version, release))
            spec.write('- Package generated by game-data-packager'
                       ' for local use only\n')

        return specfile

    def build_package(self, per_package_dir, game, package, destination,
            compress=True):
        destdir = os.path.join(per_package_dir, 'DESTDIR')
        arch = self.get_effective_architecture(package)

        if arch == 'noarch':
            setarch = []
        else:
            setarch = ['setarch', arch]

        # increase local 'release' number on repacking
        if not self.is_installed(package.name):
            release = '0'
        elif Version(package.version) > Version(self.current_version(package.name)):
            release = '0'
        else:
            try:
                release = check_output(['rpm', '-q', '--qf' ,'%{RELEASE}',
                                         package.name]).decode('ascii')
                if (self.distro is not None and
                        release.endswith('.' + self.distro)):
                    release = release[:-(len(self.distro) + 1)]
                release = str(int(release) + 1)
            except (subprocess.CalledProcessError, ValueError):
                release = '0'

        if self.distro is not None:
            release = release + '.' + self.distro

        if compress:
            compress = game.compress_deb

        specfile = self.__fill_dest_dir_rpm(game, package,
                per_package_dir, destdir, compress, arch, release)
        normalize_permissions(destdir)

        assert os.path.isdir(os.path.join(destdir, 'usr')), destdir

        try:
            logger.info('generating package %s', package.name)
            check_output(setarch  + ['rpmbuild',
                         '--buildroot', destdir,
                         '-bb', '-v', specfile],
                         cwd=per_package_dir)
        except subprocess.CalledProcessError as cpe:
            print(cpe.output)
            raise

        return(os.path.expanduser('~/rpmbuild/RPMS/') + arch + '/'
                + package.name + '-'
                + package.version + '-' + release + '.' + arch + '.rpm')

# XXX: dnf is written in python3 and has a stable public api,
#      it is likely faster to use it instead of calling 'dnf' pgm.
#
#      I just can't make sense of it or of these "simple examples"
#
#      http://dnf.readthedocs.org/en/latest/api_base.html
#      https://github.com/timlau/dnf-apiex
#
#      As install_packages() needs root, we need to use the 'dnf' pgm

class DnfPackaging(RpmPackaging):
    LICENSEDIR = '/usr/share/licenses'
    INSTALL_CMD = ['dnf', 'install']
    PACKAGE_MAP = {
                  'dpkg-deb': 'dpkg',
                  'id-shr-extract': None,
                  '7z': 'p7zip-plugins',
                  'unrar-nonfree': 'unrar',
                  }

    def __init__(self, distro='fedora'):
        super(DnfPackaging, self).__init__(distro)
        self.available = None

    def read_architecture(self):
        super(DnfPackaging, self).read_architecture()
        if self._architecture == 'amd64':
            self._foreign_architectures = set(['i386'])

    def is_available(self, package):
        if self.available is None:
            try:
                proc = subprocess.Popen(['dnf', 'list'],
                        universal_newlines=True,
                        stderr=subprocess.DEVNULL,
                        stdout=subprocess.PIPE)
            except FileNotFoundError:
                return False
            cache = set()
            for line in proc.stdout:
                if '.' in line:
                    cache.add(line.split('.')[0])
            self.available = cache

        return package in self.available

    def available_version(self, package):
        try:
            proc = subprocess.Popen(['dnf', 'list', package],
                                     universal_newlines=True,
                                     stderr=subprocess.DEVNULL,
                                     stdout=subprocess.PIPE)
        except FileNotFoundError:
            return None
        # keep only last line
        for line in proc.stdout:
            pass
        return line.split()[1]

    def install_packages(self, rpms, method='dnf', gain_root='su'):
        super(DnfPackaging, self).install_packages(rpms, method=method,
                gain_root=gain_root)

class ZypperPackaging(RpmPackaging):
    DOCDIR = '/usr/share/doc/packages'
    LICENSEDIR = '/usr/share/doc/packages'
    INSTALL_CMD = ['zypper', 'install']
    PACKAGE_MAP = {
                  'dpkg-deb': 'dpkg',
                  'id-shr-extract': None,
                  '7z': 'p7zip',
                  'unrar-nonfree': 'unrar',
                  }

    def __init__(self, distro='suse'):
        super(ZypperPackaging, self).__init__(distro)

    def is_available(self, package):
        try:
            proc = subprocess.Popen(['zypper', 'info', package],
                    universal_newlines=True,
                    stdout=subprocess.PIPE,
                    env={'LANG':'C'})
        except FileNotFoundError:
            return False
        for line in proc.stdout:
            if line.startswith('Version:'):
                return True
        return False

    def available_version(self, package):
        try:
            proc = subprocess.Popen(['zypper', 'info', package],
                    universal_newlines=True,
                    stdout=subprocess.PIPE,
                    env={'LANG':'C'})
        except FileNotFoundError:
            return None
        for line in proc.stdout:
            if line.startswith('Version:'):
                return line.split(':', maxsplit=1)[1]

    def install_packages(self, rpms, method='zypper', gain_root='su'):
        super(ZypperPackaging, self).install_packages(rpms, method=method,
                gain_root=gain_root)

class UrpmiPackaging(RpmPackaging):
    BINDIR = '/usr/games'
    ASSETS = '/usr/share/games'
    INSTALL_CMD = ['urpmi']
    PACKAGE_MAP = {
                  'dpkg-deb': 'dpkg',
                  'id-shr-extract': None,
                  '7z': 'p7zip',
                  'unrar-nonfree': 'unrar',
                  }

    def __init__(self, distro='mageia'):
        super(UrpmiPackaging, self).__init__(distro)

    def is_available(self, package):
        try:
            return 0 == subprocess.call(['urpmq', package],
                                        stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            return False

    def available_version(self, package):
        try:
            line = check_output(['urpmq', '-r', package]).decode('ascii')
            return line.split('-')[-2]
        except FileNotFoundError:
            return None
        except subprocess.CalledProcessError:
            return None

def get_packaging_system(distro=None):
    if distro is None:
        distro = _get_distro()

    if distro == 'mageia':
        return UrpmiPackaging(distro)
    elif distro == 'fedora':
        return DnfPackaging(distro)
    elif distro == 'suse':
        return ZypperPackaging(distro)

    return RpmPackaging(distro)

def _get_distro():
    if os.path.isfile('/etc/mageia-release'):
        return 'mageia'

    if os.path.isfile('/etc/redhat-release'):
        return 'fedora'

    if os.path.isfile('/etc/SuSE-release'):
        return 'suse'

    try:
        maybe = DnfPackaging()

        if maybe.is_available('rpm'):
            return 'fedora'
    except:
        pass

    try:
        maybe = ZypperPackaging()

        if maybe.is_available('rpm'):
            return 'suse'
    except:
        pass

    return 'generic'
