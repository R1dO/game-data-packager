#!/usr/bin/python3
# encoding=utf-8

import os

if os.environ.get('GDP_UNINSTALLED'):
    CONFIG = './etc/game-data-packager.conf'
    DATADIR = './out'
    ETCDIR = './etc'
    USE_VFS = bool(os.environ.get('GDP_USE_VFS'))
else:
    CONFIG = '/etc/game-data-packager.conf'
    if os.path.isdir('/usr/share/games/game-data-packager'):
        DATADIR = '/usr/share/games/game-data-packager'
    else:
        DATADIR = '/usr/share/game-data-packager'
    ETCDIR = '/etc/game-data-packager'
    USE_VFS = True
