#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2015 Simon McVittie <smcv@debian.org>
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

import argparse
import logging
import os
import subprocess
import sys
import tarfile
import tempfile
import glob
import zipfile

import yaml
try:
    from debian.deb822 import Deb822
    from debian.debian_support import Version
    ON_DEBIAN = True
except ImportError:
    from distutils.version import LooseVersion as Version
    ON_DEBIAN = False

from . import HashedFile
from .gog import GOG
from .steam import parse_acf
from .util import (
        check_output,
        which,
        )

logging.basicConfig()
logger = logging.getLogger('game_data_packager.make-template')

# I guess there is a minimum size under which a
# MD5 collision is not possible and having
# a SHA1 for these files is not useful
MD5_SAFE_ENOUGH = 5000

def guess_lang(string):
    string = string.lower()
    path = os.path.basename(string.rstrip('/'))
    if path in ('de', 'en', 'fr', 'it', 'ja', 'pl', 'ru'):
        return path
    for short, long in [('de', 'german'),
                        ('es', 'spanish'),
                        ('fr', 'french'),
                        ('it', 'italian'),
                        ('ja', 'japanese'),
                        ('pl', 'polish'),
                        ('ru', 'russian')]:
      if long in string:
          return short
    # check against other args
    for lang in ('german', 'spanish', 'french', 'italian', 'polish', 'russian'):
        for arg in sys.argv:
            if lang in arg:
                return 'en'

def is_license(file):
    file = file.split('?')[0]
    name, ext = os.path.splitext(file.lower())
    if ext not in ('.doc', '.htm', '.html', '.pdf', '.txt', ''):
        return False
    for word in ('eula', 'license', 'vendor'):
        if word in name:
            return True
    return False

def iter_path_components(filename):
    dirname, basename = os.path.split(filename)

    if dirname == filename:
        # the root
        yield dirname
    elif dirname:
        for x in iter_path_components(dirname):
            yield x

    if basename:
        yield basename

def is_doc(file):
    file = file.split('?')[0]

    for dirname in iter_path_components(file):
        if dirname.lower() in  ('manual', 'docs', 'doc', 'help'):
            return True

    name, ext = os.path.splitext(file.lower())

    if ext not in ('.doc', '.htm', '.html', '.pdf', '.txt', ''):
        return False

    for word in ('changes', 'hintbook', 'manual', 'quickstart',
                 'readme', 'refcard', 'reference', 'support'):
        if word in name:
            return True

    return False

def is_dosbox(file):
    '''check if DOSBox assests are just dropped in games assets directory'''
    basename = os.path.basename(file)
    if basename in ('dosbox.conf',  'dosbox.exe',
                    'dosbox-0.71.tar.gz', 'dosbox-0.74.tar.gz',
                    'SDL_net.dll', 'SDL.dll', 'zmbv.dll', 'zmbv.inf'):
         return True
    # to check: COPYING.txt INSTALL.txt NEWS.txt THANKS.txt *.conf
    if basename.startswith('dosbox'):
         return True
    if basename not in ('AUTHORS.txt', 'README.txt'):
         return False
    with open(file, 'r', encoding='latin1') as txt:
         line = txt.readline()
         return 'dosbox' in line.lower()

def is_runtime(path):
    dir_l = path.lower()
    for runtime in ('data.now', 'directx', 'dosbox'):
        if '/%s/' % runtime in dir_l:
            return True
        if dir_l.endswith('/' + runtime):
            logger.warning('ignoring %s runtime at %s' % (runtime, path))
            return True
    return False

