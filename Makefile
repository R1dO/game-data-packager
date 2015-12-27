# Makefile - used for building icon

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

obj = \
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
	build/quake3.png \
	build/quake3-teamarena.png \
	build/quake4.svg \
	build/48/quake3.png \
	build/48/quake3-teamarena.png \
	$(patsubst %,build/%/quake.png,$(layer_sizes)) \
	$(patsubst %,build/%/quake-armagon.png,$(layer_sizes)) \
	$(patsubst %,build/%/quake-dissolution.png,$(layer_sizes)) \
	$(patsubst %,build/%/quake2.png,$(layer_sizes)) \
	$(patsubst %,build/%/quake2-reckoning.png,$(layer_sizes)) \
	$(patsubst %,build/%/quake2-groundzero.png,$(layer_sizes)) \
	$(patsubst %,build/%/quake4.png,$(layer_sizes)) \
	$(NULL)

all: $(obj)

build/quake: quake.in
	install -d build
	sed -e 's/@self@/quake/g' \
		-e 's/@role@/client/g' \
		-e 's/@options@//g' \
		-e 's/@alternative@/quake-engine/g' \
		< $< > $@
	chmod +x $@

build/quake2: quake2.in
	install -d build
	sed -e 's/@self@/quake2/g' \
		-e 's/@role@/client/g' \
		-e 's/@options@//g' \
		-e 's/@alternative@/quake2-engine/g' \
		< $< > $@
	chmod +x $@

build/quake3: quake3.in Makefile
	install -d build
	sed \
		-e 's!@IOQ3BINARY@!ioquake3!' \
		-e 's!@IOQ3SELF@!quake3!' \
		-e 's!@IOQ3ROLE@!client!' \
		< $< > $@
	chmod +x $@

build/quake4: quake4.in Makefile
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
		< $< > $@
	chmod +x $@

build/README.quake4-bin: README.binary.in Makefile
	install -d build
	sed \
		-e 's!@id@!quake4!' \
		-e 's!@shortname@!Quake 4!' \
		-e 's!@distro@!$(distro)!' \
		< $< > $@

build/etqw: quake4.in Makefile
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
		< $< > $@
	chmod +x $@

build/README.etqw-bin: README.binary.in Makefile
	install -d build
	sed \
		-e 's!@id@!etqw!' \
		-e 's!@shortname@!ETQW!' \
		-e 's!@distro@!$(distro)!' \
		< $< > $@

build/quake2-server: quake2.in
	install -d build
	sed -e 's/@self@/quake2-server/g' \
		-e 's/@role@/dedicated server/g' \
		-e 's/@options@/+set dedicated 1/g' \
		-e 's/@alternative@/quake2-engine-server/g' \
		< $< > $@
	chmod +x $@

build/quake-server: quake.in
	install -d build
	sed -e 's/@self@/quake-server/g' \
		-e 's/@role@/server/g' \
		-e 's/@options@/-dedicated/g' \
		-e 's/@alternative@/quake-engine-server/g' \
		< $< > $@
	chmod +x $@

build/quake3-server: quake3.in Makefile
	install -d build
	sed \
		-e 's!@IOQ3BINARY@!ioq3ded!' \
		-e 's!@IOQ3SELF@!quake3-server!' \
		-e 's!@IOQ3ROLE@!server!' \
		< $< > $@
	chmod +x $@

build/quake4-dedicated: quake4.in Makefile
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
		< $< > $@
	chmod +x $@

build/etqw-dedicated: quake4.in Makefile
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
		< $< > $@
	chmod +x $@

build/tmp/recolour-dissolution.svg: quake1+2.svg Makefile
	install -d build/tmp
	sed -e 's/#c17d11/#999984/' \
		-e 's/#d5b582/#dede95/' \
		-e 's/#5f3b01/#403f31/' \
		-e 's/#e9b96e/#dede95/' \
		< $< > $@

build/tmp/recolour-armagon.svg: quake1+2.svg Makefile
	install -d build/tmp
	sed -e 's/#c17d11/#565248/' \
		-e 's/#d5b582/#aba390/' \
		-e 's/#5f3b01/#000000/' \
		-e 's/#e9b96e/#aba390/' \
		< $< > $@

build/tmp/recolour-reckoning.svg: quake1+2.svg Makefile
	install -d build/tmp
	sed -e 's/#3a5a1e/#999984/' \
		-e 's/#73ae3a/#eeeeec/' \
		-e 's/#8ae234/#eeeeec/' \
		-e 's/#132601/#233436/' \
		< $< > $@

build/tmp/recolour-groundzero.svg: quake1+2.svg Makefile
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

$(patsubst %,build/%/quake.png,$(layer_sizes)): build/%/quake.png: quake1+2.svg
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

$(patsubst %,build/%/quake2.png,$(layer_sizes)): build/%/quake2.png: quake1+2.svg
	install -d build/$*
	inkscape \
		--export-area=0:0:$*:$* \
		--export-width=$* \
		--export-height=$* \
		--export-id=layer-quake2-$* \
		--export-id-only \
		--export-png=$@ \
		$<

$(patsubst %,build/%/quake4.png,16 22 32): build/%/quake4.png: quake1+2.svg
	install -d build/$*
	inkscape \
		--export-area=0:0:32:32 \
		--export-width=$* \
		--export-height=$* \
		--export-id=layer-quake4-32 \
		--export-id-only \
		--export-png=$@ \
		$<

$(patsubst %,build/%/quake4.png,48 256): build/%/quake4.png: quake1+2.svg
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

build/quake.svg: quake1+2.svg Makefile
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

build/quake2.svg: quake1+2.svg Makefile
	install -d build
	xmlstarlet ed -d "//*[local-name() = 'g' and @inkscape:groupmode = 'layer' and @id != 'layer-quake2-256']" < $< > build/tmp/quake2.svg
	inkscape \
		--export-area-page \
		--export-plain-svg=$@ \
		build/tmp/quake2.svg
	rm -f build/tmp/quake2.svg

build/quake4.svg: quake1+2.svg Makefile
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

build/quake3.png: quake3-tango.xcf
	install -d build
	xcf2png -o $@ $<

build/quake3-teamarena.png: quake3-teamarena-tango.xcf
	install -d build
	xcf2png -o $@ $<

build/48/quake3.png: build/quake3.png Makefile
	install -d build/48
	convert -resize 48x48 $< $@

build/48/quake3-teamarena.png: build/quake3-teamarena.png Makefile
	install -d build/48
	convert -resize 48x48 $< $@

check:
	set -e; \
	failed=0; \
	for x in $(text); do \
		if grep -E "@[a-zA-Z]|[a-zA-Z]@" $$x; then \
			echo "^ probably a missing substitution?"; \
			failed=1; \
		fi; \
	done; exit $$failed

.PHONY: check
