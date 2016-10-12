# Makefile - used for building icon

bindir ?= /usr/bin
libdir ?= /usr/lib
datadir ?= /usr/share
assets ?= $(datadir)
distro ?= $(shell lsb_release -si)

layer_sizes = 16 22 32 48 256

text = \
	build/quake \
	build/quake2 \
	build/quake3 \
	build/quake4 \
	build/etqw \
	build/quake-server \
	build/quake2-server \
	build/quake3-server \
	build/quake4-dedicated \
	build/etqw-dedicated \
	build/README.etqw-bin \
	build/README.quake4-bin \
	$(NULL)

desktop = \
	$(patsubst runtime/%.in,build/%,$(wildcard runtime/*.desktop.in)) \
	$(NULL)

obj = \
	$(desktop) \
	$(text) \
	build/24/quake.png \
	build/24/quake-armagon.png \
	build/24/quake-dissolution.png \
	build/24/quake2.png \
	build/24/quake2-reckoning.png \
	build/24/quake2-groundzero.png \
	build/24/quake4.png \
	build/quake.svg \
	build/quake-armagon.svg \
	build/quake-dissolution.svg \
	build/quake2.svg \
	build/quake2-reckoning.svg \
	build/quake2-groundzero.svg \
	build/256/quake3.png \
	build/256/quake3-team-arena.png \
	build/quake4.svg \
	build/48/quake3.png \
	build/48/quake3-team-arena.png \
	$(patsubst %,build/%/quake.png,$(layer_sizes)) \
	$(patsubst %,build/%/quake-armagon.png,$(layer_sizes)) \
	$(patsubst %,build/%/quake-dissolution.png,$(layer_sizes)) \
	$(patsubst %,build/%/quake2.png,$(layer_sizes)) \
	$(patsubst %,build/%/quake2-reckoning.png,$(layer_sizes)) \
	$(patsubst %,build/%/quake2-groundzero.png,$(layer_sizes)) \
	$(patsubst %,build/%/quake4.png,$(layer_sizes)) \
	$(NULL)

all: $(obj)

build/quake: runtime/quake.in
	install -d build
	sed -e 's/@self@/quake/g' \
		-e 's/@role@/client/g' \
		-e 's/@options@//g' \
		-e 's/@alternative@/quake-engine/g' \
		< $< > $@
	chmod +x $@

build/quake2: runtime/quake2.in
	install -d build
	sed -e 's/@self@/quake2/g' \
		-e 's/@role@/client/g' \
		-e 's/@options@//g' \
		-e 's/@alternative@/quake2-engine/g' \
		< $< > $@
	chmod +x $@

build/quake3: runtime/quake3.in Makefile
	install -d build
	sed \
		-e 's!@IOQ3BINARY@!ioquake3!' \
		-e 's!@IOQ3SELF@!quake3!' \
		-e 's!@IOQ3ROLE@!client!' \
		< $< > $@
	chmod +x $@

build/quake4: runtime/quake4.in Makefile
	install -d build
	sed \
		-e 's!@id@!quake4!' \
		-e 's!@icon@!/usr/share/icons/hicolor/48x48/apps/quake4.png!' \
		-e 's!@longname@!Quake 4!' \
		-e 's!@shortname@!Quake 4!' \
		-e 's!@binary@!quake4.x86!' \
		-e 's!@smpbinary@!quake4smp.x86!' \
		-e 's!@self@!quake4!' \
		-e 's!@role@!client!' \
		-e 's!@pkglibdir@!/usr/lib/quake4!' \
		-e 's!@paks@!pak001 pak021 pak022 zpak_english!' \
		-e 's!@basegame@!q4base!' \
		-e 's!@dotdir@!quake4!' \
		< $< > $@
	chmod +x $@

build/README.quake4-bin: runtime/README.binary.in Makefile
	install -d build
	sed \
		-e 's!@id@!quake4!' \
		-e 's!@shortname@!Quake 4!' \
		-e 's!@distro@!$(distro)!' \
		< $< > $@

build/etqw: runtime/quake4.in Makefile
	install -d build
	sed \
		-e 's!@id@!etqw!' \
		-e 's!@icon@!/usr/share/pixmaps/etqw.png!' \
		-e 's!@longname@!Enemy Territory: Quake Wars!' \
		-e 's!@shortname@!ETQW!' \
		-e 's!@binary@!etqw.x86!' \
		-e 's!@smpbinary@!etqw-rthread.x86!' \
		-e 's!@self@!etqw!' \
		-e 's!@role@!client!' \
		-e 's!@pkglibdir@!/usr/lib/etqw!' \
		-e 's!@paks@!pak008 game000 pak000 zpak_english000!' \
		-e 's!@basegame@!base!' \
		-e 's!@dotdir@!etqwcl!' \
		< $< > $@
	chmod +x $@

build/README.etqw-bin: runtime/README.binary.in Makefile
	install -d build
	sed \
		-e 's!@id@!etqw!' \
		-e 's!@shortname@!ETQW!' \
		-e 's!@distro@!$(distro)!' \
		< $< > $@

build/quake2-server: runtime/quake2.in
	install -d build
	sed -e 's/@self@/quake2-server/g' \
		-e 's/@role@/dedicated server/g' \
		-e 's/@options@/+set dedicated 1/g' \
		-e 's/@alternative@/quake2-engine-server/g' \
		< $< > $@
	chmod +x $@

build/quake-server: runtime/quake.in
	install -d build
	sed -e 's/@self@/quake-server/g' \
		-e 's/@role@/server/g' \
		-e 's/@options@/-dedicated/g' \
		-e 's/@alternative@/quake-engine-server/g' \
		< $< > $@
	chmod +x $@

build/quake3-server: runtime/quake3.in Makefile
	install -d build
	sed \
		-e 's!@IOQ3BINARY@!ioq3ded!' \
		-e 's!@IOQ3SELF@!quake3-server!' \
		-e 's!@IOQ3ROLE@!server!' \
		< $< > $@
	chmod +x $@

build/quake4-dedicated: runtime/quake4.in Makefile
	install -d build
	sed \
		-e 's!@id@!quake4!' \
		-e 's!@icon@!/usr/share/icons/hicolor/48x48/apps/quake4.png!' \
		-e 's!@longname@!Quake 4!' \
		-e 's!@shortname@!Quake 4!' \
		-e 's!@binary@!q4ded.x86!' \
		-e 's!@smpbinary@!!' \
		-e 's!@self@!quake4-dedicated!' \
		-e 's!@role@!server!' \
		-e 's!@pkglibdir@!/usr/lib/quake4!' \
		-e 's!@paks@!pak001 pak021 pak022 zpak_english!' \
		-e 's!@basegame@!q4base!' \
		-e 's!@dotdir@!quake4!' \
		< $< > $@
	chmod +x $@

build/etqw-dedicated: runtime/quake4.in Makefile
	install -d build
	sed \
		-e 's!@id@!etqw!' \
		-e 's!@icon@!/usr/share/pixmaps/etqw.png!' \
		-e 's!@longname@!Enemy Territory: Quake Wars!' \
		-e 's!@shortname@!ETQW!' \
		-e 's!@binary@!etqwded.x86!' \
		-e 's!@smpbinary@!!' \
		-e 's!@self@!etqw-dedicated!' \
		-e 's!@role@!server!' \
		-e 's!@pkglibdir@!/usr/lib/etqw!' \
		-e 's!@paks@!pak008 game000 pak000 zpak_english000!' \
		-e 's!@basegame@!base!' \
		-e 's!@dotdir@!etqw!' \
		< $< > $@
	chmod +x $@

build/tmp/recolour-dissolution.svg: data/quake1+2.svg Makefile
	install -d build/tmp
	sed -e 's/#c17d11/#999984/' \
		-e 's/#d5b582/#dede95/' \
		-e 's/#5f3b01/#403f31/' \
		-e 's/#e9b96e/#dede95/' \
		< $< > $@

build/tmp/recolour-armagon.svg: data/quake1+2.svg Makefile
	install -d build/tmp
	sed -e 's/#c17d11/#565248/' \
		-e 's/#d5b582/#aba390/' \
		-e 's/#5f3b01/#000000/' \
		-e 's/#e9b96e/#aba390/' \
		< $< > $@

build/tmp/recolour-reckoning.svg: data/quake1+2.svg Makefile
	install -d build/tmp
	sed -e 's/#3a5a1e/#999984/' \
		-e 's/#73ae3a/#eeeeec/' \
		-e 's/#8ae234/#eeeeec/' \
		-e 's/#132601/#233436/' \
		< $< > $@

build/tmp/recolour-groundzero.svg: data/quake1+2.svg Makefile
	install -d build/tmp
	sed -e 's/#3a5a1e/#ce5c00/' \
		-e 's/#73ae3a/#fce94f/' \
		-e 's/#8ae234/#fce94f/' \
		-e 's/#132601/#cc0000/' \
		< $< > $@

build/24/quake.png: build/22/quake.png
	install -d build/24
	convert -bordercolor Transparent -border 1x1 $< $@

build/24/quake-%.png: build/22/quake-%.png
	install -d build/24
	convert -bordercolor Transparent -border 1x1 $< $@

build/24/quake2.png: build/22/quake2.png
	install -d build/24
	convert -bordercolor Transparent -border 1x1 $< $@

build/24/quake4.png: build/22/quake4.png
	install -d build/24
	convert -bordercolor Transparent -border 1x1 $< $@

build/24/quake2-%.png: build/22/quake2-%.png
	install -d build/24
	convert -bordercolor Transparent -border 1x1 $< $@

$(patsubst %,build/%/quake.png,$(layer_sizes)): build/%/quake.png: data/quake1+2.svg
	install -d build/$*
	inkscape \
		--export-area=0:0:$*:$* \
		--export-width=$* \
		--export-height=$* \
		--export-id=layer-quake-$* \
		--export-id-only \
		--export-png=$@ \
		$<

$(patsubst %,build/%/quake-armagon.png,$(layer_sizes)): build/%/quake-armagon.png: build/tmp/recolour-armagon.svg
	install -d build/$*
	inkscape \
		--export-area=0:0:$*:$* \
		--export-width=$* \
		--export-height=$* \
		--export-id=layer-quake-$* \
		--export-id-only \
		--export-png=$@ \
		$<

$(patsubst %,build/%/quake-dissolution.png,$(layer_sizes)): build/%/quake-dissolution.png: build/tmp/recolour-dissolution.svg
	install -d build/$*
	inkscape \
		--export-area=0:0:$*:$* \
		--export-width=$* \
		--export-height=$* \
		--export-id=layer-quake-$* \
		--export-id-only \
		--export-png=$@ \
		$<

$(patsubst %,build/%/quake2.png,$(layer_sizes)): build/%/quake2.png: data/quake1+2.svg
	install -d build/$*
	inkscape \
		--export-area=0:0:$*:$* \
		--export-width=$* \
		--export-height=$* \
		--export-id=layer-quake2-$* \
		--export-id-only \
		--export-png=$@ \
		$<

$(patsubst %,build/%/quake4.png,16 22 32): build/%/quake4.png: data/quake1+2.svg
	install -d build/$*
	inkscape \
		--export-area=0:0:32:32 \
		--export-width=$* \
		--export-height=$* \
		--export-id=layer-quake4-32 \
		--export-id-only \
		--export-png=$@ \
		$<

$(patsubst %,build/%/quake4.png,48 256): build/%/quake4.png: data/quake1+2.svg
	install -d build/$*
	inkscape \
		--export-area=0:0:$*:$* \
		--export-width=$* \
		--export-height=$* \
		--export-id=layer-quake4-$* \
		--export-id-only \
		--export-png=$@ \
		$<

$(patsubst %,build/%/quake2-reckoning.png,$(layer_sizes)): build/%/quake2-reckoning.png: build/tmp/recolour-reckoning.svg
	install -d build/$*
	inkscape \
		--export-area=0:0:$*:$* \
		--export-width=$* \
		--export-height=$* \
		--export-id=layer-quake2-$* \
		--export-id-only \
		--export-png=$@ \
		$<

$(patsubst %,build/%/quake2-groundzero.png,$(layer_sizes)): build/%/quake2-groundzero.png: build/tmp/recolour-groundzero.svg
	install -d build/$*
	inkscape \
		--export-area=0:0:$*:$* \
		--export-width=$* \
		--export-height=$* \
		--export-id=layer-quake2-$* \
		--export-id-only \
		--export-png=$@ \
		$<

clean:
	rm -rf build

build/quake.svg: data/quake1+2.svg Makefile
	install -d build
	xmlstarlet ed -d "//*[local-name() = 'g' and @inkscape:groupmode = 'layer' and @id != 'layer-quake-256']" < $< > build/tmp/quake.svg
	inkscape \
		--export-area-page \
		--export-plain-svg=$@ \
		build/tmp/quake.svg
	rm -f build/tmp/quake.svg

build/quake-%.svg: build/tmp/recolour-%.svg Makefile
	install -d build
	xmlstarlet ed -d "//*[local-name() = 'g' and @inkscape:groupmode = 'layer' and @id != 'layer-quake-256']" < $< > build/tmp/quake-$*.svg
	inkscape \
		--export-area-page \
		--export-plain-svg=$@ \
		build/tmp/quake-$*.svg
	rm -f build/tmp/quake-$*.svg

build/quake2.svg: data/quake1+2.svg Makefile
	install -d build
	xmlstarlet ed -d "//*[local-name() = 'g' and @inkscape:groupmode = 'layer' and @id != 'layer-quake2-256']" < $< > build/tmp/quake2.svg
	inkscape \
		--export-area-page \
		--export-plain-svg=$@ \
		build/tmp/quake2.svg
	rm -f build/tmp/quake2.svg

build/quake4.svg: data/quake1+2.svg Makefile
	install -d build
	xmlstarlet ed -d "//*[local-name() = 'g' and @inkscape:groupmode = 'layer' and @id != 'layer-quake4-256']" < $< > build/tmp/quake4.svg
	inkscape \
		--export-area-page \
		--export-plain-svg=$@ \
		build/tmp/quake4.svg
	rm -f build/tmp/quake4.svg

build/quake2-%.svg: build/tmp/recolour-%.svg Makefile
	install -d build
	xmlstarlet ed -d "//*[local-name() = 'g' and @inkscape:groupmode = 'layer' and @id != 'layer-quake2-256']" < $< > build/tmp/quake2-$*.svg
	inkscape \
		--export-area-page \
		--export-plain-svg=$@ \
		build/tmp/quake2-$*.svg
	rm -f build/tmp/quake2-$*.svg

build/256/quake3.png: data/quake3-tango.xcf
	install -d build/256
	xcf2png -o $@ $<

build/256/quake3-team-arena.png: data/quake3-teamarena-tango.xcf
	install -d build/256
	xcf2png -o $@ $<

build/48/quake3.png: build/256/quake3.png Makefile
	install -d build/48
	convert -resize 48x48 $< $@

build/48/quake3-team-arena.png: build/256/quake3-team-arena.png Makefile
	install -d build/48
	convert -resize 48x48 $< $@

$(desktop): build/%: runtime/%.in
	install -d build
	sed \
		-e 's#[$$]{assets}#${assets}#g' \
		-e 's#[$$]{bindir}#${bindir}#g' \
		< $< > $@

check:
	set -e; \
	failed=0; \
	for x in $(text); do \
		if grep -E "@[a-zA-Z]|[a-zA-Z]@" $$x; then \
			echo "^ probably a missing substitution?"; \
			failed=1; \
		fi; \
	done; \
	for x in $(desktop); do \
		if grep -E "[$$][{a-z]" $$x; then \
			echo "^ probably a missing substitution?"; \
			failed=1; \
		fi; \
	done; \
	exit $$failed

.PHONY: check

install:
	install -d                                             $(DESTDIR)$(bindir)
	install -m755 build/quake                              $(DESTDIR)$(bindir)
	install -m755 build/quake-server                       $(DESTDIR)$(bindir)
	install -m755 build/quake2                             $(DESTDIR)$(bindir)
	install -m755 build/quake2-server                      $(DESTDIR)$(bindir)
	install -m755 build/quake3                             $(DESTDIR)$(bindir)
	install -m755 build/quake3-server                      $(DESTDIR)$(bindir)
	install -m755 build/quake4                             $(DESTDIR)$(bindir)
	install -m755 build/quake4-dedicated                   $(DESTDIR)$(bindir)
	install -m755 build/etqw                               $(DESTDIR)$(bindir)
	install -m755 build/etqw-dedicated                     $(DESTDIR)$(bindir)
	install -d                                             $(DESTDIR)$(datadir)/applications
	install -m644 $(desktop)                               $(DESTDIR)$(datadir)/applications
	install -d                                             $(DESTDIR)$(datadir)/icons/hicolor/16x16/apps
	install -m644 build/16/*.png                           $(DESTDIR)$(datadir)/icons/hicolor/16x16/apps
	install -d                                             $(DESTDIR)$(datadir)/icons/hicolor/22x22/apps
	install -m644 build/22/*.png                           $(DESTDIR)$(datadir)/icons/hicolor/22x22/apps
	install -d                                             $(DESTDIR)$(datadir)/icons/hicolor/24x24/apps
	install -m644 build/24/*.png                           $(DESTDIR)$(datadir)/icons/hicolor/24x24/apps
	install -d                                             $(DESTDIR)$(datadir)/icons/hicolor/32x32/apps
	install -m644 build/32/*.png                           $(DESTDIR)$(datadir)/icons/hicolor/32x32/apps
	install -d                                             $(DESTDIR)$(datadir)/icons/hicolor/48x48/apps
	install -m644 build/48/*.png                           $(DESTDIR)$(datadir)/icons/hicolor/48x48/apps
	install -d                                             $(DESTDIR)$(datadir)/icons/hicolor/256x256/apps
	install -m644 build/256/*.png                          $(DESTDIR)$(datadir)/icons/hicolor/256x256/apps
	install -d                                             $(DESTDIR)$(datadir)/icons/hicolor/scalable/apps
	install -m644 build/quake*.svg                         $(DESTDIR)$(datadir)/icons/hicolor/scalable/apps
	install -m644 build/quake-*.svg                        $(DESTDIR)$(datadir)/icons/hicolor/scalable/apps
	install -m644 build/quake2*.svg                        $(DESTDIR)$(datadir)/icons/hicolor/scalable/apps
	install -m644 build/quake4*.svg                        $(DESTDIR)$(datadir)/icons/hicolor/scalable/apps
	install -d                                             $(DESTDIR)$(datadir)/man/man6
	install -m644 doc/*.6                                  $(DESTDIR)$(datadir)/man/man6
	install -d                                             $(DESTDIR)$(assets)/quake
	install -m755 runtime/need-data.sh                     $(DESTDIR)$(assets)/quake
	install -d                                             $(DESTDIR)$(assets)/quake2
	install -m755 runtime/need-data.sh                     $(DESTDIR)$(assets)/quake2
	install -d                                             $(DESTDIR)$(assets)/quake3
	install -m644 runtime/README.quake3-data               $(DESTDIR)$(assets)/quake3
	install -m755 runtime/need-data.sh                     $(DESTDIR)$(assets)/quake3
	install -d                                             $(DESTDIR)$(libdir)/quake4
	install -m644 build/README.quake4-bin                  $(DESTDIR)$(libdir)/quake4
	install -m644 runtime/README.quake4-data               $(DESTDIR)$(libdir)/quake4
	install -m755 runtime/confirm-binary-only.sh           $(DESTDIR)$(libdir)/quake4
	install -m755 runtime/need-data.sh                     $(DESTDIR)$(libdir)/quake4
	install -d                                             $(DESTDIR)$(libdir)/etqw
	install -m644 build/README.etqw-bin                    $(DESTDIR)$(libdir)/etqw
	install -m644 runtime/README.etqw-data                 $(DESTDIR)$(libdir)/etqw
	install -m755 runtime/confirm-binary-only.sh           $(DESTDIR)$(libdir)/etqw
	install -m755 runtime/need-data.sh                     $(DESTDIR)$(libdir)/etqw

.PHONY: install
