#!/usr/bin/python3
# encoding=utf-8

# game-data-packager Gtk launcher stub. See doc/launcher.mdwn for design

# Copyright © 2015-2016 Simon McVittie <smcv@debian.org>
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
import fnmatch
import json
import logging
import os
import shutil
import string
import sys
import traceback

import gi
gi.require_version('Gtk', '3.0')

from gi.repository import (GLib, GObject)
from gi.repository import Gtk

if 'GDP_UNINSTALLED' in os.environ:
    GDP_DIR = './runtime'
else:
    GDP_DIR = '/usr/share/games/game-data-packager'

# Normalize environment so we can use ${XDG_DATA_HOME} unconditionally.
# Do this before we use GLib functions that might create worker threads,
# because setenv() is not thread-safe.
ORIG_ENVIRON = os.environ.copy()
os.environ.setdefault('XDG_CACHE_HOME', os.path.expanduser('~/.cache'))
os.environ.setdefault('XDG_CONFIG_HOME', os.path.expanduser('~/.config'))
os.environ.setdefault('XDG_CONFIG_DIRS', '/etc/xdg')
os.environ.setdefault('XDG_DATA_HOME', os.path.expanduser('~/.local/share'))
os.environ.setdefault('XDG_DATA_DIRS', '/usr/local/share:/usr/share')

logger = logging.getLogger('game-data-packager.launcher')
logging.basicConfig()

if os.environ.get('GDP_DEBUG'):
    logger.setLevel(logging.DEBUG)
else:
    logger.setLevel(logging.INFO)

DISTRO = 'the distribution'

try:
    os_release = open('/usr/lib/os-release')
except:
    pass
else:
    for line in os_release:
        if line.startswith('NAME='):
            line = line[5:].strip()
            if line.startswith('"'):
                line = line.strip('"')
            elif line.startswith("'"):
                line = line.strip("'")
            DISTRO = line

def expand(path):
    if path is None:
        return None

    return os.path.expanduser(os.path.expandvars(path))

