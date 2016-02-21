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


# Online at http://pkg-games.alioth.debian.org/game-data/

from game_data_packager import (load_games)
from game_data_packager.build import (FillResult)

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
    if game.copyright:
        year = game.copyright[2:6]
    else:
        year = None
    for package in game.packages.values():
        if not year and package.copyright:
            year = package.copyright[2:6]
        if not package.demo_for:
            for m_lang in package.langs:
                if m_lang not in stats:
                    stats[m_lang] = '*'
        with game.construct_task() as task:
            if task.fill_gaps(package=package,
                     log=False) is FillResult.IMPOSSIBLE:
                if not package.better_versions:
                    fullfree = False
            else:
                 somefree = True
    genre = game.genre or 'Unknown'
    genres[genre] = genres.get(genre, 0) + 1
    stats['genre'] = genre
    if game.franchise:
        stats['sort_key'] = game.franchise.lower() + ' ' + year
    else:
        stats['sort_key'] = game.shortname
    stats['shortname'] = name
    stats['longname'] = game.longname
    stats['url_wiki'] = game.wikibase + (game.wiki or '')
    stats['total'] = len(game.packages)
    stats['missing_langs'] = game.missing_langs
    stats['fullfree'] = fullfree
    stats['somefree'] = somefree
    stats['url_wikipedia'] = game.wikipedia
    stats['url_steam'] = game.url_steam
    stats['url_gog'] = game.url_gog
    stats['url_dotemu'] = game.url_dotemu
    stats['url_misc'] = game.url_misc
    for l in game.missing_langs:
        if l not in langs:
            langs[l] = 0
    games.append(stats)

# add missing games from list
with open('debian/TODO', 'r', encoding='utf8') as missing:
    for line in missing:
        if line[0:2] == '##':
            break
    genre = None
    for line in missing:
        line = line.strip()
        if line[0:1] == '#':
            genre = line[1:len(line)].strip()
        elif line == '':
            pass
        else:
            stats = {'todo': True}
            genres[genre] = genres.get(genre, 0) + 1
            stats['genre'] = genre
            shortname = ''
            for char in line.lower():
                if 'a' <= char <= 'z' or '0' <= char <= '9':
                   shortname += char
            stats['sort_key'] = shortname
            if '#' not in line:
                stats['longname'] = line
            else:
                longname, bug = line.split('#')
                if ' ' in bug:
                    bug, remainder = bug.split(maxsplit=1)
                else:
                    remainder = ''
                stats['longname'] = ('%s <a href="https://bugs.debian.org/'
                                   'cgi-bin/bugreport.cgi?bug=%s">#%s</a> %s'
                                   % (longname, bug, bug, remainder))
            games.append(stats)

games = sorted(games, key=lambda k: (k['genre'], k['sort_key']))

langs_order = [k for k, v in sorted(langs.items(), key=lambda kv: (-kv[1], kv[0]))]

html = open('out/index.html', 'w', encoding='utf8')
html.write('''<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN" "http://www.w3.org/TR/html4/loose.dtd">
<html>
<head>
<title>Game-Data-Packager</title>
<meta http-equiv="Content-Type" content="text/html;charset=utf-8">
<meta name="generator" content="http://anonscm.debian.org/cgit/pkg-games/game-data-packager.git/tree/tools/babel.py">
<style type="text/css">
'''
)

for lang in langs_order:
    if lang in ('total', 'en'):
        continue
    html.write('  #check-%s:checked ~ * .%s' % (lang, lang))
    if lang != langs_order[-1]:
        html.write(',\n')

html.write(''' {
  background-color: yellow;
}
</style>
</head>

<body>
<h1>Debian Games Team</h1>
<img src="../proposed-logo.png" height="64" width="64" alt="Debian Games Team logo">
<h2>List of games supported by <code>game-data-packager</code> in git</h2>
This is an automaticaly generated list of games supported by then upcoming release.<br>
Please visit the <a href="http://wiki.debian.org/Games/GameDataPackager">Wiki</a>
for more general information.
<br><br>
'''
)
for lang in langs_order:
    if lang in ('total', 'en'):
        continue
    html.write('<!--label for=check-%s-->%s<!--/label--><input id=check-%s type=checkbox>&nbsp;&nbsp;' % (lang, lang, lang))

html.write('''<table border=1 cellspacing=0>
<tr>
<td colspan=2>&nbsp</td>
<td>WP</td>
<td>yaml</td>
'''
)
for lang in langs_order:
    html.write('  <td><b>%s</b></td>\n' % lang)
html.write('''<td>Demo</td>
<td><a href="https://steamcommunity.com/groups/debian_gdp#curation">Steam</a></td>
<td><a href="https://www.gog.com/mix/games_supported_by_debians_gamedatapackager">GOG.com</a></td>
<td>DotEmu</td>
<td>Misc.</td></tr>
''')

# BODY
last_genre = None
demos = 0
wikipedia = set()
for game in games:
    html.write('<tr>\n')
    genre = game['genre']
    if genre != last_genre:
        html.write('<td rowspan=%i>%s</td>\n' % (genres[genre], genre))
        last_genre = genre
    highlight = [l for l in langs_order if l not in ('total', 'en') and l in game]
    highlight += game.get('missing_langs', [])
    if highlight:
        css = ' class="%s"' % ' '.join(highlight)
    else:
        css = ''
    html.write('  <td%s>' % css)
    if game.get('url_wiki', False):
        html.write('<a href="%s">%s</a>' % (game['url_wiki'], game['longname']))
    else:
        html.write(game['longname'])
    html.write('</td>')

    wp = game.get('url_wikipedia')
    if wp in wikipedia:
        html.write('<td><b>&Prime;</b></td>')
    elif wp:
        html.write('<td><a href="%s"><b>W</b></a></td>' % wp)
        wikipedia.add(wp)
    else:
        html.write('<td>&nbsp;</td>')

    if 'todo' in game:
        html.write('<td>&nbsp;</td>')
    else:
        html.write('<td><a href="http://anonscm.debian.org/cgit/pkg-games/game-data-packager.git/tree/data/%s.yaml">'
                   '<img src="gear.png" alt="gear icon"></a></td>' % game['shortname'])

    for lang in langs_order:
        count = game.get(lang,None)
        if lang in ('total', 'en') and count == None:
            html.write('  <td bgcolor="orange">!</td>\n')
        elif lang in ('total', 'en') or count == '*':
            html.write('  <td bgcolor="lightgreen">%s</td>\n' % count)
        elif 'missing_langs' in game and lang in game['missing_langs']:
            html.write('  <td bgcolor="orange">!</td>\n')
        elif count:
            html.write('  <td bgcolor="green">%s</td>\n' % count)
        else:
            html.write('  <td>&nbsp;</td>\n')

    if game.get('fullfree', False):
        html.write('  <td colspan=5 align=center%s><b>freeload</b></td>\n' % css)
    else:
        if 'demos' in game:
            demos += game['demos']
            html.write('  <td align=center><b>%i</b></td>\n' % game['demos'])
        elif game.get('somefree', False):
            html.write('  <td align=center><b>X</b></td>\n')
        else:
            html.write('  <td>&nbsp;</td>\n')
        for url in ('url_steam', 'url_gog', 'url_dotemu', 'url_misc'):
            if url in game and game[url]:
                html.write('  <td align=center%s><a href="%s"><b>X</b></a></td>\n' % (css, game[url]))
            else:
                html.write('  <td%s>&nbsp;</td>\n' % css)
    html.write('</tr>\n')

# TOTAL
html.write('<tr><td colspan=4><b>Total</b></td>\n')
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
</body>
</html>
'''
)

html.close()
