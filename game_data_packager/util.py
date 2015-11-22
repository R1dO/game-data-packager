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

import grp
import logging
import os
import shlex
import shutil
import stat
import subprocess
import sys

from .paths import DATADIR
from .version import (GAME_PACKAGE_VERSION, FORMAT, DISTRO)

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

def prefered_langs():
    if prefered_langs.langs is not None:
        return prefered_langs.langs

    lang_raw = []
    if 'LANGUAGE' in os.environ:
        lang_raw = os.getenv('LANGUAGE').split(':')
    if 'LANG' in os.environ:
        lang_raw.append(os.getenv('LANG'))
    lang_raw.append('en')

    prefered_langs.langs = []
    for lang in lang_raw:
        lang = lang.split('.')[0]
        if not lang or lang == 'C':
            continue
        if lang in ('en_US', 'en_GB', 'pt_BR'):
            prefered_langs.langs.append(lang)
        lang = lang[0:2]
        if lang not in prefered_langs.langs:
            prefered_langs.langs.append(lang)

    return prefered_langs.langs

prefered_langs.langs = None

def lang_score(lang):
    langs = prefered_langs()

    if lang in langs:
        return len(langs) - langs.index(lang)

    lang = lang[0:2]
    if lang in langs:
        return len(langs) - langs.index(lang)

    return 0

def ascii_safe(string, force=False):
    if sys.stdout.encoding != 'UTF-8' or force:
        string = string.translate(str.maketrans('àäçčéèêëîïíłñ§┏┛',
                                                'aacceeeeiiiln***'))
    return string

def run_as_root(argv, gain_root=''):
    if not gain_root and which('pkexec') is not None:
            # Use pkexec if possible. It has desktop integration, and will
            # prompt for the user's password if they are administratively
            # privileged (a member of group sudo), or root's password
            # otherwise.
            gain_root = 'pkexec'

    if not gain_root and which('sudo') is not None:
        # Use sudo as the next choice after pkexec, but only if we're in
        # a group that should be able to use it.
        try:
            sudo_group = grp.getgrnam('sudo')
        except KeyError:
            pass
        else:
            if sudo_group.gr_gid in os.getgroups():
                gain_root = 'sudo'

        # If we are in the admin group, also use sudo, but only
        # if this looks like Ubuntu. We use dpkg-vendor at build time
        # to detect Ubuntu derivatives.
        try:
            admin_group = grp.getgrnam('admin')
        except KeyError:
            pass
        else:
            if (admin_group.gr_gid in os.getgroups() and
                    os.path.exists(os.path.join(DATADIR,
                        'is-ubuntu-derived'))):
                gain_root = 'sudo'

    if not gain_root:
        # Use su if we don't have anything better.
        gain_root = 'su'

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

def check_call(command, *args, **kwargs):
    """Like subprocess.check_call, but log what we will do first."""
    logger.debug('%r', command)
    return subprocess.check_call(command, *args, **kwargs)

def check_output(command, *args, **kwargs):
    """Like subprocess.check_output, but log what we will do first."""
    logger.debug('%r', command)
    return subprocess.check_output(command, *args, **kwargs)

def recursive_utime(directory, orig_time):
    """Recursively set the access and modification times of everything
    in directory to orig_time.

    orig_time may be a tuple (atime, mtime), or a single int or float.
    """
    if isinstance(orig_time, (int, float)):
        orig_time = (orig_time, orig_time)

    for dirpath, dirnames, filenames in os.walk(directory):
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            os.utime(full, orig_time)

# https://wiki.archlinux.org/index.php/Pacman/Rosetta

# loaded at the end to avoid failed cyclic loads
if FORMAT == 'deb':
    from .util_deb import (PACKAGE_CACHE,
                           install_packages,
                           lintian_license,
                           lintian_desktop)
elif FORMAT == 'arch':
    from .util_arch import (PACKAGE_CACHE, install_packages)
    lintian_license = lambda a,b,c: None
    lintian_desktop = lambda a,b,c: None
elif DISTRO == 'fedora':
    from .util_fedora import (PACKAGE_CACHE, install_packages)
    lintian_license = lambda a,b,c: None
    lintian_desktop = lambda a,b,c: None
elif DISTRO == 'suse':
    from .util_suse import (PACKAGE_CACHE, install_packages)
    lintian_license = lambda a,b,c: None
    lintian_desktop = lambda a,b,c: None

# pyflakes
PACKAGE_CACHE
install_packages
lintian_license
lintian_desktop
