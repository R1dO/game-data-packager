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
import shutil
import stat
import subprocess

KIBIBYTE = 1024
MEBIBYTE = KIBIBYTE * KIBIBYTE

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

def is_installed(package):
    # FIXME: this shouldn't be hard-coded
    if package == 'doom-engine':
        return (is_installed('chocolate-doom')
             or is_installed('prboom-plus')
             or is_installed('doomsday'))
    if package == 'boom-engine':
        return (is_installed('prboom-plus')
             or is_installed('doomsday'))
    if package in ('heretic-engine', 'hexen-engine'):
        return (is_installed('chocolate-doom')
             or is_installed('doomsday'))

    return os.path.isdir(os.path.join('/usr/share/doc', package))

def is_avaible(package):
    proc = subprocess.Popen(['apt-cache', 'pkgnames', package],
                            universal_newlines=True,
                            stdout=subprocess.PIPE)
    for line in proc.stdout:
        if line.rstrip() == package:
            return True
    return False

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
