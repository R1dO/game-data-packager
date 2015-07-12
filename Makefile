VERSION := $(shell dpkg-parsechangelog | grep ^Version | cut -d' ' -f2-)
DIRS := ./out
GDP_MIRROR ?= localhost

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
json      := $(patsubst ./data/%.yaml,./out/%.json,$(in_yaml))
copyright := $(patsubst ./data/%,./out/%,$(wildcard ./data/*.copyright))
dot_in    := $(patsubst ./data/%,./out/%,$(wildcard ./data/*.in))

default: $(DIRS) $(png) $(svgz) $(json) $(copyright) $(dot_in) \
      out/bash_completion out/changelog.gz out/copyright out/game-data-packager

out/%: data/%
	if [ -L $< ]; then cp -a $< $@ ; else install -m644 $< $@ ; fi

out/%.json: data/%.yaml
	python3 tools/yaml2json.py $< > $@ || rm -f $@

out/bash_completion: $(in_yaml)
	python3 tools/bash_completion.py > ./out/bash_completion
	chmod 0644 ./out/bash_completion

out/changelog.gz: debian/changelog
	gzip -nc9 debian/changelog > ./out/changelog.gz
	chmod 0644 ./out/changelog.gz

out/game-data-packager: run
	install -m644 run out/game-data-packager

out/memento-mori.svg: data/memento-mori-2.svg
	inkscape --export-plain-svg=$@ --export-id=layer1 --export-id-only $<

out/memento-mori.png: out/memento-mori.svg
	inkscape --export-png=$@ -w96 -h96 $<

out/%.png: data/%.xpm
	convert $< $@

out/%.png: data/%.svg
	inkscape --export-png=$@ -w96 -h96 $<

out/%.svgz: data/%.svg
	gzip -nc $< > $@

$(DIRS):
	mkdir -p $@

clean:
	rm -f ./out/bash_completion
	rm -f ./out/changelog.gz
	rm -f ./out/copyright
	rm -f ./out/game-data-packager
	rm -f ./out/*.control.in
	rm -f ./out/*.copyright
	rm -f ./out/*.copyright.in
	rm -f ./out/*.desktop.in
	rm -f ./out/*.preinst.in
	rm -f ./out/*.png
	rm -f ./out/*.svgz
	rm -f ./out/*.svg
	rm -f ./out/*.json
	rm -rf game_data_packager/__pycache__
	for d in $(DIRS); do [ ! -d "$$d" ]  || rmdir "$$d"; done

check:
	LC_ALL=C GDP_UNINSTALLED=1 PYTHONPATH=. python3 tools/check_syntax.py
	LC_ALL=C pyflakes3 game_data_packager/*.py game_data_packager/*/*.py runtime/*.py tools/*.py || :

# Requires additional setup, so not part of "make check"
manual-check:
	install -d tmp/
	for game in $(TEST_SUITE); do \
	        GDP_MIRROR=$(GDP_MIRROR) GDP_UNINSTALLED=1 PYTHONPATH=. \
		python3 -m game_data_packager -d ./tmp --no-search --no-compress $$game || exit $$?; \
	done
	rm -fr tmp/

.PHONY: default clean check manual-check
