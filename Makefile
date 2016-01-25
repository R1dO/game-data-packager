GDP_MIRROR ?= localhost
bindir := /usr/games
datadir := /usr/share/games
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

out/%: data/%
	@mkdir -p out
	if [ -L $< ]; then cp -a $< $@ ; else install -m644 $< $@ ; fi

out/vfs/%.json: data/%.yaml
	@mkdir -p out/vfs
	$(PYTHON) tools/compile_yaml.py $< $@

out/vfs.zip: $(json)
	@mkdir -p out
	rm -f out/vfs.zip
	if [ -n "$(BUILD_DATE)" ]; then \
		touch --date='$(BUILD_DATE)' out/vfs/*; \
	fi
	cd out/vfs && ls -1 | LC_ALL=C sort | \
		env TZ=UTC zip ../vfs.zip -9 -X -q -@

out/bash_completion: $(in_yaml)
	@mkdir -p out
	$(PYTHON) tools/bash_completion.py > ./out/bash_completion
	chmod 0644 ./out/bash_completion

out/changelog.gz: debian/changelog
	@mkdir -p out
	gzip -nc9 debian/changelog > ./out/changelog.gz
	chmod 0644 ./out/changelog.gz

out/game-data-packager: run
	@mkdir -p out
	install run out/game-data-packager

out/%.svg: data/%.svg
	@mkdir -p out
	inkscape --export-plain-svg=$@ $<

out/memento-mori.svg: data/memento-mori-2.svg
	@mkdir -p out
	inkscape --export-plain-svg=$@ --export-id=layer1 --export-id-only $<

out/memento-mori.png: out/memento-mori.svg
	inkscape --export-png=$@ -w96 -h96 $<

out/%.png: data/%.xpm
	@mkdir -p out
	convert $< $@

out/%.png: data/%.svg
	@mkdir -p out
	inkscape --export-png=$@ -w96 -h96 $<

out/%.svgz: out/%.svg
	gzip -nc $< > $@

out/launch-%.json: out/launch-%.yaml
	@mkdir -p out
	$(PYTHON) tools/yaml2json.py $< $@

out/%: runtime/%.in
	@mkdir -p out
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

	mkdir -p $(DESTDIR)$(datadir)/game-data-packager
	cp -ar game_data_packager/                             $(DESTDIR)$(datadir)/game-data-packager/
	python3 -m game_data_packager.version >                $(DESTDIR)$(datadir)/game-data-packager/game_data_packager/version.py
	install -m0644 out/*.copyright                         $(DESTDIR)$(datadir)/game-data-packager/
	install -m0644 out/*.png                               $(DESTDIR)$(datadir)/game-data-packager/
	install -m0644 out/*.svgz                              $(DESTDIR)$(datadir)/game-data-packager/
	install -m0644 out/bash_completion                     $(DESTDIR)$(datadir)/game-data-packager/
	install -m0644 out/changelog.gz                        $(DESTDIR)$(datadir)/game-data-packager/
	install -m0644 out/copyright                           $(DESTDIR)$(datadir)/game-data-packager/
	install -m0644 out/vfs.zip                             $(DESTDIR)$(datadir)/game-data-packager/

	install runtime/launcher.py                            $(DESTDIR)$(datadir)/game-data-packager/gdp-launcher
	install -m0644 out/*.desktop                           $(DESTDIR)$(datadir)/game-data-packager/
	install -m0644 runtime/confirm-binary-only.txt         $(DESTDIR)$(datadir)/game-data-packager/
	install -m0644 runtime/missing-data.txt                $(DESTDIR)$(datadir)/game-data-packager/
	install -m0644 out/launch-*.json                       $(DESTDIR)$(datadir)/game-data-packager/
	install -d                                             $(DESTDIR)/etc/apparmor.d/
	install -m0644 etc/apparmor.d/*                        $(DESTDIR)/etc/apparmor.d/

	mkdir -p $(DESTDIR)/usr/share/bash-completion/completions
	install -m0644 data/bash-completion/game-data-packager $(DESTDIR)/usr/share/bash-completion/completions/
ifneq ($(datadir),/usr/share/games)
	sed -i 's#/usr/share/games#$(datadir)#g' $(DESTDIR)/usr/share/bash-completion/completions/game-data-packager
endif

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
	install -d tmp/
	for game in $(TEST_SUITE); do \
	        GDP_MIRROR=$(GDP_MIRROR) GDP_UNINSTALLED=1 PYTHONPATH=. \
		python3 -m game_data_packager.command_line -d ./tmp --no-compress $$game --no-search || exit $$?; \
	done
	rm -fr tmp/

html: $(DIRS) $(json)
	LC_ALL=C GDP_UNINSTALLED=1 PYTHONPATH=. python3 -m tools.babel
	rsync out/index.html alioth.debian.org:/var/lib/gforge/chroot/home/groups/pkg-games/htdocs/game-data/ -e ssh -v

.PHONY: default clean check manual-check install html