class GameData(object):
    '''simplified object with only one package per game'''
    def __init__(self):
        self.longname = None
        self.try_repack_from = []
        self.plugin = None
        self.gog_url = None
        self.gog_game = None
        self.gog_path = None

        self.data = dict()
        # global list of files across packages
        self.install = set()
        self.optional = set()
        self.doc = set()
        self.license = set()
        self.loose_file = set()

        self.files = dict(files={})
        self.size = {}
        self.md5 = {}
        self.sha1 = {}

    def is_scummvm(self,path):
        dir_l = path.lower()
        if dir_l.endswith('/scummvm') or '/scummvm/' in dir_l:
            self.plugin = 'scummvm_common'
            return True
        return False

    def add_one_file(self, name, lower, is_content=True):
        out_name = os.path.basename(name)
        if lower:
            out_name = out_name.lower()

        if not is_content:
            pass
        elif is_license(name):
            out_name = os.path.basename(out_name)
            self.loose_file.add(out_name)
        elif is_doc(name):
            self.loose_file.add(out_name)
            self.files['files'][out_name] = dict(install_to='$docdir')
        else:
            self.loose_file.add(out_name)

        hf = HashedFile.from_file(name, open(name, 'rb'))
        self.size[out_name] = size = os.path.getsize(name)
        self.md5[out_name] = hf.md5
        if size > MD5_SAFE_ENOUGH:
            self.sha1[out_name] = hf.sha1

    def add_one_dir(self, destdir, lower, game=None, lang=None):
        if destdir.startswith('/usr/local') or destdir.startswith('/opt/'):
            self.try_repack_from.append(destdir)

        if not game:
            game = os.path.basename(os.path.abspath(destdir))
        if game.endswith('-data'):
            game = game[:len(game) - 5]

        steam = max(destdir.find('/SteamApps/common/'),
                    destdir.find('/steamapps/common/'))
        if steam > 0:
            steam_dict = dict()
            steam_id = 'FIXME'
            for acf in parse_acf(destdir[:steam+11]):
                if '/common/' + acf['installdir'] in destdir:
                     steam_id = acf['appid']
                     self.longname = game = acf['name']
                     break
            steam_dict['id'] = int(steam_id)
            steam_dict['path'] = destdir[steam+11:]

        game = game.replace(' ','').replace(':','').replace('_','-').lower()
        if lang:
            pkg = game + '-' + lang + '-data'
            virtual = game + '-data'
        else:
            pkg = game + '-data'
        self.package = self.data.setdefault('packages', {}).setdefault(pkg, {})
        if lang:
            if lang != 'en':
                self.package['lang'] = lang
            self.package['provides'] = virtual

        self.package['install'] = []
        self.package['optional'] = []
        self.package['doc'] = []
        self.package['license'] = []

        if steam > 0:
            self.package['steam'] = steam_dict

        has_dosbox = False

        for dirpath, dirnames, filenames in os.walk(destdir):
            if self.is_scummvm(dirpath) or is_runtime(dirpath):
                continue

            for fn in filenames:
                path = os.path.join(dirpath, fn)

                assert path.startswith(destdir + '/')
                name = path[len(destdir) + 1:]
                out_name = name
                if lower:
                    out_name = out_name.lower()

                if os.path.isdir(path):
                    continue
                elif is_dosbox(path):
                    has_dosbox = True
                elif os.path.splitext(fn.lower())[1] in ('.exe', '.exe$0', '.ovl',
                                                         '.dll', '.dll$0', '.bat', '.386'):
                    logger.warning('ignoring dos/windows binary %s' % fn)
                elif out_name.startswith('goggame-') or out_name in ('webcache.zip',
                                                                 'gog.ico', 'gfw_high.ico'):
                    logger.warning('ignoring GOG stuff %s' % fn)
                elif os.path.islink(path):
                    self.package.setdefault('symlinks', {})[name] = os.path.realpath(path).lstrip('/')
                elif os.path.isfile(path):
                    size = os.path.getsize(path)
                    hf = HashedFile.from_file(name, open(path, 'rb'))
                    # avoid that look_for: overlaps in cases where
                    # that leeds to looping during package build.
                    #
                    # e.g.:
                    #   md5 English = $A
                    #   md5 German = $B
                    #   md5 French = $B
                    for existing in self.size.keys():
                        if (    size == self.size[existing]
                            and hf.md5 == self.md5[existing]
                            and existing.startswith(out_name)):
                            out_name = existing
                            break
                    else:
                        if out_name in self.size:
                            if (size == self.size[out_name] and hf.md5 == self.md5[out_name]):
                                pass
                            elif lang:
                                out_name += ('?' + lang)
                            else:
                                out_name += ('?' + hf.md5[1:6])

                    if is_license(fn):
                        out_name = os.path.basename(out_name)
                        self.license.add(out_name)
                        self.package['license'].append(out_name)
                    elif is_doc(path):
                        self.doc.add(out_name)
                        self.package['doc'].append(out_name)
                    # most of the times these files are not needed
                    elif fn.lower().split('.')[-1] in ('cfg', 'cmd', 'com', 'drv', 'ico', 'ini'):
                        self.optional.add(out_name)
                        self.package['optional'].append(out_name)
                    else:
                        self.install.add(out_name)
                        self.package['install'].append(out_name)

                    self.size[out_name] = size
                    self.md5[out_name] = hf.md5
                    if size > MD5_SAFE_ENOUGH:
                        self.sha1[out_name] = hf.sha1
                else:
                    logger.warning('ignoring unknown file type at %s' % path)

            if has_dosbox:
                logger.warning('DOSBOX files detected, make sure not to include those in your package')

        if self.plugin != 'scummvm_common':
            self.package['install_to'] = 'usr/share/games/' + game

        self.package['install'].sort()
        if self.package['optional']:
            self.package['optional'].sort()
        else:
            del self.package['optional']
        if self.package['doc']:
            self.package['doc'].sort()
        else:
            del self.package['doc']
        if self.package['license']:
            self.package['license'].sort()
        else:
            del self.package['license']

    def add_one_zip(self,archive):
        self.add_one_file(archive, lower=False, is_content=False)
        # TODO
        return

    def add_one_gog_sh(self,archive):
        self.add_one_zip(archive)
        with zipfile.ZipFile(archive, 'r') as zf:
            if 'scripts/config.lua' in zf.namelist():
                with zf.open('scripts/config.lua') as metadata:
                    for line in metadata.read().decode().splitlines():
                        line = line.strip()
                        if line.startswith('id = '):
                            self.gog_path = line.split('"')[1]

    def add_one_innoextract(self,exe):
        game = self.gog_game = GOG.get_id_from_archive(exe)
        if not game:
            game = os.path.basename(exe)
            game = game[len('setup_'):len(game)-len('.exe')]
            last_part = game.split('_')[-1]
            if last_part.strip('0123456789.') == '':
                game = game[0:len(game)-len(last_part)-1]
            last_part = game.split('_')[-1]
            if last_part in ('german', 'spanish', 'french', 'italian', 'polish', 'russian'):
                game = game[0:len(game)-len(last_part)-1]

        tmp = tempfile.mkdtemp(prefix='gdptmp.')

        command = ['innoextract', os.path.realpath(exe)]
        version = check_output(['innoextract', '-v', '-s'], universal_newlines=True)
        if Version(version.split('-')[0]) >= Version('1.5'):
            command.append('-I')
            command.append('app')
            command.append('--collisions=rename')

        logger.info('running "%s" ...' % ' '.join(command))
        log = check_output(command,
                 stderr=subprocess.DEVNULL,
                 universal_newlines=True,
                 cwd=tmp)
        self.longname = log.split('\n')[0].split('"')[1]
        self.add_one_dir(os.path.join(tmp, 'app'), True, game=game, lang=guess_lang(exe))
        os.system('rm -r ' + tmp)

        self.add_one_file(exe, lower=False, is_content=False)
        self.files['files'][os.path.basename(exe)] = dict(unpack=dict(format='innoextract'),provides=['file1','file2'])

    def add_one_deb(self,deb,lower):
        if not ON_DEBIAN or not which('dpkg-deb'):
            exit('.deb analysis is only implemented on Debian.')

        control = None

        version = None
        with subprocess.Popen(['dpkg-deb', '--ctrl-tarfile', deb],
                stdout=subprocess.PIPE) as ctrl_process:
            with tarfile.open(deb + '//control.tar.*', mode='r|',
                    fileobj=ctrl_process.stdout) as ctrl_tarfile:
                for entry in ctrl_tarfile:
                    name = entry.name
                    if name == '.':
                        continue

                    if name.startswith('./'):
                        name = name[2:]
                    if name == 'control':
                        reader = ctrl_tarfile.extractfile(entry)
                        control = Deb822(reader)
                        print('# data/%s.control.in' % control['package'])
                        version = control['version']
                        if 'Homepage' in control:
                            if 'gog.com/' in control['Homepage']:
                                self.gog_url = control['Homepage'].split('/')[-1]

                        control.dump(fd=sys.stdout, text_mode=True)
                        print('')
                    elif name == 'preinst':
                        logger.warning('ignoring preinst, not supported yet')
                    elif name == 'md5sums':
                        pass
                    else:
                        logger.warning('unknown control member: %s', name)

        if control is None:
            logger.error('Could not find DEBIAN/control')

        self.data = dict(packages={ control['package']: {} })
        self.package = self.data['packages'][control['package']]
        self.package['install'] = []
        self.package['optional'] = []
        self.package['license'] = []
        if version:
            self.package['version'] = version

        install_to = None

        with subprocess.Popen(['dpkg-deb', '--fsys-tarfile', deb],
                stdout=subprocess.PIPE) as fsys_process:
            with tarfile.open(deb + '//data.tar.*', mode='r|',
                    fileobj=fsys_process.stdout) as fsys_tarfile:
                for entry in fsys_tarfile:
                    name = entry.name
                    if name.startswith('./'):
                        name = name[2:]

                    if self.is_scummvm(name) or is_runtime(name):
                        continue
                    if (name.startswith('usr/share/doc/') and
                            name.endswith('changelog.gz')):
                        continue
                    if (name.startswith('usr/share/doc/') and
                            name.endswith('changelog.Debian.gz')):
                        continue

                    if (name.startswith('usr/share/doc/') and
                            name.endswith('copyright')):
                        print('# data/%s.copyright' % control['package'])
                        for line in fsys_tarfile.extractfile(entry):
                            print(line.decode('utf-8'), end='')
                        print('')
                        continue

                    if (entry.isfile() and install_to is None):
                        # assume this is the place
                        if name.startswith('usr/share/games/'):
                            there = name[len('usr/share/games/'):]
                            there = there.split('/', 1)[0]
                            install_to = ('usr/share/games/' + there)
                        elif name.startswith('opt/GOG Games/'):
                            there = name[len('opt/GOG Games/'):]
                            there = there.split('/', 1)[0]
                            install_to = ('opt/GOG Games/' + there)
                            self.gog_path = there

                    if entry.isfile():
                        hf = HashedFile.from_file(deb + '//data.tar.*//' + name,
                                fsys_tarfile.extractfile(entry))
                        name_l = name.lower()
                        basename_l = os.path.basename(name_l)

                        if os.path.splitext(name_l)[1] in ('.exe', '.bat'):
                            logger.warning('ignoring dos/windows binary %s' % name)
                            continue
                        elif 'support/gog' in name_l or os.path.basename(name_l) in (
                                                        'start.sh', 'uninstall.sh'):
                            logger.warning('ignoring GOG stuff %s' % name)
                            continue
                        elif name.startswith('opt/') and is_license(name):
                            name = basename_l
                            self.license.add(name)
                            self.package['license'].append(name)
                        elif name.startswith('opt/') and is_doc(name):
                            name = basename_l
                            self.optional.add(name)
                            self.package['optional'].append(name)
                            self.files['files'][name] = dict(install_to='$docdir')
                        elif (install_to is not None and
                            name.startswith(install_to + '/')):
                            name = name[len(install_to) + 1:]
                            if lower:
                                name = name.lower()
                            if self.gog_url and name.startswith('data/'):
                                name = name[len('data/'):]
                            self.install.add(name)
                            self.package['install'].append(name)
                        else:
                            self.optional.add(name)
                            self.files['files'][name] = dict(install_to='.')

                        self.size[name] = entry.size
                        self.md5[name] = hf.md5
                        if entry.size > MD5_SAFE_ENOUGH:
                            self.sha1[name] = hf.sha1
                    elif entry.isdir():
                        pass
                    elif entry.issym():
                        self.package.setdefault('symlinks', {})[name] = os.path.join(
                            os.path.dirname(name), entry.linkname)
                    else:
                        logger.warning('unhandled data.tar entry type: %s: %s',
                            name, entry.type)

        if self.plugin != 'scummvm_common':
            self.package['install_to'] = install_to
        self.package['install'].sort()
        if self.package['optional']:
            self.package['optional'].sort()
        else:
            del self.package['optional']
        if self.package['license']:
            self.package['license'].sort()
        else:
            del self.package['license']

    def to_yaml(self):
        print('---')
        if self.longname:
            print('longname: %s' % self.longname)
        print('copyright: © 1970 FIXME')
        if self.try_repack_from:
            if len(self.try_repack_from) == 1:
                print('try_repack_from: %s' % self.try_repack_from)
            else:
                print('try_repack_from:')
                for path in sorted(self.try_repack_from):
                    print('- "%s"' % path)
        if self.plugin:
            print('plugin: %s' % self.plugin)
        if self.gog_url:
            print('gog:\n  url: %s' % self.gog_url)
        if self.gog_game:
            print('gog:\n  url: FIXME\n  game: %s' % self.gog_game)

        print('')
        yaml.safe_dump(self.data, stream=sys.stdout, default_flow_style=False)

        if self.loose_file:
            print('    XXX:')
            for file in sorted(self.loose_file):
                print('    - %s' % file)

        if self.files['files']:
            yaml.safe_dump(self.files, stream=sys.stdout, default_flow_style=False)

        print_order = sorted(self.install | self.optional) + sorted(self.doc) + sorted(self.license)
        print_order += sorted(set(self.size.keys()) - set(print_order))

        print('\ngroups:')

        print('  FIXME:')
        print('    group_members: |')
        for filename in print_order:
            print('      %-9s %s %s' % (self.size[filename], self.md5[filename], filename))
        print('\nsha1sums: |')
        for filename in print_order:
            if filename in self.sha1:
                print('  %s  %s' % (self.sha1[filename], filename))

        print('...')

