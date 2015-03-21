#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2015 Alexandre Detiste <alexandre@detiste.be>
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

import gi
import os
import subprocess

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Pango

map = None
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

window = Gtk.Window()
window.set_default_size(1020, 800)
window.connect("destroy", lambda q: Gtk.main_quit())

grid = Gtk.Grid()
grid.set_row_spacing(5)
grid.set_column_spacing(5)
window.add(grid)

# level list
games = Gtk.ListStore(str, int)
description = dict()
for wad in sorted(levels.keys()):
     game = os.path.splitext(os.path.basename(wad))[0]
     games.append([game, levels[wad][0] ])
     txt = '/usr/share/doc/doom2-masterlevels-wad/%s.txt' % game
     try:
         with open(txt, 'r', encoding='latin1') as f:
             description[game] = f.read()
     except (PermissionError, FileNotFoundError):
         description[game] = "failed to read " + txt

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

def tooltip_query(treeview, x, y, mode, tooltip):
    path = treeview.get_path_at_pos(x, y - 30) # FIXME
    if path:
       treepath, column = path[:2]
       model = treeview.get_model()
       iter = model.get_iter(treepath)
       tooltip.set_text(levels[ model[iter][0] + '.wad' ][1])
    return True

treeview.connect("query-tooltip", tooltip_query)
treeview.set_tooltip_column(0)


# header
label = Gtk.Label()
label.set_markup("<span size='xx-large'>Doom II Master Levels</span>")
grid.attach(label, 1, 0, 1, 1)

logo = Gtk.Image()
logo.set_from_file('/usr/share/pixmaps/doom2.png')
grid.attach(logo, 2, 0, 1, 1)

# description
scrolledwindow = Gtk.ScrolledWindow()
scrolledwindow.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
grid.attach(scrolledwindow, 1, 1, 2, 1)

textbuffer = Gtk.TextBuffer()
textbuffer.set_text('Please select a map from the list on the left')

textview = Gtk.TextView(buffer=textbuffer)
textview.set_vexpand(True)
textview.set_hexpand(True)
textview.set_property('editable', False)
textview.modify_font(Pango.FontDescription('Monospace 11'))
scrolledwindow.add(textview)

doomwiki = Gtk.LinkButton("http://doomwiki.org/wiki/Master_Levels_for_Doom_II",
                          label="http://doomwiki.org/wiki/Master_Levels_for_Doom_II")
grid.attach(doomwiki, 1, 2, 2, 1)

# difficulty
difflabel = Gtk.Label("Choose your difficulty")
grid.attach(difflabel, 1, 3, 2, 1)

diffgrid = Gtk.Grid()
diffradio = Gtk.RadioButton(group=None, label="1)  I'm too young to die")
diffgrid.attach(diffradio, 0, 0, 1, 1)
for diff in ["2)  Hey, Not too Rough",
             "3)  Hurt me plenty",
             "4)  Ultra Violence",
             "5)  Nightmare!"]:
    radiobutton = Gtk.RadioButton(group=diffradio, label=diff)
    if diff[0] == '3':
        radiobutton.set_active(True)
    diffgrid.attach(radiobutton, 0, int(diff[0]), 1, 1)
grid.attach(diffgrid, 1, 4, 2, 1)

# engine
label = Gtk.Label("Choose your engine")
grid.attach(label, 1, 4, 2, 1)
radiogrid = Gtk.Grid()
default = os.readlink('/etc/alternatives/doom')
radiobuttonDefault = Gtk.RadioButton(group=None, label="%s (default)" % default)
radiogrid.attach(radiobuttonDefault, 0, 0, 1, 1)
i = 1
proc = subprocess.Popen(['update-alternatives', '--list', 'doom'], stdout=subprocess.PIPE, universal_newlines=True)

for alternative in proc.stdout:
    alternative = alternative.strip()
    if alternative == default:
        continue
    radiobutton = Gtk.RadioButton(group=radiobuttonDefault, label=alternative)
    i += 1
    radiogrid.attach(radiobutton, 0, i, i, 1)
grid.attach(radiogrid, 1, 5, 2, 1)


# Run !
button1 = Gtk.Button(label="Run")
grid.attach(button1, 1, 6, 1, 1)
button2 = Gtk.Button(label="Exit")
grid.attach(button2, 2, 6, 1, 1)

def select_game(event):
    global game, map
    (model, pathlist) = treeview.get_selection().get_selected_rows()
    for path in pathlist:
        tree_iter = model.get_iter(path)
        game = model.get_value(tree_iter,0)
        map = model.get_value(tree_iter,1)
        textbuffer.set_text(description[game])
        url = 'http://doomwiki.org/wiki/' + levels[game + '.wad'][2]
        doomwiki.set_uri(url)
        doomwiki.set_label(url)

def run_game(event):
    for button in diffradio.get_group():
        if button.get_active():
            difficulty = button.get_label()[0]
            break
    for button in radiobuttonDefault.get_group():
        if button.get_active():
            engine = button.get_label().split(' ')[0]
            break
    if 'doomsday' in engine:
        engine = 'doomsday -game doom2'
    if map:
        os.system('%s -file /usr/share/games/doom/%s.wad -warp %s -skill %s' % (engine, game, map, difficulty))

treeview.connect("cursor-changed", select_game)
button1.connect("clicked", run_game)
button2.connect("clicked", Gtk.main_quit)

window.show_all()

Gtk.main()
