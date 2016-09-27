GDP_MIRROR ?= localhost
bindir := /usr/games
datadir := /usr/share/games
pkgdatadir := ${datadir}/game-data-packager
PYTHON := python3
PYFLAKES3 := $(shell if [ -x /usr/bin/pyflakes3 ] ;  then echo pyflakes3 ; \
                   elif [ -x /usr/bin/pyflakes3k ] ; then echo pyflakes3k ; \
                   elif [ -x /usr/bin/python3-pyflakes ] ; then echo python3-pyflakes ; \
                   else ls -1 /usr/bin/pyflakes-python3.* | tail -n 1 ; \
                    fi)

# some cherry picked games that:
# - are freely downloadable (either demo or full version)
# - test various codepaths:
#   - alternatives
#   - archive recursion (zip in zip)
#   - lha
#   - id-shr-extract
#   - doom_commo.py plugin
# - are not too big
TEST_SUITE += rott spear-of-destiny wolf3d heretic

png       := $(patsubst ./data/%.xpm,./out/%.png,$(wildcard ./data/*.xpm))
png       += $(patsubst ./data/%.svg,./out/%.png,$(wildcard ./data/*.svg))
png       += out/memento-mori.png
# We deliberately don't compress and install memento-mori{,-2}.svg because
# they use features that aren't supported by librsvg, so they'd look wrong
# in all GTK-based environments.
svgz      := $(patsubst ./data/%.svg,./out/%.svgz,$(filter-out ./data/memento-mori-2.svg,$(wildcard ./data/*.svg)))
in_yaml   := $(wildcard ./data/*.yaml)
json      := $(patsubst ./data/%.yaml,./out/vfs/%.json,$(in_yaml))
json      += $(patsubst ./runtime/%.yaml.in,./out/%.json,$(wildcard ./runtime/*.yaml.in))
copyright := $(patsubst ./data/%,./out/%,$(wildcard ./data/*.copyright))
dot_in    := $(patsubst ./data/%,./out/%,$(wildcard ./data/*.in))
desktop   := $(patsubst ./runtime/%.in,./out/%,$(wildcard ./runtime/*.desktop.in))

default: $(png) $(svgz) $(json) $(copyright) $(dot_in) \
      $(desktop) \
      out/bash_completion out/changelog.gz out/copyright \
      out/game-data-packager out/vfs.zip out/memento-mori-2.svg

out/CACHEDIR.TAG:
	@mkdir -p out
	( echo "Signature: 8a477f597d28d17""2789f06886806bc55"; \
	echo "# This file marks this directory to not be backed up."; \
	echo "# For information about cache directory tags, see:"; \
	echo "#	http://www.brynosaurus.com/cachedir/" ) > $@

out/%: data/% out/CACHEDIR.TAG
	if [ -L $< ]; then cp -a $< $@ ; else install -m644 $< $@ ; fi

out/vfs/%.json: data/%.yaml tools/compile_yaml.py out/CACHEDIR.TAG
	@mkdir -p out/vfs
	$(PYTHON) tools/compile_yaml.py $< $@

out/vfs.zip: $(json)
	rm -f out/vfs.zip
	chmod 0644 out/vfs/*
	if [ -n "$(BUILD_DATE)" ]; then \
		touch --date='$(BUILD_DATE)' out/vfs/*; \
	fi
	cd out/vfs && ls -1 | LC_ALL=C sort | \
		env TZ=UTC zip ../vfs.zip -9 -X -q -@

out/bash_completion: $(in_yaml) out/CACHEDIR.TAG
	$(PYTHON) tools/bash_completion.py > ./out/bash_completion
	chmod 0644 ./out/bash_completion

out/changelog.gz: debian/changelog out/CACHEDIR.TAG
	gzip -nc9 debian/changelog > ./out/changelog.gz
	chmod 0644 ./out/changelog.gz

out/game-data-packager: run out/CACHEDIR.TAG
	install run out/game-data-packager

out/%.svg: data/%.svg out/CACHEDIR.TAG
	inkscape --export-plain-svg=$@ $<

out/memento-mori.svg: data/memento-mori-2.svg out/CACHEDIR.TAG
	inkscape --export-plain-svg=$@ --export-id=layer1 --export-id-only $<

out/memento-mori.png: out/memento-mori.svg
	inkscape --export-png=$@ -w96 -h96 $<

out/%.png: data/%.xpm out/CACHEDIR.TAG
	convert $< $@

out/%.png: data/%.svg out/CACHEDIR.TAG
	inkscape --export-png=$@ -w96 -h96 $<

out/%.svgz: out/%.svg
	gzip -nc $< > $@

out/launch-%.json: out/launch-%.yaml
	$(PYTHON) tools/yaml2json.py $< $@

out/%: runtime/%.in out/CACHEDIR.TAG
	PYTHONPATH=. $(PYTHON) tools/expand_vars.py $< $@

clean:
	rm -f ./out/bash_completion
	rm -f ./out/changelog.gz
	rm -f ./out/copyright
	rm -f ./out/game-data-packager
	rm -f ./out/*.control.in
	rm -f ./out/*.copyright
	rm -f ./out/*.copyright.in
	rm -f ./out/*.desktop
	rm -f ./out/*.json
	rm -f ./out/*.preinst.in
	rm -f ./out/*.png
	rm -f ./out/*.svgz
	rm -f ./out/*.svg
	rm -f ./out/*.txt
	rm -f ./out/vfs.zip
	rm -f ./out/index.html
	rm -fr out/vfs
	rm -rf game_data_packager/__pycache__
	rm -rf game_data_packager/games/__pycache__
	rm -rf tools/__pycache__
	rm -f out/CACHEDIR.TAG
	test ! -d out || rmdir out

check:
	LC_ALL=C $(PYFLAKES3) game_data_packager/*.py game_data_packager/*/*.py runtime/*.py tools/*.py || :
	LC_ALL=C GDP_UNINSTALLED=1 PYTHONPATH=. $(PYTHON) tests/deb.py
	LC_ALL=C GDP_UNINSTALLED=1 PYTHONPATH=. $(PYTHON) tests/hashed_file.py
	LC_ALL=C GDP_UNINSTALLED=1 PYTHONPATH=. $(PYTHON) tests/rpm.py
	LC_ALL=C GDP_UNINSTALLED=1 PYTHONPATH=. $(PYTHON) tests/umod.py
	LC_ALL=C GDP_UNINSTALLED=1 PYTHONPATH=. $(PYTHON) tools/check_syntax.py
	LC_ALL=C GDP_UNINSTALLED=1 PYTHONPATH=. $(PYTHON) tools/check_equivalence.py

install:
	mkdir -p $(DESTDIR)$(bindir)
	install -m0755 out/game-data-packager                  $(DESTDIR)$(bindir)

	mkdir -p $(DESTDIR)$(pkgdatadir)
	cp -ar game_data_packager/                             $(DESTDIR)$(pkgdatadir)/
	python3 -m game_data_packager.version $(RELEASE) >     $(DESTDIR)$(pkgdatadir)/game_data_packager/version.py
	install -m0644 out/*.copyright                         $(DESTDIR)$(pkgdatadir)/
	install -m0644 out/*.png                               $(DESTDIR)$(pkgdatadir)/
	install -m0644 out/*.svgz                              $(DESTDIR)$(pkgdatadir)/
	install -m0644 out/bash_completion                     $(DESTDIR)$(pkgdatadir)/
	install -m0644 out/changelog.gz                        $(DESTDIR)$(pkgdatadir)/
	install -m0644 out/copyright                           $(DESTDIR)$(pkgdatadir)/
	install -m0644 out/vfs.zip                             $(DESTDIR)$(pkgdatadir)/

	install runtime/launcher.py                            $(DESTDIR)$(pkgdatadir)/gdp-launcher
	install -m0644 out/*.desktop                           $(DESTDIR)$(pkgdatadir)/
	install -m0644 runtime/confirm-binary-only.txt         $(DESTDIR)$(pkgdatadir)/
	install -m0644 runtime/missing-data.txt                $(DESTDIR)$(pkgdatadir)/
	install -m0644 out/launch-*.json                       $(DESTDIR)$(pkgdatadir)/
	install -d                                             $(DESTDIR)/etc/apparmor.d/
	install -m0644 etc/apparmor.d/*                        $(DESTDIR)/etc/apparmor.d/

	mkdir -p $(DESTDIR)/usr/share/bash-completion/completions
	install -m0644 data/bash-completion/game-data-packager $(DESTDIR)/usr/share/bash-completion/completions/
	sed -i 's#pkgdatadir=.*#pkgdatadir=$(pkgdatadir)#g' $(DESTDIR)/usr/share/bash-completion/completions/game-data-packager

	mkdir -p $(DESTDIR)/usr/share/man/man6/
	mkdir -p $(DESTDIR)/usr/share/man/fr/man6/
	install -m0644 doc/game-data-packager.6                $(DESTDIR)/usr/share/man/man6/
	install -m0644 doc/game-data-packager.fr.6             $(DESTDIR)/usr/share/man/fr/man6/game-data-packager.6

	mkdir -p $(DESTDIR)/etc/game-data-packager
	install -m0644 etc/game-data-packager.conf             $(DESTDIR)/etc/
	install -m0644 etc/*-mirrors                           $(DESTDIR)/etc/game-data-packager/

	mkdir -p $(DESTDIR)/usr/share/applications
	mkdir -p $(DESTDIR)/usr/share/pixmaps
	install -m0755 runtime/doom2-masterlevels.py           $(DESTDIR)$(bindir)/doom2-masterlevels
	install -m0644 out/doom2-masterlevels.desktop          $(DESTDIR)/usr/share/applications/
	install -m0644 doc/doom2-masterlevels.6                $(DESTDIR)/usr/share/man/man6/
	install -m0644 out/doom-common.png                     $(DESTDIR)/usr/share/pixmaps/doom2-masterlevels.png

# Requires additional setup, so not part of "make check"
manual-check:
	install -d out/manual-check/
	for game in $(TEST_SUITE); do \
	        GDP_MIRROR=$(GDP_MIRROR) GDP_UNINSTALLED=1 PYTHONPATH=. \
		python3 -m game_data_packager.command_line -d ./out/manual-check --no-compress $$game --no-search || exit $$?; \
	done
	rm -fr out/manual-check/

html: $(DIRS) $(json)
	LC_ALL=C GDP_UNINSTALLED=1 PYTHONPATH=. python3 -m tools.babel
	rsync out/index.html alioth.debian.org:/var/lib/gforge/chroot/home/groups/pkg-games/htdocs/game-data/ -e ssh -v

.PHONY: default clean check manual-check install html