def do_one_file(name,lower):
    hf = HashedFile.from_file(name, open(name, 'rb'))
    out_name = os.path.basename(name)
    if lower:
        out_name = out_name.lower()

    # sniff Makeself archives
    # http://megastep.org/makeself/
    has_makeself = False
    trailer = None
    SHEBANG = bytes('/bin/sh', 'ascii')
    HEADER_V1 = bytes('# This script was generated using Makeself 1.', 'ascii')
    HEADER_V2 = bytes('# This script was generated using Makeself 2.', 'ascii')
    TRAILER_V1 = bytes('END_OF_STUB', 'ascii')
    TRAILER_V2 = bytes('eval $finish; exit $res', 'ascii')
    with open(name, 'rb') as raw:
        skip = 0
        pos = 0
        for line in raw:
            pos += 1
            skip += len(line)
            if pos == 1 and SHEBANG not in line:
                break
            elif has_makeself:
                if trailer in line:
                    break
            elif HEADER_V1 in line:
                has_makeself = True
                trailer = TRAILER_V1
            elif HEADER_V2 in line:
                has_makeself = True
                trailer = TRAILER_V2
            elif pos > 3:
                break
    if has_makeself:
        print('  %s' % out_name)
        print('    unpack: tar.gz')
        print('    skip: %d' % skip)
        print()

    print('  %-9s %s %s' % (os.path.getsize(name), hf.md5, out_name))
    print('  %s  %s' % (hf.sha1, out_name))
    #print('  %s  %s' % (hf.sha256, out_name))

