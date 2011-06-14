#! /bin/sh

# quake.sh - launcher script for quake 1

data_location=/usr/share/games/quake
engine_path=/usr/games/quakespasm

exec ${engine_path} -basedir ${data_location}
