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
# /usr/share/common-licenses/GPL-2.


# Online at http://users.teledisnet.be/ade15809/babel.html

from game_data_packager import load_games
from game_data_packager.util import ascii_safe

games = []
genres = dict()
langs = dict()
langs['total'] = 0
for name, game in load_games().items():
    stats = dict()
    for package in game.packages.values():
        lang = package.lang
        langs[lang] = langs.get(lang, 0) + 1
        langs['total'] += 1
        stats[lang] = stats.get(lang, 0) + 1

    for package in game.packages.values():
        for m_lang in getattr(package, 'langs', []):
            if m_lang not in stats:
                stats[m_lang] = '*'

    genres[game.genre] = genres.get(game.genre, 0) + 1
    stats['genre'] = game.genre
    stats['shortname'] = name
    stats['longname'] = ascii_safe(game.longname, force=True)
    stats['total'] = len(game.packages)
    games.append(stats)

if 'ru' not in langs:
    langs['ru'] = 0

missing = {
  'nomouth': ['ru'],
  'rtcw': ['de','es','it'],
  'waxworks': ['es','fr'],
}

games = sorted(games, key=lambda k: (k['genre'], k['shortname'], k['longname']))

langs_order = [k for k, v in sorted(langs.items(), key=lambda kv: (-kv[1], kv[0]))]

html = open('/home/tchet/Utilitaires/Homepage/babel.html', 'w', encoding='latin1')
html.write('''<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN" "http://www.w3.org/TR/html4/loose.dtd">
<html>
<head>
<title>Game-Data-Packager</title>
<meta http-equiv="Content-Type" content="text/html;charset=iso-8859-1">
</head>
<table border=1 cellspacing=0>
<tr>
<td colspan=2>&nbsp</td>
'''
)
for lang in langs_order:
    html.write('  <td><b>%s</b></td>\n' % lang)
html.write('</tr>\n')

# BODY
last_genre = None
for game in games:
    html.write('<tr>\n')
    genre = game['genre']
    if genre != last_genre:
        html.write('<td rowspan=%i>%s</td>\n' % (genres[genre], genre))
        last_genre = genre
    html.write('  <td>%s</td>\n' % game['longname'])
    for lang in langs_order:
        count = game.get(lang,None)
        if lang in ('total', 'en') or count in ('*', 'm'):
            html.write('  <td bgcolor="lightgreen">%s</td>\n' % count)
        elif lang in missing.get(game['shortname'],[]):
            assert not count
            html.write('  <td bgcolor="orange">!</td>\n')
        elif count:
            html.write('  <td bgcolor="green">%s</td>\n' % count)
        else:
            html.write('  <td>&nbsp;</td>\n')

    html.write('</tr>\n')

# TOTAL
html.write('<tr><td colspan=2><b>Total</b></td>\n')
for lang in langs_order:
    html.write('  <td><b>%s</b></td>\n' % langs[lang])

html.write('''
</tr>
</table>
<ul>
<li>! : language is missing</li>
<li>* : multi-lang support in a single package</li>
</ul>
</html>
'''
)

