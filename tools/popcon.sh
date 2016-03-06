#!/bin/bash

mkdir -p /var/cache/popcon/
mkdir -p tmp

date=$(date +%Y%m%d)
wget http://popcon.debian.org/by_inst.gz --no-clobber --output-document=/var/cache/popcon/debian_$date.gz

# the Ubuntu file is unreliably updated, sometimes it's stale for months
last_ubuntu=$(cd /var/cache/popcon/ ; ls -1 ubuntu_201*.gz  | tail -n 1)
md5_old=$(md5sum /var/cache/popcon/$last_ubuntu | cut -f 1 -d ' ')

wget http://popcon.ubuntu.com/by_inst.gz          --no-clobber --output-document=tmp/ubuntu_$date.gz
md5_new=$(md5sum tmp/ubuntu_$date.gz | cut -f 1 -d ' ')
if [ ! "$md5_old" = "$md5_new" ]
then
        echo "New Ubuntu file"
	mv tmp/ubuntu_$date.gz /var/cache/popcon/ -v
else
        echo "No Ubuntu update"
        rm tmp/ubuntu_$date.gz
fi
