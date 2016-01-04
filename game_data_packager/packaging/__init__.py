#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2014-2016 Simon McVittie <smcv@debian.org>
#           © 2015 Alexandre Detiste <alexandre@detiste.be>
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

from abc import (ABCMeta, abstractmethod)

class PackagingSystem(metaclass=ABCMeta):

    def is_installed(self, package):
        """Return boolean: is a package with the given name installed?"""
        return (self.current_version(package) is not None)

    def is_available(self, package):
        """Return boolean: is a package with the given name available
        to apt or equivalent?
        """
        try:
            self.available_version(package)
        except:
            return False
        else:
            return True

    @abstractmethod
    def current_version(self, package):
        """Return the version number of the given package as a string,
        or None.
        """
        raise NotImplementedError

    @abstractmethod
    def available_version(self, package):
        """Return the version number of the given package available in
        apt or equivalent, or raise an exception if unavailable.
        """
        raise NotImplementedError

    @abstractmethod
    def install_packages(self, packages, method=None, gain_root='su'):
        """Install one or more packages (a list of filenames)."""
        raise NotImplementedError

def get_native_packaging_system():
    # lazy import when actually needed
    from ..version import (FORMAT)

    if FORMAT == 'deb':
        from .deb import (get_distro_packaging)
    elif FORMAT == 'arch':
        from .arch import (get_distro_packaging)
    elif FORMAT == 'rpm':
        from .rpm import (get_distro_packaging)
    else:
        raise RuntimeError('Unable to determine native packaging system')

    return get_distro_packaging()
