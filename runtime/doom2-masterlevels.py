#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2015-2016 Alexandre Detiste <alexandre@detiste.be>
#           © 2015 Simon McVittie <smcv@debian.org>
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
# /usr/share/common-licenses/GPL-2

import os
import stat
import subprocess

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

CACODEMON = '/usr/share/pixmaps/doom2-masterlevels.png'

if os.path.isdir('/usr/share/doom'):
    DIR = '/usr/share/doom'
else:
    DIR = '/usr/share/games/doom'

if os.path.isfile('/etc/redhat-release'):
    depedencies = 'python3-gobject-base and gobject-introspection\n  (already pulled-in by this .rpm)'
    command = 'dnf install prboom-plus'
else:
    depedencies = 'python3-gi and gir1.2-gtk-3.0'
    command = 'apt-get install doom-engine python3-gi gir1.2-gtk-3.0'

requirements='''
--------------------------------------------------------

You need those to make use this launcher:
* the .wad files from DOOM 2 Master Levels
* some Doom game engine
* ''' + depedencies + '''

The free parts can be obtained this way:
  ''' + command + '''

The .wad files can be for example bought on Steam:
http://store.steampowered.com/app/9160/ or found
on "Doom 3: Resurrection of Evil" Xbox game disc.

The data then need to be put at the right location.
You can use game-data-packager(6) to automate this.

It will also automatically pick up the data downloaded
by a windows Steam instance running through Wine.
'''

# ValueError: Namespace Gtk not available
try:
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk, Pango
except (ImportError,ValueError):
    message = 'Python3 Gtk+ libraries not found!\n' + requirements
    if which('zenity'):
       subprocess.call(['zenity', '--error', '--title=Doom 2 Master Levels', '--text', message])
    elif which('kdialog'):
        subprocess.call(['kdialog', '--error', message, '--title=Doom 2 Master Levels'])
    elif which('xmessage'):
        subprocess.call(['xmessage', '-center', message])
    exit(message)

# wad : (warp, longname,  'http://doomwiki.org/wiki/' + url)
levels = {
    'attack.wad':   ( 1, 'Attack'                                 , 'MAP01:_Attack_(Master_Levels)'),
    'blacktwr.wad': (25, 'Black Tower'                            , 'MAP25:_Black_Tower_(Master_Levels)'),
    'bloodsea.wad': ( 7, 'Bloodsea Keep'                          , 'MAP07:_Bloodsea_Keep_(Master_Levels)'),
    'canyon.wad':   ( 1, 'Canyon'                                 , 'MAP01:_Canyon_(Master_Levels)'),
    'catwalk.wad':  ( 1, 'The Catwalk'                            , 'MAP01:_The_Catwalk_(Master_Levels)'),
    'combine.wad':  ( 1, 'The Combine'                            , 'MAP01:_The_Combine_(Master_Levels)'),
    'fistula.wad':  ( 1, 'The Fistula'                            , 'MAP01:_The_Fistula_(Master_Levels)'),
    'garrison.wad': ( 1, 'The Garrison'                           , 'MAP01:_The_Garrison_(Master_Levels)'),
    'geryon.wad':   ( 8, 'Geryon: 6th Canto of Inferno'           , 'MAP08:_Geryon_(Master_Levels)'),
    'mephisto.wad': ( 7, "Mephisto's Maosoleum"                   , "MAP07:_Mephisto%27s_Maosoleum_(Master_Levels)"),
    'manor.wad':    ( 1, 'Titan Manor'                            , 'MAP01:_Titan_Manor_(Master_Levels)'),
    'minos.wad':    ( 5, "Minos' Judgement: 4th Canto of Inferno" , "MAP05:_Minos%27_Judgement_(Master_Levels)"),
    'nessus.wad':   ( 7, 'Nessus: 5th Canto of Inferno'           , "MAP07:_Nessus_(Master_Levels)"),
    'paradox.wad':  ( 1, 'Paradox'                                , 'MAP01:_Paradox_(Master_Levels)'),
    'subspace.wad': ( 1, 'Subspace'                               , 'MAP01:_Subspace_(Master_Levels)'),
    'subterra.wad': ( 1, 'Subterra'                               , 'MAP01:_Subterra_(Master_Levels)'),
    'teeth.wad':    (31, 'The Express Elevator to Hell'           , 'MAP31:_The_Express_Elevator_to_Hell_-_teeth.wad_(Master_Levels)'),
    'teeth.wad*':   (32, 'Bad Dream'                              , 'MAP32:_Bad_Dream_-_teeth.wad_(Master_Levels)'),
    'ttrap.wad':    ( 1, 'Trapped on Titan'                       , 'MAP01:_Trapped_on_Titan_(Master_Levels)'),
    'vesperas.wad': ( 9, 'Vesperas: 7th Canto of Inferno'         , 'MAP09:_Vesperas_(Master_Levels)'),
    'virgil.wad':   ( 3, "Virgil's Lead: 3rd Canto of Inferno"    , "MAP03:_Virgil%27s_Lead_(Master_Levels)"),
}
description = dict()

