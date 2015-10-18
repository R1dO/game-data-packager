# encoding=utf-8

import os

if os.environ.get('GDP_UNINSTALLED'):
    CONFIG = './etc/game-data-packager.conf'
    DATADIR = './out'
    ETCDIR = './etc'
    USE_VFS = False
else:
    CONFIG = '/etc/game-data-packager.conf'
    DATADIR = '/usr/share/games/game-data-packager'
    ETCDIR = '/etc/game-data-packager'
    USE_VFS = True
