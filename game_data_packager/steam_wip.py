#!/usr/bin/python3
# vim:set fenc=utf-8:
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

import os
import argparse
import logging

from . import GameData,load_games,rm_rf
from .steam import parse_acf,owned_steam_games
from .util import is_installed

logging.basicConfig()
logger = logging.getLogger('steam.py')

if os.environ.get('DEBUG'):
    logging.getLogger().setLevel(logging.DEBUG)
else:
    logging.getLogger().setLevel(logging.INFO)


games_obj = load_games(None)

STEAMDIRS = ['~/.steam',
             '~/.wine/drive_c/Program Files/Steam',
             '~/.PlayOnLinux/wineprefix/Steam/drive_c/Program Files/Steam']

games = []

for shortname, gamedata in games_obj.items():
    logger.debug('G: %s: %s' % (shortname, str(gamedata.steam)))
    for package in gamedata.packages.values():
        logger.debug('P: %s: %s' % (package.name, str(package.steam)))
        if package.type == 'demo':
            continue
        if 'path' in package.steam:
            steam_suffix = package.steam['path']
            steam_id     = package.steam['id']
        elif 'path' in gamedata.steam:
            steam_suffix = gamedata.steam['path']
            steam_id     = gamedata.steam['id']
        else:
            continue

        type_order = { 'full' : 1,
                       'expansion' : 2,
                       'demo' : 3
                     }.get(package.type)

        # FIXME: can't get it to work with iter_steam_paths()
        # TypeError: 'GameDataPackage' object is not iterable
        for dir in STEAMDIRS:
            check_path = os.path.expanduser(dir) + '/SteamApps/' + steam_suffix
            if os.path.isdir(check_path):
                steam_path = check_path
                steam_date = os.stat(steam_path).st_mtime
                break
        else:
            steam_path = None
            steam_date = 0

        games.append({
                      'shortname' : shortname,
                      'type' : package.type,
                      'type_order' : type_order,
                      'package': package.name,
                      'installed': is_installed(package.name),
                      'longname': package.longname if package.longname else gamedata.longname,
                      'steam_path': steam_path,
                      'steam_id': steam_id,
                      'steam_date': steam_date,
                      })

games = sorted(games, key=lambda k: (k['shortname'], k['type_order'], k['longname']))

def show(games,args):
    print('steam packages supported:')
    printed = []
    for game in games:
        if game['shortname'] not in printed:
            print('\t%16s\t%s' % (game['shortname'], game['longname']))
            printed.append(game['shortname'])
        else:
            print('\t\t\t\t%s' % game['longname'])

def install(todos,args):
    global games_obj

    print('building %s:' % todos)
    if args.dryrun:
        exit(0)

    all_debs = set()
    for todo in todos:
        print(todo)
        with games_obj[todo] as game:
            game.look_for_files()
            packages = set(game.packages.values())
            ready = game.prepare_packages(packages)
            debs = game.build_packages(ready, destination='.', compress=True)
            all_debs = all_debs.union(debs)
            rm_rf(os.path.join(game.get_workdir(), 'tmp'))
            for deb in debs:
                print('generated "%s"' % os.path.abspath(deb))

    assert all_debs, 'at least a .deb should have been generated'

    # call su once
    GameData.install_packages(games_obj, all_debs)

def last(games,args):
    games = sorted(games, key=lambda k: (-k['steam_date']))
    for game in games:
        logger.debug("%s: %s" % (game['package'], game['steam_date']))
        if not game['installed'] and game['steam_path']:
             install(set([game['shortname']]),args)
             exit(0)
    exit('No new game to install')


def new(games,args):
    todo = set()
    for game in games:
        if game['steam_path'] and not game['installed']:
            todo.add(game['shortname'])
    if todo:
        install(todo,args)
    else:
        print('No new game to install')

def all(games,args):
    todo = set()
    for game in games:
        if game['steam_path']:
            todo.add(game['shortname'])
    if todo:
        install(todo,args)
    else:
        exit("Couldn't find any game to install")

def parse(games,args):
    acf = []
    for dir in STEAMDIRS:
        apps = os.path.expanduser(dir) + '/SteamApps'
        if os.path.isdir(apps):
            for acf_struct in parse_acf(apps):
                acf.append(acf_struct)

    acf = sorted(acf, key=lambda k: (k['name']))
    for record in acf:
        print(record)

def owned(games,args):
    owned = {}
    for appid, name in owned_steam_games(os.environ.get('STEAM_ID', 'sir_dregan')):
        for supported in games:
             if int(supported['steam_id']) == int(appid):
                 owned[appid] = name
    for k in sorted(owned):
        print("%-9s %s" % (k, owned[k]))

args_parser = argparse.ArgumentParser(description='manage your Steam collection with game-data-packager')

group = args_parser.add_mutually_exclusive_group()

group.add_argument('-s', '--show', dest='action', action='store_const', const='show',
                    help='Show games supported')
group.add_argument('-l', '--last', dest='action', action='store_const', const='last',
                    help='Package newest game')
group.add_argument('-n', '--new', dest='action', action='store_const', const='new',
                    help='Package all new games')
group.add_argument('-a', '--all', dest='action', action='store_const', const='all',
                    help='Package all games')
group.add_argument('-p', '--parse', dest='action', action='store_const', const='parse',
                    help="Parse Steam manifest data")
group.add_argument('-o', '--owned', dest='action', action='store_const', const='owned',
                    help="List the games you own, set your STEAM_ID first")

args_parser.add_argument('-d', '--dry-run', dest='dryrun', action='store_true',
                    help="Dry-run, don't really package anything")

args = args_parser.parse_args()

if not getattr(args, 'action', None):
    args_parser.print_help()
    print()

action = {'show': show,
          'last': last,
          'new': new,
          'all': all,
          'parse': parse,
          'owned': owned,
         }.get(args.action, show)

action(games,args)