class Launcher:
    def __init__(self):
        self.game = None
        self.warp = None
        self.difficulty = None
        self.engine = None

        self.window = Gtk.Window()
        self.window.set_default_size(1020, 650)
        if os.path.isfile(CACODEMON):
            self.window.set_icon_from_file(CACODEMON)
        self.window.connect("delete_event", Gtk.main_quit)

        grid = Gtk.Grid()
        grid.set_row_spacing(5)
        grid.set_column_spacing(5)
        self.window.add(grid)

        # level list
        games = Gtk.ListStore(str, int)
        for wad in sorted(levels.keys()):
            game = os.path.splitext(wad)[0]
            games.append([game, levels[wad][0] ])

        treeview = Gtk.TreeView(model=games)
        grid.attach(treeview, 0, 0, 1, 8)

        treeviewcolumn = Gtk.TreeViewColumn("Wad")
        treeview.append_column(treeviewcolumn)
        cellrenderertext = Gtk.CellRendererText()
        treeviewcolumn.pack_start(cellrenderertext, True)
        treeviewcolumn.add_attribute(cellrenderertext, "text", 0)

        treeviewcolumn = Gtk.TreeViewColumn("Map")
        treeview.append_column(treeviewcolumn)
        cellrenderertext = Gtk.CellRendererText()
        treeviewcolumn.pack_start(cellrenderertext, True)
        treeviewcolumn.add_attribute(cellrenderertext, "text", 1)

        treeview.connect("query-tooltip", self.tooltip_query)
        treeview.set_tooltip_column(0)
        treeview.connect("cursor-changed", self.select_game)

        # header
        label = Gtk.Label()
        label.set_markup("<span size='xx-large'>Doom II Master Levels</span>")
        grid.attach(label, 1, 0, 1, 1)

        logo = Gtk.Image()
        logo.set_from_file(CACODEMON)
        grid.attach(logo, 2, 0, 1, 1)

        # description
        scrolledwindow = Gtk.ScrolledWindow()
        scrolledwindow.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        grid.attach(scrolledwindow, 1, 1, 2, 1)

        self.textbuffer = Gtk.TextBuffer()
        self.textbuffer.set_text('Please select a map from the list on the left')

        textview = Gtk.TextView(buffer=self.textbuffer)
        textview.set_vexpand(True)
        textview.set_hexpand(True)
        textview.set_property('editable', False)
        textview.modify_font(Pango.FontDescription('Monospace 11'))
        scrolledwindow.add(textview)

        self.doomwiki = Gtk.LinkButton("http://doomwiki.org/wiki/Master_Levels_for_Doom_II",
                                  label="http://doomwiki.org/wiki/Master_Levels_for_Doom_II")
        grid.attach(self.doomwiki, 1, 2, 2, 1)

        # difficulty
        difflabel = Gtk.Label("Choose your difficulty")
        grid.attach(difflabel, 1, 3, 1, 1)

        diffgrid = Gtk.Grid()
        diffradio = Gtk.RadioButton(group=None, label="1)  I'm too young to die")
        diffgrid.attach(diffradio, 0, 0, 1, 1)
        diffradio.connect('toggled', self.select_difficulty)
        for diff in ["2)  Hey, Not too Rough",
                     "3)  Hurt me plenty",
                     "4)  Ultra Violence",
                     "5)  Nightmare!"]:
            radiobutton = Gtk.RadioButton(group=diffradio, label=diff)
            radiobutton.connect('toggled', self.select_difficulty)
            if diff[0] == '3':
               radiobutton.set_active(True)
            diffgrid.attach(radiobutton, 0, int(diff[0]), 1, 1)
        grid.attach(diffgrid, 1, 4, 1, 1)

        # engine
        label = Gtk.Label("Choose your engine")
        grid.attach(label, 2, 3, 1, 1)
        radiogrid = Gtk.Grid()
        radiobuttonDefault = Gtk.RadioButton(group=None, label="n/a")
        radiobuttonDefault.connect('toggled', self.select_engine)
        radiogrid.attach(radiobuttonDefault, 0, 0, 1, 1)

        default = None
        alternatives = []
        if os.path.islink('/etc/alternatives/doom'):
            # on Debian
            default = os.readlink('/etc/alternatives/doom')
            if default == '/usr/games/doomsday-compat':
                default = '/usr/games/doomsday'

            proc = subprocess.check_output(['update-alternatives', '--list', 'doom'],
                                             universal_newlines=True)
            for alternative in proc.splitlines():
                if alternative == '/usr/games/doomsday-compat':
                    alternative = '/usr/games/doomsday'
                if alternative != default:
                    alternatives.append(alternative)
        else:
            # not on Debian
            for alternative in ('prboom-plus', 'prboom', 'chocolate-doom'):
                if which(alternative):
                    if not default:
                        default = alternative
                    else:
                        alternatives.append(alternative)

        if default:
            radiobuttonDefault.set_label("%s (default)" % default)
            self.select_engine(radiobuttonDefault)
            if default.split('/')[-1] == 'chocolate-doom' and which('chocolate-doom-setup'):
                self.button_conf = Gtk.Button(label="Configure")
                radiogrid.attach(self.button_conf,1, 0, 1, 1)
                self.button_conf.connect("clicked", self.chocolate_setup)

            i = 1
            for alternative in alternatives:
                radiobutton = Gtk.RadioButton(group=radiobuttonDefault, label=alternative)
                radiobutton.connect('toggled', self.select_engine)
                i += 1
                radiogrid.attach(radiobutton, 0, i, 1, 1)
                if alternative.split('/')[-1] == 'chocolate-doom' and which('chocolate-doom-setup'):
                    self.button_conf = Gtk.Button(label="Configure")
                    radiogrid.attach(self.button_conf,1, i, 1, 1)
                    self.button_conf.connect("clicked", self.chocolate_setup)
                if os.path.isfile('/etc/debian_version'):
                    radiogrid.set_tooltip_text('Default can be changed with update-alternatives(8)')

        grid.attach(radiogrid, 2, 4, 1, 1)

        # Run !
        self.button_exec = Gtk.Button(label="Run")
        self.button_exec.set_sensitive(False)
        grid.attach(self.button_exec, 1, 6, 1, 1)
        self.button_exec.connect("clicked", self.run_game)

        button_quit = Gtk.Button(label="Exit")
        grid.attach(button_quit, 2, 6, 1, 1)
        button_quit.connect("clicked", Gtk.main_quit)

        self.window.show_all()

    def tooltip_query(self, treeview, x, y, mode, tooltip):
        path = treeview.get_path_at_pos(x, y - 30) # FIXME
        if path:
            treepath, column = path[:2]
            model = treeview.get_model()
            iter = model.get_iter(treepath)
            game, warp = model[iter]
            wad = game + '.wad'
            if game == 'teeth' and warp == 32: wad += '*'
            tooltip.set_text(levels[wad][1])
        return True

    def select_game(self, treeview):
        self.button_exec.set_sensitive(True)
        (model, pathlist) = treeview.get_selection().get_selected_rows()
        for path in pathlist:
            tree_iter = model.get_iter(path)
            self.game, self.warp = model[tree_iter]
            self.textbuffer.set_text(description[self.game])
            wad = self.game + '.wad'
            if self.game == 'teeth' and self.warp == 32:
                wad += '*'
            url = 'http://doomwiki.org/wiki/' + levels[wad][2]
            self.doomwiki.set_uri(url)
            self.doomwiki.set_label(url)

    def select_difficulty(self, radio):
        self.difficulty = int(radio.get_label()[0])

    def select_engine(self, radio):
        self.engine = [radio.get_label().split(' ')[0]]
        if self.engine == ['/usr/games/doomsday']:
            self.engine.append('-game')
            self.engine.append('doom2')
        if self.engine == ['chocolate-doom'] and DIR == '/usr/share/doom':
            self.engine.append('-iwad')
            self.engine.append('/usr/share/doom/doom2.wad')

    def run_game(self, event):
        subprocess.call(self.engine +
            ['-file', '%s/%s.wad' % (DIR, self.game),
            '-warp', '%d' % self.warp,
            '-skill', '%d' % self.difficulty])

    def chocolate_setup(self, event):
        subprocess.call('chocolate-doom-setup')

    def main(self):
        if not self.engine:
            message = 'No DOOM engine found!\n' + requirements
            md = Gtk.MessageDialog(self.window, 0, Gtk.MessageType.WARNING,
                                       Gtk.ButtonsType.OK, message)
            md.run()
            exit(message)
        for level in levels.keys():
            level = os.path.splitext(level)[0]
            fullpath = DIR + '/%s.wad' % level
            if not os.path.isfile(fullpath):
                print('\n')
                message = fullpath + " is missing !\n" + requirements
                md = Gtk.MessageDialog(self.window, 0, Gtk.MessageType.WARNING,
                                       Gtk.ButtonsType.OK, message)
                md.run()
                exit(message)
            txt = '/usr/share/doc/doom2-masterlevels-wad/%s.txt' % level
            try:
                 with open(txt, 'r', encoding='latin1') as f:
                     description[level] = f.read()
            except (PermissionError, FileNotFoundError):
                description[level] = "failed to read " + txt

        Gtk.main()

if __name__ == "__main__":
    launcher = Launcher()
    launcher.main()
