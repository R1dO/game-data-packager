# Makefile - used for building icon

obj = \
	build/quake \
	build/quake2 \
	build/quake3 \
	build/quake-server \
	build/quake2-server \
	build/quake3-server \
	build/quake.xpm \
	build/quake2.xpm \
	build/16/quake.png \
	build/16/quake-armagon.png \
	build/16/quake-dissolution.png \
	build/16/quake2.png \
	build/22/quake.png \
	build/22/quake-armagon.png \
	build/22/quake-dissolution.png \
	build/22/quake2.png \
	build/24/quake.png \
	build/24/quake-armagon.png \
	build/24/quake-dissolution.png \
	build/24/quake2.png \
	build/32/quake.png \
	build/32/quake-armagon.png \
	build/32/quake-dissolution.png \
	build/32/quake2.png \
	build/48/quake.png \
	build/48/quake-armagon.png \
	build/48/quake-dissolution.png \
	build/48/quake2.png \
	build/256/quake.png \
	build/256/quake-armagon.png \
	build/256/quake-dissolution.png \
	build/256/quake2.png \
	build/quake.svg \
	build/quake-armagon.svg \
	build/quake-dissolution.svg \
	build/quake2.svg \
	build/quake3.png \
	build/quake3.xpm \
	build/quake332.xpm \
	build/quake3-teamarena.png \
	build/quake3-teamarena.xpm \
	build/quake3-teamarena32.xpm

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
		-e 's!@IOQ3SELF@!quake3!' \
		-e 's!@IOQ3ROLE@!server!' \
		< $< > $@
	chmod +x $@

build/tmp-dissolution.svg: quake1+2.svg Makefile
	install -d build
	sed -e 's/#c17d11/#999984/' \
		-e 's/#d5b582/#dede95/' \
		-e 's/#5f3b01/#403f31/' \
		-e 's/#e9b96e/#dede95/' \
		< $< > $@

build/tmp-armagon.svg: quake1+2.svg Makefile
	install -d build
	sed -e 's/#c17d11/#565248/' \
		-e 's/#d5b582/#aba390/' \
		-e 's/#5f3b01/#000000/' \
		-e 's/#e9b96e/#aba390/' \
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

build/%/quake.png: quake1+2.svg
	install -d build/$*
	inkscape \
		--export-area=0:0:$*:$* \
		--export-width=$* \
		--export-height=$* \
		--export-id=layer-quake-$* \
		--export-id-only \
		--export-png=$@ \
		$<

build/%/quake-armagon.png: build/tmp-armagon.svg
	install -d build/$*
	inkscape \
		--export-area=0:0:$*:$* \
		--export-width=$* \
		--export-height=$* \
		--export-id=layer-quake-$* \
		--export-id-only \
		--export-png=$@ \
		$<

build/%/quake-dissolution.png: build/tmp-dissolution.svg
	install -d build/$*
	inkscape \
		--export-area=0:0:$*:$* \
		--export-width=$* \
		--export-height=$* \
		--export-id=layer-quake-$* \
		--export-id-only \
		--export-png=$@ \
		$<

build/%/quake2.png: quake1+2.svg
	install -d build/$*
	inkscape \
		--export-area=0:0:$*:$* \
		--export-width=$* \
		--export-height=$* \
		--export-id=layer-quake2-$* \
		--export-id-only \
		--export-png=$@ \
		$<

build/%.xpm: build/32/%.png
	install -d build
	convert $< $@

clean:
	rm -rf build

build/quake.svg: quake1+2.svg Makefile
	install -d build
	xmlstarlet ed -d "//*[local-name() = 'g' and @id != 'layer-quake-256']" < $< > tmp.svg
	inkscape \
		--export-area-page \
		--export-plain-svg=$@ \
		tmp.svg
	rm -f tmp.svg

build/quake-%.svg: build/tmp-%.svg Makefile
	install -d build
	xmlstarlet ed -d "//*[local-name() = 'g' and @id != 'layer-quake-256']" < $< > tmp.svg
	inkscape \
		--export-area-page \
		--export-plain-svg=$@ \
		tmp.svg
	rm -f tmp.svg

build/quake2.svg: quake1+2.svg Makefile
	install -d build
	xmlstarlet ed -d "//*[local-name() = 'g' and @id != 'layer-quake2-256']" < $< > tmp.svg
	inkscape \
		--export-area-page \
		--export-plain-svg=$@ \
		tmp.svg
	rm -f tmp.svg

build/quake3.png: quake3-tango.xcf
	install -d build
	xcf2png -o $@ $<

build/quake3-teamarena.png: quake3-teamarena-tango.xcf
	install -d build
	xcf2png -o $@ $<

build/%.xpm: build/%.png
	convert $< $@

build/%32.xpm: build/%.png
	convert -resize 32x32 $< $@
