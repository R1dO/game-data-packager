#!/usr/bin/python3
# encoding=utf-8
#
# Copyright © 2015 Simon McVittie <smcv@debian.org>
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

import io
import logging
import os
import struct
import re

from . import (StreamUnpackable, UnpackableEntry)

logger = logging.getLogger(__name__)

# Arbitrary limit to avoid reading too much binary data if something goes wrong
MAX_LINE_LENGTH = 1024

class UmodSection(object):
    """Base class for [Sections] in a umod's manifest."""
    def __init__(self, name):
        # The name of the section, e.g. UTRequirement
        self.name = name
        # Sequence of UmodEntry
        self.entries = ()
        # Stuff we didn't parse
        self.unparsed = []

class UmodEntryFile(io.BufferedIOBase):
    """File-like object allowing an embedded file to be read from a umod.

    Each Umod can currently have at most one UmodEntryFile open at a time.
    """
    def __init__(self, umod, entry, offset, length):
        assert isinstance(umod.reader, io.BufferedIOBase)
        self.__umod = umod
        self.entry = entry
        self.__offset = offset
        self.__position = 0
        self.__length = length

    def read(self, size=-1):
        if self.__position is None:
            raise OSError('File closed')

        if size is None or size < 0 or size > (self.__length - self.__position):
            size = self.__length - self.__position

        if size <= 0:
            return b''

        ret = self.__umod.reader.read(size)
        self.__position += len(ret)

        return ret

    def read1(self, size=-1):
        """read1() is the same as read() for this class."""
        return self.read(size)

    def close(self):
        self.__position = None

    def _read_text_line(self):
        line = b';'

        # Lines starting with ; or // are comments.
        while line.startswith(b';') or line.startswith(b'//'):
            line = self.readline(MAX_LINE_LENGTH)

        if not line:
            raise ValueError('Unexpected end of file')
        elif not line.endswith(b'\r\n'):
            raise ValueError('Unterminated line: %r' % line)

        line = line[:-2].decode('windows-1252')
        return line

class UmodEntry(UnpackableEntry):
    """Base class for files and edit instructions in a umod."""
    def __init__(self, name, size, offset, flags):
        self._name = name.replace('\\', '/')
        self._size = size
        self.offset = offset
        self.flags = flags

    @property
    def is_directory(self):
        return False

    @property
    def is_regular_file(self):
        return True

    @property
    def name(self):
        return self._name

    @property
    def size(self):
        return self._size

    @property
    def type_indicator(self):
        if self.flags:
            return '-%d' % self.flags
        else:
            return '-r'

class UmodFileEntry(UmodEntry):
    """A file that can be unpacked from a umod."""
    pass

class UmodEditEntry(UmodEntry):
    """An instruction to edit a file by merging in content from the umod."""

    @property
    def is_regular_file(self):
        return False

    @property
    def type_indicator(self):
        if self.flags:
            return 'e%d' % self.flags
        else:
            return 'er'

_FILE_RE = re.compile(r'^[(]'
        r'Src=([^,]+),'
        r'(?:Master=[^,]+,)?'
        r'(?:Lang=[a-z][a-z]t,)?'
        r'Size=([0-9]+)'
        r'(?:,Flags=([0-9]+))?'
        r'[)]$')
_COPY_RE = re.compile(r'^[(]'
        r'Src=([^,]+),'
        r'Master=([^,]+),'
        r'Size=([^,]+),'
        r'Flags=3'
        r'[)]$')