class Launcher:
    def __init__(self, argv=None):
        name = os.path.basename(sys.argv[0])

        if name.endswith('.py'):
            name = name[:-3]

        parser = argparse.ArgumentParser()
        parser.add_argument('--id', default=name,
                help='identity of launched game (default: %s)' % name)
        parser.add_argument('arguments', nargs='*',
                help='arguments for the launched game')
        self.args = parser.parse_args(argv)

        self.id = self.args.id
        self.keyfile = GLib.KeyFile()
        self.keyfile.load_from_file(os.path.join(GDP_DIR,
                    self.id + '.desktop'),
                GLib.KeyFileFlags.NONE)

        self.name = self.keyfile.get_string(GLib.KEY_FILE_DESKTOP_GROUP,
            GLib.KEY_FILE_DESKTOP_KEY_NAME)
        logger.debug('Name: %s', self.name)
        GLib.set_application_name(self.name)

        self.icon_name = self.keyfile.get_string(GLib.KEY_FILE_DESKTOP_GROUP,
            GLib.KEY_FILE_DESKTOP_KEY_ICON)
        logger.debug('Icon: %s', self.icon_name)

        if 'GDP_UNINSTALLED' in os.environ:
            import yaml
            self.data = yaml.load(open('%s/launch-%s.yaml' % (GDP_DIR, self.id),
                encoding='utf-8'), Loader=yaml.CSafeLoader)
        else:
            self.data = json.load(open('%s/launch-%s.json' % (GDP_DIR, self.id),
                encoding='utf-8'))

        self.binary_only = self.data['binary_only']
        logger.debug('Binary-only: %r', self.binary_only)
        self.required_files = list(map(expand, self.data['required_files']))
        logger.debug('Checked files: %r', sorted(self.required_files))

        self.dot_directory = expand(self.data.get('dot_directory',
                    '${XDG_DATA_HOME}/' + self.id))
        logger.debug('Dot directory: %s', self.dot_directory)

        self.base_directories = list(map(expand,
                        self.data.get('base_directories',
                            '/usr/lib/' + self.id)))
        logger.debug('Base directories: %r', self.base_directories)

        self.library_path = self.data.get('library_path', [])
        logger.debug('Library path: %r', self.library_path)

        self.working_directory = expand(self.data.get('working_directory',
                    None))
        logger.debug('Working directory: %s', self.working_directory)

        self.link_files = self.data.get('link_files', False)
        logger.debug('Link files: %r', self.link_files)

        if self.link_files:
            self.copy_files = self.data.get('copy_files', [])
            logger.debug('... but copy files matching: %r', self.copy_files)

        self.argv = list(map(expand, self.data.get('argv', False)))
        logger.debug('Arguments: %r', self.argv)

        self.exit_status = 1

    def main(self):
        have_all_data = True
        warning_stamp = os.path.join(self.dot_directory,
                'confirmed-binary-only.stamp')

        for p in self.base_directories:
            logger.debug('Searching: %s' % p)

        # sanity check: game engines often don't cope well with missing data
        for f in self.required_files:
            logger.debug('looking for %s', f)
            for p in self.base_directories:
                logger.debug('looking for %s in %s', f, p)
                if os.path.exists(os.path.join(p, f)):
                    logger.debug('found %s in %s', f, p)
                    break
            else:
                logger.warning('Data file is missing: %s' % f)
                have_all_data = False

        os.makedirs(self.dot_directory, exist_ok=True)

        if not have_all_data:
            gui = Gui(self)
            gui.text_view.get_buffer().set_text(
                    self.load_text('missing-data.txt', 'Data files missing'))
            gui.window.show_all()
            gui.check_box.hide()
            Gtk.main()
            sys.exit(72)    # EX_OSFILE

        elif self.binary_only and not os.path.exists(warning_stamp):
            self.exit_status = 77   # EX_NOPERM
            gui = Gui(self)
            gui.text_view.get_buffer().set_text(
                    self.load_text('confirm-binary-only.txt',
                        'Binary-only game, we cannot fix bugs or security '
                        'vulnerabilities!'))
            gui.check_box.bind_property('active', gui.ok_button, 'sensitive',
                    GObject.BindingFlags.SYNC_CREATE)
            gui.ok_button.connect('clicked', lambda _:
                    self._confirm_binary_only_cb(gui))

            gui.window.show_all()
            Gtk.main()
            sys.exit(self.exit_status)

        else:
            try:
                self.exec_game()
            except:
                gui = Gui(self)
                gui.text_view.get_buffer().set_text(traceback.format_exc())
                gui.ok_button.set_sensitive(False)
                gui.window.show_all()
                gui.check_box.hide()
                Gtk.main()
                sys.exit(self.exit_status)
            else:
                raise AssertionError('exec_game should never return')

    def flush(self):
        for f in (sys.stdout, sys.stderr):
            f.flush()

    def _confirm_binary_only_cb(self, gui):
        warning_stamp = os.path.join(self.dot_directory,
                'confirmed-binary-only.stamp')

        try:
            open(warning_stamp, 'a').close()
            self.exec_game()
        except:
            gui.text_view.get_buffer().set_text(traceback.format_exc())
            gui.check_box.hide()
            gui.ok_button.set_sensitive(False)

    def exec_game(self, _unused=None):
        self.exit_status = 69   # EX_UNAVAILABLE

        if self.link_files:
            logger.debug('linking in files')
            # prune dangling symbolic links
            if os.path.exists(self.dot_directory):
                logger.debug('checking %r for dangling symlinks',
                        self.dot_directory)
                for dirpath, dirnames, filenames in os.walk(self.dot_directory):
                    logger.debug('walking: %r %r %r', dirpath, dirnames,
                            filenames)
                    for filename in filenames:
                        logger.debug('checking whether %r is a dangling '
                                'symlink', filename)
                        f = os.path.join(dirpath, filename)

                        if not os.path.exists(f):
                            logger.info('Removing dangling symlink %s', f)
                            os.remove(f)

            logger.debug('%r', self.base_directories)

            # symlink in all base directories, highest priority first
            for p in self.base_directories:
                logger.debug('Searching for files to link in %s', p)
                for dirpath, dirnames, filenames in os.walk(p):
                    logger.debug('walking: %r %r %r', dirpath, dirnames,
                            filenames)
                    for filename in filenames:
                        logger.debug('ensuring that %s is symlinked in',
                                filename)

                        f = os.path.join(dirpath, filename)
                        logger.debug('%s', f)
                        assert f.startswith(p + '/')

                        target = os.path.join(self.dot_directory,
                                f[len(p) + 1:])
                        d = os.path.dirname(target)

                        if os.path.exists(target):
                            logger.debug('Already exists: %s', target)
                            continue

                        if os.path.lexists(target):
                            logger.info('Removing dangling symlink %s', target)
                            os.remove(target)

                        if d:
                            logger.info('Creating directory: %s', d)
                            os.makedirs(d, exist_ok=True)

                        for pattern in self.copy_files:
                            if fnmatch.fnmatch(f, pattern):
                                logger.info('Copying %s -> %s', f, target)
                                shutil.copyfile(f, target)
                                break
                        else:
                            logger.info('Symlinking %s -> %s', f, target)
                            os.symlink(f, target)
        else:
            logger.debug('not linking in files')

        if self.working_directory is not None:
            os.chdir(self.working_directory)

        self.flush()

        environ = os.environ.copy()

        library_path = self.library_path[:]

        if 'LD_LIBRARY_PATH' in environ:
            library_path.append(environ['LD_LIBRARY_PATH'])

        environ['LD_LIBRARY_PATH'] = ':'.join(library_path)

        os.execve(self.argv[0], self.argv + self.args.arguments, environ)

        raise AssertionError('os.execve should never return')

    def load_text(self, filename, placeholder):
        for f in ('%s.%s' % (self.id, filename), filename):
            try:
                path = os.path.join(GDP_DIR, f)
                text = open(path).read()
            except OSError:
                pass
            else:
                text = string.Template(text).safe_substitute(
                        distro=DISTRO,
                        name=self.name,
                        )
                # strip single \n
                text = text.replace('\n\n', '\r\r').replace('\n', ' ')
                text = text.replace('\r', '\n')
                return text
        else:
            return placeholder

