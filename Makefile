bindir := /usr/games
datadir := /usr/share/games
pkgdatadir := ${datadir}/game-data-packager
runtimedir := ${datadir}/game-data-packager-runtime
PYTHON := python3
PYFLAKES3 := $(shell if [ -x /usr/bin/pyflakes3 ] ;  then echo pyflakes3 ; \
                   elif [ -x /usr/bin/pyflakes3k ] ; then echo pyflakes3k ; \
                   elif [ -x /usr/bin/python3-pyflakes ] ; then echo python3-pyflakes ; \
                   else ls -1 /usr/bin/pyflakes-python3.* | tail -n 1 ; \
                    fi)

png_from_xpm := $(patsubst ./data/%.xpm,./out/%.png,$(wildcard ./data/*.xpm))
png_from_svg := $(patsubst ./data/%.svg,./out/%.png,$(wildcard ./data/*.svg))
png       := $(png_from_xpm) $(png_from_svg) out/memento-mori.png
simplified_svg := $(patsubst ./data/%.svg,./out/%.svg,$(wildcard ./data/*.svg))
# We deliberately don't compress and install memento-mori{,-2}.svg because
# they use features that aren't supported by librsvg, so they'd look wrong
# in all GTK-based environments.
svgz      := $(patsubst ./out/%.svg,./out/%.svgz,$(filter-out ./out/memento-mori-2.svg,$(simplified_svg)))
in_yaml   := $(wildcard ./data/*.yaml)
json_from_data := $(patsubst ./data/%.yaml,./out/vfs/%.json,$(in_yaml))
json_from_runtime := $(patsubst ./runtime/%.yaml.in,./out/%.json,$(wildcard ./runtime/*.yaml.in))
copyright := $(patsubst ./data/%,./out/%,$(wildcard ./data/*.copyright) ./data/copyright)
dot_in    := $(patsubst ./data/%,./out/%,$(wildcard ./data/*.in))
desktop   := $(patsubst ./runtime/%.in,./out/%,$(wildcard ./runtime/*.desktop.in))

default: $(png) $(svgz) $(json_from_data) $(json_from_runtime) \
      $(copyright) $(dot_in) $(desktop) \
      out/bash_completion out/changelog.gz \
      out/game-data-packager out/vfs.zip out/memento-mori-2.svg

out/CACHEDIR.TAG:
	@mkdir -p out
	( echo "Signature: 8a477f597d28d17""2789f06886806bc55"; \
	echo "# This file marks this directory to not be backed up."; \
	echo "# For information about cache directory tags, see:"; \
	echo "#	http://www.brynosaurus.com/cachedir/" ) > $@

$(copyright) $(dot_in): out/%: data/% out/CACHEDIR.TAG
	if [ -L $< ]; then cp -a $< $@ ; else install -m644 $< $@ ; fi

$(json_from_data): out/vfs/%.json: data/%.yaml tools/compile_yaml.py out/CACHEDIR.TAG
	@mkdir -p out/vfs
	$(PYTHON) tools/compile_yaml.py $< $@

out/vfs.zip: $(json_from_data)
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

$(simplified_svg): out/%.svg: data/%.svg out/CACHEDIR.TAG
	inkscape --export-plain-svg=$@ $<

out/memento-mori.svg: data/memento-mori-2.svg out/CACHEDIR.TAG
	inkscape --export-plain-svg=$@ --export-id=layer1 --export-id-only $<

out/memento-mori.png: out/memento-mori.svg
	inkscape --export-png=$@ -w96 -h96 $<

$(png_from_xpm): out/%.png: data/%.xpm out/CACHEDIR.TAG
	convert $< $@

$(png_from_svg): out/%.png: data/%.svg out/CACHEDIR.TAG
	inkscape --export-png=$@ -w96 -h96 $<

$(svgz): out/%.svgz: out/%.svg
	gzip -nc $< > $@

$(json_from_runtime): out/launch-%.json: out/launch-%.yaml
	$(PYTHON) tools/yaml2json.py $< $@

$(desktop) $(patsubst %.json,%.yaml,$(json_from_runtime)): out/%: runtime/%.in out/CACHEDIR.TAG
	PYTHONPATH=. $(PYTHON) tools/expand_vars.py $< $@

clean:
	rm -fr out
	rm -rf game_data_packager/__pycache__
	rm -rf game_data_packager/games/__pycache__
	rm -rf tools/__pycache__

check:
	LC_ALL=C $(PYFLAKES3) game_data_packager/*.py game_data_packager/*/*.py runtime/*.py tests/*.py tools/*.py || :
	LC_ALL=C GDP_UNINSTALLED=1 PYTHONPATH=. $(PYTHON) tests/deb.py
	LC_ALL=C GDP_UNINSTALLED=1 PYTHONPATH=. $(PYTHON) tests/hashed_file.py
	LC_ALL=C GDP_UNINSTALLED=1 PYTHONPATH=. $(PYTHON) tests/integration.py
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
	install -m0644 out/*.control.in                        $(DESTDIR)$(pkgdatadir)/
	install -m0644 out/*.copyright                         $(DESTDIR)$(pkgdatadir)/
	install -m0644 out/*.png                               $(DESTDIR)$(pkgdatadir)/
	install -m0644 out/*.preinst.in                        $(DESTDIR)$(pkgdatadir)/
	install -m0644 out/*.svgz                              $(DESTDIR)$(pkgdatadir)/
	install -m0644 out/bash_completion                     $(DESTDIR)$(pkgdatadir)/
	install -m0644 out/changelog.gz                        $(DESTDIR)$(pkgdatadir)/
	install -m0644 out/copyright                           $(DESTDIR)$(pkgdatadir)/
	install -m0644 out/vfs.zip                             $(DESTDIR)$(pkgdatadir)/

	install -d                                             $(DESTDIR)$(runtimedir)/
	install runtime/launcher.py                            $(DESTDIR)$(runtimedir)/gdp-launcher
	install runtime/openurl.py                             $(DESTDIR)$(runtimedir)/gdp-openurl
	install -m0644 out/*.desktop                           $(DESTDIR)$(runtimedir)/
	install -m0644 runtime/confirm-binary-only.txt         $(DESTDIR)$(runtimedir)/
	install -m0644 runtime/missing-data.txt                $(DESTDIR)$(runtimedir)/
	install -m0644 out/launch-*.json                       $(DESTDIR)$(runtimedir)/
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

html: $(DIRS) $(json)
	LC_ALL=C GDP_UNINSTALLED=1 PYTHONPATH=. python3 -m tools.babel
	rsync out/index.html alioth.debian.org:/var/lib/gforge/chroot/home/groups/pkg-games/htdocs/game-data/ -e ssh -v

.PHONY: default clean check install html
