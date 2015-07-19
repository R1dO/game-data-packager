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

from game_data_packager import (load_games, GameData, FillResult)
from game_data_packager.util import ascii_safe

games = []
genres = dict()
langs = dict()
langs['total'] = 0
for name, game in load_games().items():
    stats = dict()
    for package in game.packages.values():
        langs['total'] += 1
        if package.demo_for:
            stats['demos'] = stats.get('demos', 0) + 1
        else:
            langs[package.lang] = langs.get(package.lang, 0) + 1
            stats[package.lang] = stats.get(package.lang, 0) + 1

    # free-as-in-beer
    fullfree = True
    somefree = False
    for package in game.packages.values():
        if not package.demo_for:
            for m_lang in package.langs:
                if m_lang not in stats:
                    stats[m_lang] = '*'
        if GameData.fill_gaps(game, package=package,
                 log=False) is FillResult.IMPOSSIBLE:
             fullfree = False
        else:
             somefree = True

    genres[game.genre] = genres.get(game.genre, 0) + 1
    stats['genre'] = game.genre
    stats['shortname'] = name
    stats['longname'] = ascii_safe(game.longname, force=True)
    stats['total'] = len(game.packages)
    stats['missing_langs'] = game.missing_langs
    stats['fullfree'] = fullfree or name == 'dreamweb' #XXX
    stats['somefree'] = somefree
    stats['url_steam'] = game.url_steam
    stats['url_gog'] = game.url_gog
    stats['url_dotemu'] = game.url_dotemu
    stats['url_misc'] = game.url_misc
    for l in game.missing_langs:
        if l not in langs:
            langs[l] = 0
    games.append(stats)

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
html.write('<td>Demo</td><td>Steam</td><td>GOG.com</td><td>DotEmu</td><td>Misc.</td></tr>\n')

# BODY
last_genre = None
demos = 0
for game in games:
    html.write('<tr>\n')
    genre = game['genre']
    if genre != last_genre:
        html.write('<td rowspan=%i>%s</td>\n' % (genres[genre], genre))
        last_genre = genre
    html.write('  <td>%s</td>\n' % game['longname'])
    for lang in langs_order:
        count = game.get(lang,None)
        if lang in ('total', 'en') or count == '*':
            html.write('  <td bgcolor="lightgreen">%s</td>\n' % count)
        elif lang in game['missing_langs']:
            html.write('  <td bgcolor="orange">!</td>\n')
        elif count:
            html.write('  <td bgcolor="green">%s</td>\n' % count)
        else:
            html.write('  <td>&nbsp;</td>\n')

    if game['fullfree']:
        html.write('  <td colspan=5 align=center><b>freeload</b></td>\n')
    else:
        if 'demos' in game:
            demos += game['demos']
            html.write('  <td align=center><b>%i</b></td>\n' % game['demos'])
        elif game['somefree']:
            html.write('  <td align=center><b>X</b></td>\n')
        else:
            html.write('  <td>&nbsp;</td>\n')
        for url in (game['url_steam'], game['url_gog'], game['url_dotemu'], game['url_misc']):
            if url:
                html.write('  <td align=center><a href="%s"><b>X</b></a></td>\n' % url)
            else:
                html.write('  <td>&nbsp;</td>\n')
    html.write('</tr>\n')

# TOTAL
html.write('<tr><td colspan=2><b>Total</b></td>\n')
for lang in langs_order:
    html.write('  <td><b>%i</b></td>\n' % langs[lang])

html.write('  <td><b>%i</b></td>\n' % demos)

html.write('''
<td colspan=4>&nbsp;</td>
</tr>
</table>
<ul>
<li>! : language is missing</li>
<li>* : multi-lang support in a single package</li>
</ul>
</html>
'''
)