class Gui:
    def __init__(self, launcher):
        self.window = Gtk.Window()
        self.window.set_default_size(600, 300)
        self.window.connect('delete-event', Gtk.main_quit)
        self.window.set_title(launcher.name)
        self.window.set_icon_name(launcher.icon_name)

        self.grid = Gtk.Grid(row_spacing=6, column_spacing=6,
                margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        self.window.add(self.grid)

        image = Gtk.Image.new_from_icon_name(launcher.icon_name,
                Gtk.IconSize.DIALOG)
        image.set_valign(Gtk.Align.START)
        self.grid.attach(image, 0, 0, 1, 1)

        self.text_view = Gtk.TextView(editable=False, cursor_visible=False,
            hexpand=True, vexpand=True, wrap_mode=Gtk.WrapMode.WORD,
            top_margin=6, left_margin=6, right_margin=6, bottom_margin=6)
        self.grid.attach(self.text_view, 1, 0, 1, 1)

        subgrid = Gtk.Grid(column_spacing=6, column_homogeneous=True,
                halign=Gtk.Align.END)

        cancel_button = Gtk.Button.new_with_label('Cancel')
        cancel_button.connect('clicked', Gtk.main_quit)
        subgrid.attach(cancel_button, 0, 0, 1, 1)

        self.check_box = Gtk.CheckButton.new_with_label("I'll be careful")
        self.check_box.set_hexpand(True)
        self.grid.attach(self.check_box, 0, 1, 2, 1)

        self.ok_button = Gtk.Button.new_with_label('Run')
        self.ok_button.set_sensitive(False)
        subgrid.attach(self.ok_button, 1, 0, 1, 1)

        self.grid.attach(subgrid, 0, 2, 2, 1)

        self.window.show_all()

if __name__ == '__main__':
    Launcher().main()
