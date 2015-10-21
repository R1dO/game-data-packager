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

import logging
import os
import shlex
import shutil
import stat
import subprocess
import sys

from debian.debian_support import Version

from .version import GAME_PACKAGE_VERSION

logger = logging.getLogger('game-data-packager.util')

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

    def current_version(self, package):
        # 'dpkg-query: no packages found matching $package'
        # will leak on stderr if called with an unknown package,
        # but that should never happen
        try:
            return check_output(['dpkg-query', '--show',
              '--showformat', '${Version}', package], universal_newlines=True)
        except subprocess.CalledProcessError:
            return

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

def run_as_root(argv, gain_root='su'):
    if gain_root not in ('su', 'pkexec' ,'sudo', 'super', 'really'):
        logger.warning(('Unknown privilege escalation method %r, assuming ' +
            'it works like sudo') % gain_root)

    if gain_root == 'su':
        print('using su to obtain root privileges and install the package(s)')

        # su expects a single sh(1) command-line
        cmd = ' '.join([shlex.quote(arg) for arg in argv])

        subprocess.call(['su', '-c', cmd])
    else:
        # this code path works for pkexec, sudo, super, really;
        # we assume everything else is the same
        print('using %s to obtain root privileges and install the package(s)' %
                gain_root)
        subprocess.call([gain_root] + list(argv))

def install_packages(debs, method, gain_root='su'):
    """Install one or more packages (a list of filenames)."""

    if method and method not in (
            'apt', 'dpkg',
            'gdebi', 'gdebi-gtk', 'gdebi-kde',
            ):
        logger.warning(('Unknown installation method %r, using apt or dpkg ' +
            'instead') % method)
        method = None

    if not method:
        apt_ver = PACKAGE_CACHE.current_version('apt')
        if Version(apt_ver.strip()) >= Version('1.1~0'):
            method = 'apt'
        else:
            method = 'dpkg'

    if method == 'apt':
        run_as_root(['apt-get', 'install', '--install-recommends'] + list(debs),
                gain_root)
    elif method == 'dpkg':
        run_as_root(['dpkg', '-i'] + list(debs), gain_root)
    elif method == 'gdebi':
        run_as_root(['gdebi'] + list(debs), gain_root)
    else:
        # gdebi-gtk etc.
        subprocess.call([method] + list(debs))

def check_call(command, *args, **kwargs):
    """Like subprocess.check_call, but log what we will do first."""
    logger.debug('%r', command)
    return subprocess.check_call(command, *args, **kwargs)

def check_output(command, *args, **kwargs):
    """Like subprocess.check_output, but log what we will do first."""
    logger.debug('%r', command)
    return subprocess.check_output(command, *args, **kwargs)