class UmodGroup(UmodSection):
    """A group of files and edit instructions.
    """
    def __init__(self, name):
        super(UmodGroup, self).__init__(name)
        self.entries = []

    def _consume_line(self, umod, k, v):
        if k == 'File':
            m = _FILE_RE.match(v)

            if not m:
                raise ValueError('Unexpected value in File= line: %r' % v)

            name = m.group(1).replace('\\', '/')
            entry = umod.entries[name]
            assert entry.size == int(m.group(2)), entry.size
            if m.group(3):
                assert entry.flags == int(m.group(3)), entry.flags

            # replace placeholder
            umod.entries[name] = UmodFileEntry(name, entry.size,
                    entry.offset, entry.flags)
            self.entries.append(umod.entries[name])

        elif k == 'Copy':
            m = _COPY_RE.match(v)

            if not m:
                raise ValueError('Unexpected value in Copy= line: %r' % v)

            assert m.group(1) == m.group(2)
            name = m.group(1).replace('\\', '/')
            entry = umod.entries[name]
            assert (entry.size == int(m.group(3)) or
                    name == 'System/Manifest.ini')
            assert entry.flags == 3

            # replace placeholder
            umod.entries[name] = UmodEditEntry(name,
                    entry.size, entry.offset, entry.flags)
            self.entries.append(umod.entries[name])

        elif k in ('AddIni',
                'Backup',
                'Delete',
                'Ini',
                'MasterPath',
                'Optional',
                'Selected',
                'Visible',
                'WinRegistry'):
            self.unparsed.append((k, v))

        else:
            raise ValueError('Unexpected key in group: %r (value %r)' % (k, v))

class UmodRequirement(UmodSection):
    def __init__(self, name):
        super(UmodRequirement, self).__init__(name)
        self.product = None
        self.version = None

    def _consume_line(self, umod, k, v):
        if k == 'Product':
            self.product = v
        elif k == 'Version':
            self.version = v
        elif k in ('DLLCheck',
                'OldVersionNumber',
                'OldVersionInstallCheck',
                'MapCheck',
                'TextureCheck',
                'UCheck'):
            self.unparsed.append((k, v))
        else:
            raise ValueError('Unexpected key in requirement: %r (value %r)' %
                    (k, v))

class NotUmod(ValueError):
    pass

def _open(path_or_file):
    if isinstance(path_or_file, (str, bytes, int)):
        close_file = True
        name = str(path_or_file)
        reader = open(path_or_file, 'rb')
    else:
        close_file = False
        reader = path_or_file

        if hasattr(path_or_file, 'name'):
            name = path_or_file.name
        else:
            name = repr(path_or_file)

        if reader.read(0) != b'':
            raise ValueError('%r is not open in binary mode' % reader)

        if not isinstance(reader, io.BufferedIOBase):
            reader = io.BufferedReader(reader)

    reader.seek(-20, os.SEEK_END)
    trailer_offset = reader.tell()
    block = reader.read(20)

    if len(block) != 20:
        raise NotUmod('"%s" is not a .umod: unable to read 20 bytes at end' %
                name)

    magic, toc_offset, eof_offset, flags, checksum = struct.unpack('<IIIII',
            block)

    if magic != 0x9fe3c5a3:
        raise NotUmod('"%s" is not a .umod: magic number does not match' % name)

    if reader.tell() != eof_offset:
        raise NotUmod('"%s" is not a .umod: length field does not match' % name)

    return (reader, name, toc_offset, trailer_offset, flags, checksum, \
            close_file)

