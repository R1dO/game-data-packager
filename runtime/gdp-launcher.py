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

import fnmatch
import logging
import os
import traceback

import gi

gi.require_version('Gtk', '3.0')

from gi.repository import (GLib, GObject)
from gi.repository import Gtk

from gdp_launcher_base import (
        Launcher,
        RUNTIME_BUILT,
        )

logger = logging.getLogger('game-data-packager.launcher')

class IniEditor:
    def __init__(self, edits):
        self.lines = []
        self.edits = edits
        self.__section = None
        self.__section_lines = []
        self.__sections = set()

    def load(self, reader):
        # Simple INI parser. Not using ConfigParser because Unreal
        # uses duplicate keys within sections, and we want to preserve
        # comments, blank lines etc.
        self.__section = None
        self.__section_lines = []
        self.__sections = set()

        for line in reader:
            line = line.rstrip('\r\n')

            if line.startswith('[') and line.endswith(']'):
                self.__end_section()
                self.__section = line[1:-1]

            self.__section_lines.append(line)

        self.__end_section()

        for edit in self.edits:
            if edit['section'] not in self.__sections:
                self.__section = edit['section']
                self.__section_lines = ['[%s]' % edit['section']]
                self.__end_section()

    def __end_section(self):
        self.__sections.add(self.__section)

        for edit in self.edits:
            if edit['section'] != self.__section:
                continue

            logger.debug('editing %s', self.__section)
            extra_lines = []

            for k, v in sorted(edit.get('replace_key', {}).items()):
                logger.debug('replacing %s with %s', k, v)
                self.__section_lines = [l for l in self.__section_lines
                        if not l.startswith(k + '=')]
                extra_lines.append('%s=%s' % (k, v))

            for pattern in sorted(edit.get('delete_matched', [])):
                logger.debug('deleting lines matching %s', pattern)
                self.__section_lines = [l for l in self.__section_lines
                        if not fnmatch.fnmatchcase(l, pattern)]

            for pattern in edit.get('comment_out_matched', []):
                logger.debug('commenting out lines matching %s', pattern)
                for i in range(len(self.__section_lines)):
                    if fnmatch.fnmatchcase(self.__section_lines[i], pattern):
                        self.__section_lines[i] = ';' + self.__section_lines[i]
                        self.__section_lines.insert(i, '; ' +
                                edit['comment_out_reason'])

            for append in edit.get('append_unique', []):
                logger.debug('appending unique line %s', append)
                for line in self.__section_lines:
                    if line == append:
                        break
                else:
                    extra_lines.append(append)

            i = len(self.__section_lines) - 1

            while i >= 0:
                if self.__section_lines[i]:
                    # _s_l[i] is the last non-empty line, insert after it
                    self.__section_lines[i + 1:i + 1] = extra_lines
                    break
                i -= 1
            else:
                # no non-empty lines, insert after the section-opening heading
                self.__section_lines[1:1] = extra_lines

        self.lines.extend(self.__section_lines)
        self.__section_lines = []
        self.__section = None

    def save(self, writer):
        for line in self.lines:
            print(line, file=writer)

