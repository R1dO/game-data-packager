#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2014-2015 Simon McVittie <smcv@debian.org>
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

from abc import (ABCMeta, abstractmethod)
import errno
import os
import shlex
import shutil
import tarfile
import time
import zipfile

class UnpackableEntry(metaclass=ABCMeta):
    """An entry in a StreamUnpackable.
    """
    @property
    @abstractmethod
    def is_directory(self):
        raise NotImplementedError

    @property
    @abstractmethod
    def is_regular_file(self):
        """True if the entry is a regular file. False if it is a
        directory, symlink, or some special thing like an instruction
        to patch some other file.
        """
        raise NotImplementedError

    @property
    def is_extractable(self):
        """True if the entry is something that we can extract.

        The default implementation is that we can extract regular files.
        """
        return self.is_regular_file

    @property
    def mtime(self):
        """The last-modification time, or None if unspecified."""
        return None

    @property
    @abstractmethod
    def name(self):
        """The absolute or relative filename, with Unix path separators."""
        raise NotImplementedError

    @property
    @abstractmethod
    def size(self):
        """The size in bytes."""
        raise NotImplementedError

    @property
    def type_indicator(self):
        """One or more ASCII symbols indicating the file type."""
        if self.is_directory:
            ret = 'd'
        elif self.is_regular_file:
            ret = '-'
        else:
            ret = '?'

        if self.is_extractable:
            ret += 'r'
        else:
            ret += '-'

        return ret

class StreamUnpackable(metaclass=ABCMeta):
    """An archive in which entries can be inspected and extracted
    by iteration.
    """

    @abstractmethod
    def __iter__(self):
        """Iterate through UnpackableEntry objects."""
        raise NotImplementedError

    @abstractmethod
    def open(self, member):
        """Open a binary file-like entry for the name or entry.
        """
        raise NotImplementedError

    def extract(self, member, path=None):
        """Extract the given member from the archive into the given
        directory.
        """

        if isinstance(member, (str, bytes)):
            filename = member
        else:
            filename = member.name

        reader = self.open(member)

        if not reader:
            raise ValueError('cannot open %s' % member)

        with reader:
            filename = filename.lstrip('/')

            while filename.startswith('../'):
                filename = filename[3:]
            filename = filename.replace('/../', '/')
            if filename.endswith('/..'):
                filename = filename[:-3]
            if filename.endswith('/'):
                filename = filename[:-1]
            if path is None:
                path = '.'

            dest = os.path.join(path, filename)
            os.makedirs(os.path.dirname(dest), exist_ok=True)

            try:
                os.remove(dest)
            except OSError as e:
                if e.errno != errno.ENOENT:
                    raise

            with open(dest, 'xb') as writer:
                shutil.copyfileobj(reader, writer)

    def extractall(self, path, members=None):
        for entry in self:
            if entry.is_extractable:
                if members is None or entry.name in members:
                    self.extract(entry, path)

    def printdir(self):
        for entry in self:
            if entry.size is None:
                size = '?' * 9
            else:
                size = '%9s' % entry.size

            if entry.mtime is not None:
                mtime = time.strftime('%Y-%m-%d %H:%M:%S',
                        time.gmtime(entry.mtime))
            else:
                mtime = '????-??-?? ??:??:??'

            print('%s %s %s %s' % (entry.type_indicator, size, mtime,
                shlex.quote(entry.name)))

class WrapperUnpacker(StreamUnpackable):
    """Base class for a StreamUnpackable that wraps a TarFile-like object."""

    def __init__(self):
        self._impl = None

    @abstractmethod
    def _wrap_entry(self, entry):
        raise NotImplementedError

    @abstractmethod
    def _is_entry(self, entry):
        raise NotImplementedError

    def __enter__(self):
        return self

    def __exit__(self, ex_type, ex_value, ex_traceback):
        if self._impl is not None:
            self._impl.close()
            self._impl = None

    def __iter__(self):
        for entry in self._impl:
            yield self._wrap_entry(entry)

    def open(self, entry):
        assert self._is_entry(entry)
        return self._impl.open(entry.impl)

class TarEntry(UnpackableEntry):
    __slots__ = 'impl'

    def __init__(self, impl):
        self.impl = impl

    @property
    def is_directory(self):
        return self.impl.isdir()

    @property
    def is_regular_file(self):
        return self.impl.isfile()

    @property
    def mtime(self):
        return self.impl.mtime

    @property
    def name(self):
        return self.impl.name

    @property
    def size(self):
        return self.impl.size

class TarUnpacker(WrapperUnpacker):
    def __init__(self, name, reader=None, compression='*', skip=0):
        super(TarUnpacker, self).__init__()

        if reader is None:
            reader = open(name, 'rb')

        if skip:
            discard = reader.read(skip)
            assert len(discard) == skip

        self._impl = tarfile.open(name, mode='r|' + compression,
                fileobj=reader)

    def open(self, entry):
        assert isinstance(entry, TarEntry)
        return self._impl.extractfile(entry.impl)

    def _is_entry(self, entry):
        return isinstance(entry, TarEntry)

    def _wrap_entry(self, entry):
        return TarEntry(entry)

class ZipEntry(UnpackableEntry):
    __slots__ = 'impl'

    def __init__(self, impl):
        self.impl = impl

    @property
    def is_directory(self):
        return self.name.endswith('/')

    @property
    def is_regular_file(self):
        return not self.name.endswith('/')

    @property
    def mtime(self):
        return time.mktime(self.impl.date_time + (0, 0, -1))

    @property
    def name(self):
        return self.impl.filename

    @property
    def size(self):
        return self.impl.file_size

class ZipUnpacker(WrapperUnpacker):
    def __init__(self, file_or_name):
        super(ZipUnpacker, self).__init__()
        self._impl = zipfile.ZipFile(file_or_name, 'r')

    def __iter__(self):
        for entry in self._impl.infolist():
            yield ZipEntry(entry)

    def _is_entry(self, entry):
        return isinstance(entry, ZipEntry)

    def _wrap_entry(self, entry):
        return ZipEntry(self)