def do_one_exec(pgm,lower):
    print('running:', pgm)
    with subprocess.Popen(['strace', '-e', 'open',
                           '-s', '100'] + pgm,
           stderr=subprocess.PIPE, stdout=subprocess.DEVNULL,
           universal_newlines=True) as proc:
        used = set()
        missing = set()
        while proc.poll() == None:
            line = proc.stderr.readline().strip()
            if not line.startswith('open('):
                continue
            file = line.split('"')[1]
            file = file.replace('//', '/')
            if file.startswith('/usr/share/scummvm'):
                continue
            if (not file.startswith('/usr/share/games')
              and not file.startswith('/usr/share/' + pgm[0])
              and not file.startswith('/usr/local/')):
                continue
            if 'ENOENT' in line:
               missing.add(file)
            else:
               used.add(file)

        dirs = set()
        print('# used')
        for file in sorted(used):
            dirs.add(os.path.dirname(file))
            print("    - %s" % file)
        if missing:
            print('# missing ?')
            for file in sorted(missing):
                print("    - %s" % file)

        present = set()
        for dir in dirs:
            for dirpath, dirnames, filenames in os.walk(dir):
                for fn in filenames:
                    present.add(os.path.join(dirpath, fn))

        unused = present - used
        if unused:
            print('# not used')
            for file in sorted(unused):
                print("    - %s" % file)

