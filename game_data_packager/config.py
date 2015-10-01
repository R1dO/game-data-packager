#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2014-2015 Simon McVittie <smcv@debian.org>
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

import logging
import re

from .paths import CONFIG

logger = logging.getLogger('game-data-packager.config')

COMMENT = re.compile(r'#.*')
OPTION = re.compile('^([A-Z]+)=(["\']?)(.*)\\2$')

def read_config():
    """The world's simplest shell script parser.
    """

    config = {
            'install': False,
            'preserve': True,
            'verbose': False,
            'install_method': '',
            'gain_root_command': '',
            }

    try:
        with open(CONFIG, encoding='utf-8') as conffile:
            lineno = 0
            for line in conffile:
                lineno += 1
                line = COMMENT.sub('', line)
                line = line.strip()
                if not line:
                    continue
                match = OPTION.match(line)
                if match:
                    k = match.group(1).lower()
                    v = match.group(3)
                    if k in config:
                        if v == 'yes':
                            config[k] = True
                        elif v == 'no':
                            config[k] = False
                        else:
                            logger.warning('%s:%d: unknown option value: %s=%r',
                                    CONFIG, lineno, k, v)
                    else:
                        logger.warning('%s:%d: unknown option: %s',
                                CONFIG, lineno, k)
                else:
                    logger.warning('%s:%d: could not parse line: %r',
                        CONFIG, lineno, line)
    except OSError:
        pass

    return config
