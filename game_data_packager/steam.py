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

import glob
import logging
import os
import tempfile
import xml.etree.ElementTree
import urllib.request

from .build import (BinaryExecutablesNotAllowed,
        DownloadsFailed,
        NoPackagesPossible)
from .util import (AGENT,
        PACKAGE_CACHE,
        ascii_safe,
        install_packages,
        lang_score,
        rm_rf)

logger = logging.getLogger('game-data-packager.steam')

def parse_acf(path):
    for manifest in glob.glob(path + '/*.acf'):
        with open(manifest) as data:
            # the .acf files are not really JSON files
            level = 0
            acf_struct = {}
            for line in data.readlines():
                if line.strip() == '{':
                   level += 1
                elif line.strip() == '}':
                   level -= 1
                elif level != 1:
                   continue
                elif '"\t\t"' in line:
                   key , value = line.split('\t\t')
                   key = key.strip().strip('"')
                   value = value.strip().strip('"')
                   if key in ('appid', 'name', 'installdir'):
                       acf_struct[key] = value
            if 'name' not in acf_struct:
                acf_struct['name'] = acf_struct['installdir']
            yield acf_struct

def owned_steam_games(steam_id):
    url = "http://steamcommunity.com/profiles/" + steam_id + "/games?xml=1"
    html = urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': AGENT}))
    tree = xml.etree.ElementTree.ElementTree()
    tree.parse(html)
    games_xml = tree.getiterator('game')
    for game in games_xml:
        appid = int(game.find('appID').text)
        name = game.find('name').text
        #print(appid, name)
        yield (appid, name)

def get_steam_id():
    path = os.path.expanduser('~/.steam/config/loginusers.vdf')
    if not os.path.isfile(path):
        return None
    with open(path, 'r', ) as data:
        for line in data.readlines():
            line = line.strip('\t\n "')
            if line not in ('users', '{'):
                return line

def run_steam_meta_mode(args, games):
    logger.info('Visit our community page: https://steamcommunity.com/groups/debian_gdp#curation')
    owned = set()
    if args.download:
        steam_id = get_steam_id()
        if steam_id is None:
            logger.error("Couldn't read SteamID from ~/.steam/config/loginusers.vdf")
        else:
            logger.info('Getting list of owned games from '
                        'http://steamcommunity.com/profiles/' + steam_id)
            owned = set(g[0] for g in owned_steam_games(steam_id))

    logging.info('Searching for locally installed Steam games...')
    found_games = []
    found_packages = []
    tasks = {}
    for game, gamedata in games.items():
        for package in gamedata.packages.values():
            id = package.steam.get('id') or gamedata.steam.get('id')
            if not id:
                continue

            if package.type == 'demo':
                continue
            # ignore other translations for "I Have No Mouth"
            if lang_score(package.lang) == 0:
                continue

            installed = PACKAGE_CACHE.is_installed(package.name)
            if args.new and installed:
                continue

            if game not in tasks:
                tasks[game] = gamedata.construct_task()

            paths = []
            for path in tasks[game].iter_steam_paths((package,)):
                if path not in paths:
                    paths.append(path)
            if not paths and id not in owned:
                continue

            if game not in found_games:
                found_games.append(game)
            found_packages.append({
                'game' : game,
                'type' : 1 if package.type == 'full' else 2,
                'package': package.name,
                'installed': installed,
                'longname': package.longname or gamedata.longname,
                'paths': paths,
               })
    if not found_games:
        logger.error('No Steam games found')
        return

    print('[x] = package is already installed')
    print('----------------------------------------------------------------------\n')
    found_packages = sorted(found_packages, key=lambda k: (k['game'], k['type'], k['longname']))
    for g in sorted(found_games):
        print(g)
        for p in found_packages:
            if p['game'] != g:
                continue
            print('[%s] %-42s    %s' % ('x' if p['installed'] else ' ',
                                        p['package'], ascii_safe(p['longname'])))
            for path in p['paths']:
                print(path)
            if not p['paths']:
                print('<game owned but not installed/found>')
        print()

    if not args.new and not args.all:
       logger.info('Please specify --all or --new to create desired packages.')
       return

    preserve_debs = (getattr(args, 'destination', None) is not None)
    install_debs = getattr(args, 'install', True)
    if getattr(args, 'compress', None) is None:
        # default to not compressing if we aren't going to install it
        # anyway
        args.compress = preserve_debs

    all_debs = set()

    for shortname in sorted(found_games):
        task = tasks[shortname]
        task.verbose = getattr(args, 'verbose', False)
        task.save_downloads = args.save_downloads
        try:
            task.look_for_files(binary_executables=args.binary_executables)
        except BinaryExecutablesNotAllowed:
            continue
        except NoPackagesPossible:
            continue

        todo = list()
        for packages in found_packages:
            if packages['game'] == shortname and packages['paths']:
                todo.append(task.game.packages[packages['package']])

        if not todo:
            continue

        try:
            ready = task.prepare_packages(log_immediately=False,
                                          packages=todo)
        except NoPackagesPossible:
            logger.error('No package possible for %s.' % task.game.shortname)
            continue
        except DownloadsFailed:
            logger.error('Unable to complete any packages of %s'
                         ' because downloads failed.' % task.game.shortname)
            continue

        if args.destination is None:
            destination = workdir = tempfile.mkdtemp(prefix='gdptmp.')
        else:
            workdir = None
            destination = args.destination

        debs = task.build_packages(ready,
                compress=getattr(args, 'compress', True),
                destination=destination)
        rm_rf(os.path.join(task.get_workdir(), 'tmp'))

        if preserve_debs:
            for deb in debs:
                print('generated "%s"' % os.path.abspath(deb))
        all_debs = all_debs.union(debs)

    if not all_debs:
        logger.error('Unable to package any game.')
        if workdir:
           rm_rf(workdir)
        raise SystemExit(1)

    if install_debs:
        install_packages(all_debs, args.install_method, args.gain_root_command)
    if workdir:
        rm_rf(workdir)
