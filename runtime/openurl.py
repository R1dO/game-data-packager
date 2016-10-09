#!/usr/bin/python3
# encoding=utf-8

# Open a URL. Command-line compatible with the openurl.sh provided with
# Quake 4, but a lot simpler, and with Flatpak support (via GLib and
# xdg-desktop-portal).

# Copyright © 2016 Simon McVittie <smcv@debian.org>
# Redistribution and use in source and compiled forms, with or without
# modification, are permitted under any circumstances. No warranty.

import argparse

from gi.repository import Gio

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Open a URL')
    parser.add_argument('url')
    args = parser.parse_args()

    Gio.AppInfo.launch_default_for_uri(args.url)
