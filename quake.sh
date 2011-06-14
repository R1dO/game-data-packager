#! /bin/sh

# quake.sh - launcher script for quake 1

data_location=/usr/share/games/quake
engine_path=/usr/games/quakespasm

no_data_msg="Missing data; see /usr/share/doc/quake/README.Debian"

if ! [ -f "${data_location}/id1/pak0.pak" ]; then
    exec "$data_location"/need-data.sh "$no_data_msg"
fi

exec ${engine_path} -basedir ${data_location}
