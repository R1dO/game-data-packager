#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2014-2015 Simon McVittie <smcv@debian.org>
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

import os
import shlex
import shutil
import stat
import subprocess
import sys

from debian.debian_support import Version

from .version import GAME_PACKAGE_VERSION

KIBIBYTE = 1024
MEBIBYTE = KIBIBYTE * KIBIBYTE

AGENT = ('Debian Game-Data-Packager/%s (%s %s;'
         ' +http://wiki.debian.org/Games/GameDataPackager)' %
        (GAME_PACKAGE_VERSION, os.uname()[0], os.uname()[4]) )

class TemporaryUmask(object):
    """Context manager to set the umask. Not thread-safe.

    Use like this::

        with TemporaryUmask(0o022):
            os.makedirs('usr/share/misc')
    """

    def __init__(self, desired_mask):
        self.desired_mask = desired_mask
        self.saved_mask = None

    def __enter__(self):
        self.saved_mask = os.umask(self.desired_mask)

    def __exit__(self, et, ev, tb):
        os.umask(self.saved_mask)

def mkdir_p(path):
    if not os.path.isdir(path):
        with TemporaryUmask(0o022):
            os.makedirs(path)

def rm_rf(path):
    if os.path.exists(path):
        shutil.rmtree(path)

def which(exe):
    for path in os.environ.get('PATH', '/usr/bin:/bin').split(os.pathsep):
        try:
            abspath = os.path.join(path, exe)
            statbuf = os.stat(abspath)
        except:
            continue
        if stat.S_IMODE(statbuf.st_mode) & 0o111:
            return abspath

    return None

def human_size(size):
    # 0.0 KiB up to 1024.0 KiB
    if size < MEBIBYTE:
        return '%.1f KiB' % (size / KIBIBYTE)

    # 1.0 MiB or more
    return '%.1f MiB' % (size / (MEBIBYTE))

def copy_with_substitutions(from_, to, **kwargs):
    for line in from_:
        for k, v in kwargs.items():
            line = line.replace(k, v)
        to.write(line)

class PackageCache:
    installed = None
    available = None

    def is_installed(self, package):
        # FIXME: this shouldn't be hard-coded
        if package == 'doom-engine':
            return (self.is_installed('chocolate-doom')
                 or self.is_installed('prboom-plus')
                 or self.is_installed('doomsday'))
        if package == 'boom-engine':
            return (self.is_installed('prboom-plus')
                 or self.is_installed('doomsday'))
        if package == 'heretic-engine':
            return (self.is_installed('chocolate-heretic')
                 or self.is_installed('doomsday'))
        if package == 'hexen-engine':
            return (self.is_installed('chocolate-hexen')
                 or self.is_installed('doomsday'))

        if os.path.isdir(os.path.join('/usr/share/doc', package)):
            return True

        if self.installed is None:
            cache = set()
            proc = subprocess.Popen(['dpkg-query', '--show',
                        '--showformat', '${Package}\\n'],
                    universal_newlines=True,
                    stdout=subprocess.PIPE)
            for line in proc.stdout:
                cache.add(line.rstrip())
            self.installed = cache

        return package in self.installed

    def is_available(self, package):
        if self.available is None:
            cache = set()
            proc = subprocess.Popen(['apt-cache', 'pkgnames'],
                    universal_newlines=True,
                    stdout=subprocess.PIPE)
            for line in proc.stdout:
                cache.add(line.rstrip())
            self.available = cache

        return package in self.available

PACKAGE_CACHE = PackageCache()

def prefered_lang():
    lang_raw = []
    if 'LANGUAGE' in os.environ:
        lang_raw = os.getenv('LANGUAGE').split(':')
    if 'LANG' in os.environ:
        lang_raw.append(os.getenv('LANG'))
    lang_raw.append('en')

    lang_pref = []
    for lang in lang_raw:
        lang = lang.split('.')[0]
        if not lang or lang == 'C':
            continue
        if lang in ('en_GB', 'pt_BR'):
            lang_pref.append(lang)
        lang_pref.append(lang[0:2])
    return lang_pref

def lang_score(lang):
    langs = prefered_lang()
    if lang not in langs:
        return 0

    return len(langs) - langs.index(lang)

def ascii_safe(string, force=False):
    if sys.stdout.encoding != 'UTF-8' or force:
        string = string.translate(str.maketrans('àäçčéèêëîïíłñ§┏┛',
                                                'aacceeeeiiiln***'))
    return string

def install_packages(debs):
    """Install one or more packages (a list of filenames)."""

    print('using su(1) to obtain root privileges and install the package(s)')

    apt_ver = subprocess.check_output(['dpkg-query', '--show',
                '--showformat', '${Version}', 'apt'], universal_newlines=True)
    if Version(apt_ver.strip()) >= Version('1.1'):
        cmd = 'apt-get install --install-recommends'
    else:
        cmd = 'dpkg -i'

    for deb in debs:
        cmd = cmd + ' ' + shlex.quote(deb)

    subprocess.call(['su', '-c', cmd])
