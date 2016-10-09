#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2014-2016 Simon McVittie <smcv@debian.org>
#           © 2015-2016 Alexandre Detiste <alexandre@detiste.be>
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
import importlib
import os
import string

class PackagingSystem(metaclass=ABCMeta):
    ASSETS = '/usr/share'
    BINDIR = '/usr/bin'
    DOCDIR = '/usr/share/doc'
    LICENSEDIR = '/usr/share/doc'
    CHECK_CMD = None
    INSTALL_CMD = None

    # Exceptions to our normal heuristic for mapping a tool to a package:
    # the executable tool 'unzip' is in the unzip package, etc.
    #
    # Only exceptions need to be listed.
    #
    # 'NotImplemented' means that this dependency is not packaged by
    # the distro.
    PACKAGE_MAP = {}

    # Exceptions to our normal heuristic for mapping an abstract package name
    # to a package:
    #
    # - the library 'libfoo.so.0' is in a package that Provides libfoo.so.0
    #   (suitable for RPM)
    # - anything else is in the obvious package name
    RENAME_PACKAGES = {}

    # we keep Debian codification as reference, as it
    # - has the most architectures supported
    # - differentiates 'any' from 'all'
    # - is the most tested
    ARCH_DECODE = dict()

    def __init__(self):
        self._architecture = None
        self._foreign_architectures = set()
        # contexts to use when evaluating format- or distro-specific
        # dependencies, in order by preference
        self._contexts = ('generic',)

    def derives_from(self, context):
        return context in self._contexts

    def read_architecture(self):
        arch = os.uname()[4]
        self._architecture = { 'armv7l': 'armhf',
                               'armhfp': 'armhf',
                               'i586': 'i386',
                               'i686': 'i386',
                               'x86_64': 'amd64',
                             }.get(arch, arch)

    def get_architecture(self, archs=''):
        if self._architecture is None:
            self.read_architecture()

        if archs:
            # In theory this should deal with wildcards like linux-any,
            # but it's unlikely to be relevant in practice.
            archs = archs.split()

            if self._architecture in archs or 'any' in archs:
                return self._architecture

            for arch in archs:
                if arch in self._foreign_architectures:
                    return arch

        return self._architecture

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

    def substitute(self, template, package, **kwargs):
        if isinstance(template, dict):
            for c in self._contexts:
                if c in template:
                    template = template[c]
                    break
            else:
                return None

        if template is None:
            return template

        if '$' not in template:
            return template

        return string.Template(template).substitute(kwargs,
                assets=self.ASSETS,
                bindir=self.BINDIR,
                docdir=self.DOCDIR,
                licensedir=self.LICENSEDIR,
                pkgdocdir=self._get_pkgdocdir(package),
                pkglicensedir=self._get_pkglicensedir(package),
                prefix=self.PREFIX,
                )

    def _get_pkgdocdir(self, package):
        return '/'.join((self.DOCDIR, package))

    def _get_pkglicensedir(self, package):
        return '/'.join((self.LICENSEDIR, package))

    def override_lintian(self, destdir, package, tag, args):
        pass

    def format_relations(self, relations):
        """Yield a native dependency representation for this packaging system
        for each gdp.data.PackagingRelation in relations.
        """
        for pr in relations:
            if pr.contextual:
                for c in self._contexts:
                    if c in pr.contextual:
                        for x in self.format_relations([pr.contextual[c]]):
                            yield x

                        break
            else:
                yield self.format_relation(pr)

    @abstractmethod
    def format_relation(self, pr):
        """Return a native dependency representation for this packaging system
        and the given gdp.data.PackagingRelation. It is guaranteed
        that pr.contextual is empty.
        """
        raise NotImplementedError

    def rename_package(self, dependency):
        """Given an abstract package name, return the corresponding
        package name in this packaging system.

        Abstract package names are mostly the same as for Debian,
        except that libraries are represented as libfoo.so.0.
        """
        return self.RENAME_PACKAGES.get(dependency, dependency)

    def package_for_tool(self, tool):
        """Given an executable name, return the corresponding
        package name in this packaging system.
        """
        return self.PACKAGE_MAP.get(tool, tool)

    def tool_for_package(self, package):
        """Given a package name, return the corresponding
        main/unique executable in this packaging system.
        """
        for k,v in self.PACKAGE_MAP.items():
            if v == package:
                return k
        return package

def get_packaging_system(format, distro=None):
    mod = 'game_data_packager.packaging.{}'.format(format)
    return importlib.import_module(mod).get_packaging_system(distro)

def get_native_packaging_system():
    # lazy import when actually needed
    from ..version import (FORMAT, DISTRO)
    return get_packaging_system(FORMAT, DISTRO)
