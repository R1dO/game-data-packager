VERSION := $(shell dpkg-parsechangelog | grep ^Version | cut -d' ' -f2-)
DIRS := ./out ./build
GDP_MIRROR ?= localhost

# some cherry picked games that:
# - are freely downloadable (either demo or full version)
# - test various codepaths:
#   - alternatives
#   - archive recursion (zip in zip)
#   - lha
#   - id-shr-extract
# - are not too big
TEST_SUITE += rott spear-of-destiny wolf3d

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
	make -f quake2.mk VERSION=$(VERSION) PACKAGE=quake2-demo-data
	make -f quake2.mk VERSION=$(VERSION) PACKAGE=quake2-full-data
	make -f quake2.mk VERSION=$(VERSION) PACKAGE=quake2-music
	make -f quake2.mk VERSION=$(VERSION) PACKAGE=quake2-xatrix
	make -f quake2.mk VERSION=$(VERSION) PACKAGE=quake2-rogue

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
	make -f quake2.mk VERSION=$(VERSION) PACKAGE=quake2-demo-data clean
	make -f quake2.mk VERSION=$(VERSION) PACKAGE=quake2-full-data clean
	make -f quake2.mk VERSION=$(VERSION) PACKAGE=quake2-music clean
	make -f quake2.mk VERSION=$(VERSION) PACKAGE=quake2-xatrix clean
	make -f quake2.mk VERSION=$(VERSION) PACKAGE=quake2-rogue clean
	for d in $(DIRS); do [ ! -d "$$d" ]  || rmdir "$$d"; done

check:
	./t/verify-md5sum-alternatives.sh
	GDP_UNINSTALLED=1 PYTHONPATH=lib python3 -m game_data_packager.check_syntax
	pyflakes3 lib/game_data_packager/*.py lib/game_data_packager/*/*.py || :

# Requires additional setup, so not part of "make check"
manual-check:
	install -d tmp/
	for game in $(TEST_SUITE); do \
	        GDP_MIRROR=$(GDP_MIRROR) GDP_UNINSTALLED=1 PYTHONPATH=lib \
		python3 -m game_data_packager -d ./tmp --no-search --no-compress $$game || exit $$?; \
	done
	rm -fr tmp/

.PHONY: default clean check manual-check
