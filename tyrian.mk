BASICFILES = usr/share/doc/tyrian-data/README.Debian \
usr/share/doc/tyrian-data/copyright
DESTFILES = $(addprefix build/tyrian-data/, $(BASICFILES))

# VERSION is defined by the parent make
out/tyrian-data_$(VERSION)_all.deb: build/tyrian-data/DEBIAN/control $(DESTFILES)
		fakeroot dpkg-deb -b build/tyrian-data $@

DIRS = build/tyrian-data \
build/tyrian-data/DEBIAN \
build/tyrian-data/usr \
build/tyrian-data/usr/share \
build/tyrian-data/usr/share/games \
build/tyrian-data/usr/share/games/tyrian \
build/tyrian-data/usr/share/doc \
build/tyrian-data/usr/share/doc/tyrian-data

$(DIRS):
	mkdir $@

$(DESTFILES): $(DIRS)
	cp -p tyrian-data/`basename "$@"` $@

build/tyrian-data/DEBIAN/control: tyrian-data/control.in $(DIRS)
	m4 -DPACKAGE=tyrian-data -DVERSION=$(VERSION) $< > $@ 

clean:
	rm -f build/tyrian-data/DEBIAN/control out/tyrian-data_$(VERSION)_all.deb \
		build/tyrian-data/usr/share/doc/tyrian-data/copyright \
		build/tyrian-data/usr/share/doc/tyrian-data/README.Debian
	for d in $(DIRS); do echo "$$d"; done | sort -r | while read d; do \
		[ ! -d "$$d" ] || rmdir "$$d"; done

.PHONY: clean $(DESTFILES)