def do_flacsums(destdir, lower):
    if which('ffmpeg'): tool = 'ffmpeg'
    elif which('avconv'): tool = 'avconv'
    else:
        exit('Install either ffmpeg or avconv')
    if not which('metaflac'):
        exit('Install metaflac')

    fla_or_flac = '.fla'
    md5s = dict()
    done_wav = 0
    done_flac = 0
    for filename in glob.glob(os.path.join(destdir, '*')):
        file = os.path.basename(filename).lower()
        file, ext = os.path.splitext(file)
        if ext == '.wav':
            md5 = check_output([tool, '-i', filename, '-f', 'md5', '-'],
                     stderr=subprocess.DEVNULL,
                     universal_newlines=True)
            md5 = md5.rstrip().split('=')[1]
            assert file not in md5s or md5s[file] == md5, \
                   "got differents md5's for %s.wav|flac" % file
            md5s[file] = md5
            done_wav += 1
        if ext == '.flac':
            fla_or_flac = '.flac'
        if ext in ('.fla','.flac'):
            md5 = check_output(['metaflac', '--show-md5sum', filename],
                     universal_newlines=True)
            md5 = md5.rstrip()
            assert file not in md5s or md5s[file] == md5, \
                   "got differents md5's for %s.wav|flac" % file
            md5s[file] = md5
            done_flac += 1

    if not md5s:
        exit("Couldn' find any .wav or .flac file")

    print('flacsums: |')
    for file in sorted(md5s.keys()):
        print('  %s  %s' % (md5s[file], file + fla_or_flac))

    print("\n#processed %i .wav and %i .fla[c] files" % (done_wav, done_flac))

