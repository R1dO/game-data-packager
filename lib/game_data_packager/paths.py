import os

if os.environ.get('GDP_UNINSTALLED'):
    DATADIR = './out'
    ETCDIR = './etc'
    LIBDIR = './lib'
else:
    DATADIR = '/usr/share/games/game-data-packager'
    ETCDIR = '/etc/game-data-packager'
    LIBDIR = '/usr/lib/game-data-packager'
