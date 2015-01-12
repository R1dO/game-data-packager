VERSION := $(shell dpkg-parsechangelog | grep ^Version | cut -d' ' -f2-)
DIRS := ./out ./build
LDLIBS = -ldynamite

default: $(DIRS)
	gzip -nc9 debian/changelog > ./out/changelog.gz
	chmod 0644 ./out/changelog.gz
	install -m644 data/*.yaml out/
	install -m644 data/*.control.in out/
	install -m644 data/*.copyright out/
	install -m644 data/*.copyright.in out/
	install -m644 data/*.desktop.in out/
	install -m644 data/*.preinst.in out/
	install -m644 data/*.README.Debian.in out/
	for x in data/*.xpm; do \
		o=out/$${x#data/}; \
		convert $$x $${o%.xpm}.png || exit $$?; \
	done
	make -f quake.mk LONG="Quake" VERSION=$(VERSION) PACKAGE=quake-registered \
		FOLDER=id1
	make -f quake.mk LONG="Quake music" VERSION=$(VERSION) \
		PACKAGE=quake-music FOLDER=id1
	make -f quake.mk LONG="Quake shareware" VERSION=$(VERSION) \
		PACKAGE=quake-shareware FOLDER=id1
	make -f quake.mk LONG="Quake mission pack 1: Scourge of Armagon" \
		VERSION=$(VERSION) PACKAGE=quake-armagon FOLDER=hipnotic
	make -f quake.mk LONG="Quake MP1 music" VERSION=$(VERSION) \
		PACKAGE=quake-armagon-music FOLDER=hipnotic
	make -f quake.mk LONG="Quake mission pack 2: Dissolution of Eternity" \
		VERSION=$(VERSION) PACKAGE=quake-dissolution FOLDER=rogue
	make -f quake.mk LONG="Quake MP2 music" VERSION=$(VERSION) \
		PACKAGE=quake-dissolution-music FOLDER=rogue
	make -f quake2.mk VERSION=$(VERSION) PACKAGE=quake2-demo-data
	make -f quake2.mk VERSION=$(VERSION) PACKAGE=quake2-full-data
	make -f quake2.mk VERSION=$(VERSION) PACKAGE=quake2-music
	make -f quake2.mk VERSION=$(VERSION) PACKAGE=quake2-xatrix
	make -f quake2.mk VERSION=$(VERSION) PACKAGE=quake2-rogue
	make -f wolf3d.mk VERSION=$(VERSION)
	make -f lgeneral.mk LONG="LGeneral" VERSION=$(VERSION)

$(DIRS):
	mkdir -p $@

tests/empty.deb:
	dpkg-deb -b tests/empty tests/empty.deb

clean:
	rm -f ./out/changelog.gz
	rm -f ./out/foo ./out/bar ./out/baz
	rm -f ./out/*.control
	rm -f ./out/*.control.in
	rm -f ./out/*.copyright
	rm -f ./out/*.copyright.in
	rm -f ./out/*.desktop.in
	rm -f ./out/*.preinst.in
	rm -f ./out/*.README.Debian.in
	rm -f ./out/*.png
	rm -f ./out/*.yaml
	rm -rf lib/game_data_packager/__pycache__
	make -f quake.mk LONG="Quake" VERSION=$(VERSION) PACKAGE=quake-registered \
		FOLDER=id1 clean
	make -f quake.mk LONG="Quake music" VERSION=$(VERSION) \
		PACKAGE=quake-music FOLDER=id1 clean
	make -f quake.mk LONG="Quake shareware" VERSION=$(VERSION) \
		PACKAGE=quake-shareware FOLDER=id1 clean
	make -f quake.mk LONG="Quake mission pack 1: Scourge of Armagon" \
		VERSION=$(VERSION) PACKAGE=quake-armagon FOLDER=hipnotic clean
	make -f quake.mk LONG="Quake MP1 music" VERSION=$(VERSION) \
		PACKAGE=quake-armagon-music FOLDER=hipnotic clean
	make -f quake.mk LONG="Quake mission pack 2: Dissolution of Eternity" \
		VERSION=$(VERSION) PACKAGE=quake-dissolution FOLDER=rogue clean
	make -f quake.mk LONG="Quake MP2 music" VERSION=$(VERSION) \
		PACKAGE=quake-dissolution-music FOLDER=rogue clean
	make -f quake2.mk VERSION=$(VERSION) PACKAGE=quake2-demo-data clean
	make -f quake2.mk VERSION=$(VERSION) PACKAGE=quake2-full-data clean
	make -f quake2.mk VERSION=$(VERSION) PACKAGE=quake2-music clean
	make -f quake2.mk VERSION=$(VERSION) PACKAGE=quake2-xatrix clean
	make -f quake2.mk VERSION=$(VERSION) PACKAGE=quake2-rogue clean
	make -f wolf3d.mk VERSION=$(VERSION) clean
	make -f lgeneral.mk LONG="LGeneral" VERSION=$(VERSION) clean
	for d in $(DIRS); do [ ! -d "$$d" ]  || rmdir "$$d"; done

check:
	./t/verify-md5sum-alternatives.sh
	DATADIR=data PYTHONPATH=lib python3 -m game_data_packager.check_syntax
	pyflakes3 lib/game_data_packager/*.py lib/game_data_packager/*/*.py || :

.PHONY: default clean check