def main():
    parser = argparse.ArgumentParser(
            description='Produce a template for game-data-packager YAML ' +
                'based on an existing .deb file or installed directory',
            prog='game-data-packager guess-contents')
    parser.add_argument('args', nargs='+', metavar='DEB|DIRECTORY|FILE')
    parser.add_argument('-l', '--lower', action='store_true', dest='lower',
            help='make all files lowercase')
    parser.add_argument('-e', '--execute', action='store_true', dest='execute',
            help='run this game through strace and see which files from '
                 '/usr/share/games or /usr/local/games are needed')
    parser.add_argument('-f', '--flacsums', action='store_true', dest='flacsums',
            help='compute "flacsums" from .wav files')
    args = parser.parse_args()

    # ./run make-template -e -- scummvm -p /usr/share/games/spacequest1/ sq1
    if args.execute:
        do_one_exec(args.args,args.lower)
        return
    if args.flacsums:
        do_flacsums(args.args[0],args.lower)
        return

    gamedata = GameData()

    # "./run make-template setup_<game>.exe gog_<game>.deb"
    # will merge files lists
    for arg in args.args:
        basename = os.path.basename(arg)
        if os.path.isdir(arg):
            gamedata.add_one_dir(arg.rstrip('/'), args.lower, lang=guess_lang(arg))
        elif arg.endswith('.deb'):
            gamedata.add_one_deb(arg,args.lower)
            if basename.startswith('gog_'):
                gamedata.add_one_file(arg, lower=args.lower)
                gamedata.files['files'][basename] = dict(unpack=dict(format='deb'),
                                                         provides=['<stuff>'])
        elif basename.startswith('setup_') and arg.endswith('.exe'):
            if not which('innoextract'):
                exit('Install innoextract')
            gamedata.add_one_innoextract(arg)
        elif basename.startswith('gog_') and arg.endswith('.sh'):
            gamedata.add_one_gog_sh(arg)
        elif len(args.args) == 1:
            do_one_file(arg,args.lower)
            return
        else:
            gamedata.add_one_file(arg, lower=args.lower)
    gamedata.to_yaml()


if __name__ == '__main__':
    try:
        main()
    except BrokenPipeError:
        pass