class Umod(StreamUnpackable):
    """Object representing an Unreal Tournament modification package,
    or an executable installer in a similar format.

    The API of this class is similar to tarfile.TarFile and zipfile.ZipFile.
    """

    def __init__(self, path_or_file, mode='r'):
        """Constructor.

        path_or_file may be a string or bytes object, a file descriptor,
        or a file object open in binary mode.
        """
        if mode != 'r':
            raise ValueError('Umod objects only support read access')

        self.product = None
        self.version = None
        self.sections = []
        self.requirements = {}
        self.groups = {}
        self.entries = {}
        self.entry_order = []
        self.unparsed = []

        self.reader, self.name, toc_offset, trailer_offset, flags, \
                checksum, self.__close_file = _open(path_or_file)

        self.reader.seek(toc_offset)

        n_entries = self.__read_compact_index()

        for i in range(n_entries):
            # FIXME: is this a compact index, or just a 1-byte value?
            # We'll never know unless a filename needs more than 6 bits
            # (64 bytes including \0). For now we assume a 1-byte value.
            strlen = self.reader.read(1)[0]
            name = self.reader.read(strlen).decode('windows-1252')
            assert name[-1] == '\0'
            name = name[:-1]
            offset, length, flags = struct.unpack('<III', self.reader.read(12))
            entry = UmodEntry(name, length, offset, flags)
            self.entry_order.append(entry.name)
            self.entries[entry.name] = entry

        assert self.reader.tell() == trailer_offset
        manifest = self.open(self.entries['System/Manifest.ini'])
        line = manifest.readline()
        assert line == b'[Setup]\r\n', line

        expected_sections = {}

        while True:
            line = manifest._read_text_line()

            # A blank line terminates the Setup section. The next line
            # is expected to be a requirement or group.
            if not line:
                break

            k, v = line.split('=', 1)

            if k == 'Product':
                self.product = v
            elif k == 'Version':
                self.version = v
            elif k == 'Requires':
                section = UmodRequirement(v)
                self.sections.append(section)
                self.requirements[v] = section
                expected_sections[v] = section
            elif k == 'Group':
                section = UmodGroup(v)
                self.sections.append(section)
                self.groups[v] = section
                expected_sections[v] = section
            elif k in ('Archive',
                    'CdAutoPlay',
                    'Exe',
                    'IsMasterProduct',
                    'Language',
                    'Patch',
                    'PatchCdCheck',
                    'RefPath',
                    'SrcPath',
                    'Tree',
                    'MasterPath',
                    'Visible'):
                self.unparsed.append((k, v))
            else:
                raise ValueError('Unknown Umod [Setup] key: %r' % k)

        while expected_sections:
            line = manifest._read_text_line()

            if not line.startswith('[') or not line.endswith(']'):
                raise ValueError('Expected [*], got %r' % line)

            line = line[1:-1]

            if line not in expected_sections:
                logger.warning('Unexpected section [%s]' % line)

            self.__parse_section(manifest, expected_sections.pop(line, None))

        for x in self:
            assert isinstance(x, UmodEntry)
            assert x.__class__ != UmodEntry, x.name

    def __parse_section(self, manifest, section):
        while True:
            line = manifest._read_text_line()

            if not line:
                break

            k, v = line.split('=', 1)
            if section is None:
                logger.debug('%s=%s', k, v)
            else:
                section._consume_line(self, k, v)

    def __enter__(self):
        return self

    def __exit__(self, _et, _ev, _tb):
        if self.__close_file:
            self.reader.close()

    def open(self, member):
        """Open a binary file-like object for the given filename or UmodEntry.
        """
        if isinstance(member, str):
            entry = self.entries[member]
        else:
            entry = member

        assert isinstance(entry, UmodEntry)
        self.reader.seek(entry.offset)
        return UmodEntryFile(self, entry, entry.offset, entry.size)

    def getinfo(self, name):
        return self.entries[name]

    def infolist(self):
        return [x for x in self]

    def namelist(self):
        return [x.name for x in self]

    def __iter__(self):
        for name in self.entry_order:
            yield self.entries[name]

    def __read_compact_index(self):
        # http://wiki.beyondunreal.com/Legacy:Package_File_Format/Data_Details
        byte = self.reader.read(1)[0]
        negative = bool(byte & 0x80)
        more = bool(byte & 0x40)
        value = byte & 0x3f
        shift = 6

        while more:
            byte = self.reader.read(1)[0]

            # fifth byte contributes 8 bits 27..34 inclusive
            # (but we should never see that large an index in a umod)
            if shift >= 27:
                more = False
                value += (byte << shift)

            # second..fourth bytes contribute 7 bits 6..12, 13..19, 20. 26
            # inclusive
            more = bool(byte & 0x80)
            value += ((byte & 0x7f) << shift)
            shift += 7

        if negative:
            return -value
        return value

    @property
    def format(self):
        return 'umod'

    def seekable(self):
        # umods are always seekable
        return True

def is_umod(path_or_file):
    try:
        _open(path_or_file)
        return True
    except:
        return False

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--output', '-o', help='extract to OUTPUT',
            default=None)
    parser.add_argument('umod')
    args = parser.parse_args()

    umod = Umod(args.umod)

    if args.output:
        umod.extractall(args.output)
    else:
        umod.printdir()