class FullLauncher(Launcher):
    def set_id(self):
        self.keyfile = GLib.KeyFile()
        desktop = os.path.join(RUNTIME_BUILT, self.id + '.desktop')
        if os.path.exists(desktop):
            self.keyfile.load_from_file(desktop, GLib.KeyFileFlags.NONE)
        else:
            self.keyfile.load_from_data_dirs(
                    'applications/%s.desktop' % self.id,
                    GLib.KeyFileFlags.NONE)

        self.name = self.keyfile.get_string(GLib.KEY_FILE_DESKTOP_GROUP,
            GLib.KEY_FILE_DESKTOP_KEY_NAME)
        logger.debug('Name: %s', self.name)
        GLib.set_application_name(self.name)

        self.icon_name = self.keyfile.get_string(GLib.KEY_FILE_DESKTOP_GROUP,
            GLib.KEY_FILE_DESKTOP_KEY_ICON)
        logger.debug('Icon: %s', self.icon_name)

        self.expansion_name = self.args.expansion

        try:
            override_id = self.keyfile.get_string(GLib.KEY_FILE_DESKTOP_GROUP,
                'X-GameDataPackager-ExpansionFor')
        except GLib.Error:
            pass
        else:
            if self.expansion_name is None:
                self.expansion_name = self.id

            if self.expansion_name.startswith(override_id + '-'):
                self.expansion_name = self.expansion_name[len(override_id) + 1:]

            self.id = override_id

    def exec_game(self, _unused=None):
        # Edit before copying, so that we can detect whether this is
        # the first run or not
        for ini, details in self.data.get('edit_unreal_ini', {}).items():
            assert self.dot_directory is not None
            target = os.path.join(self.dot_directory, ini)
            encoding = details.get('encoding', 'windows-1252')

            if os.path.exists(target):
                first_time = False
                try:
                    reader = open(target, encoding='utf-16')
                    reader.readline()
                except:
                    reader = open(target, encoding=encoding)
                else:
                    reader.seek(0)
            else:
                first_time = True

                if os.path.lexists(target):
                    logger.info('Removing dangling symlink %s', target)
                    os.remove(target)

                for base in self.base_directories:
                    source = os.path.join(base, ini)

                    if os.path.exists(source):
                        try:
                            reader = open(source, encoding='utf-16')
                            reader.readline()
                        except:
                            reader = open(source, encoding=encoding)
                        else:
                            reader.seek(0)
                        break
                else:
                    raise AssertionError('Required file %s not found', ini)

            if first_time:
                edits = details.get('once', []) + details.get('always', [])
            else:
                edits = details.get('always', [])

            logger.debug('%s', edits)
            editor = IniEditor(edits)

            with reader:
                editor.load(reader)

            d = os.path.dirname(target)

            if d:
                logger.info('Creating directory: %s', d)
                os.makedirs(d, exist_ok=True)

            with open(target, 'w', encoding=encoding,
                    newline=details.get('newline', '\n')) as writer:
                editor.save(writer)

        super(FullLauncher, self).exec_game()

    def write_confirm_binary_only_stamp(self):
        open(self.warning_stamp, 'a').close()

    def __init__(self):
        super(FullLauncher, self).__init__()

        self.window = Gtk.Window()
        self.window.set_default_size(600, 300)
        self.window.connect('delete-event', Gtk.main_quit)
        self.window.set_title(self.name)
        self.window.set_icon_name(self.icon_name)

        self.grid = Gtk.Grid(row_spacing=6, column_spacing=6,
                margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        self.window.add(self.grid)

        image = Gtk.Image.new_from_icon_name(self.icon_name,
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

    def run_error(self, message):
        self.show_error(message)
        Gtk.main()

    def show_error(self, message):
        self.text_view.get_buffer().set_text(message)
        self.ok_button.set_sensitive(False)
        self.window.show_all()
        self.check_box.hide()

    def run_confirm_binary_only(self):
        self.text_view.get_buffer().set_text(
                self.load_text('confirm-binary-only.txt',
                    'Binary-only game, we cannot fix bugs or security '
                    'vulnerabilities!'))
        self.check_box.bind_property('active', self.ok_button, 'sensitive',
                GObject.BindingFlags.SYNC_CREATE)
        self.ok_button.connect('clicked',
                lambda _: self.__confirm_binary_only_cb())
        self.window.show_all()
        Gtk.main()

    def __confirm_binary_only_cb(self):
        try:
            self.write_confirm_binary_only_stamp()
            self.exec_game()
        except:
            self.show_error(traceback.format_exc())

if __name__ == '__main__':
    logging.basicConfig()
    FullLauncher().main()

