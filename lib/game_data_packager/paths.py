import os

if os.environ.get('GDP_UNINSTALLED'):
    CONFIG = './etc/game-data-packager.conf'
    DATADIR = './out'
    ETCDIR = './etc'
    LIBDIR = './lib'
else:
    CONFIG = '/etc/game-data-packager.conf'
    DATADIR = '/usr/share/games/game-data-packager'
    ETCDIR = '/etc/game-data-packager'
    LIBDIR = '/usr/lib/game-data-packager'
