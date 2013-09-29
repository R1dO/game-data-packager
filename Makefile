# Makefile - used for building icon

obj = \
	quake \
	quake2 \
	quake-server \
	quake2-server \
	quake.xpm \
	quake2.xpm \
	16/quake.png \
	16/quake-armagon.png \
	16/quake-dissolution.png \
	16/quake2.png \
	22/quake.png \
	22/quake-armagon.png \
	22/quake-dissolution.png \
	22/quake2.png \
	24/quake.png \
	24/quake-armagon.png \
	24/quake-dissolution.png \
	24/quake2.png \
	32/quake.png \
	32/quake-armagon.png \
	32/quake-dissolution.png \
	32/quake2.png \
	48/quake.png \
	48/quake-armagon.png \
	48/quake-dissolution.png \
	48/quake2.png \
	256/quake.png \
	256/quake-armagon.png \
	256/quake-dissolution.png \
	256/quake2.png \
	quake.svg \
	quake-armagon.svg \
	quake-dissolution.svg \
	quake2.svg

all: $(obj)

quake: quake.in
	sed -e 's/@self@/quake/g' \
		-e 's/@role@/client/g' \
		-e 's/@options@//g' \
		-e 's/@alternative@/quake-engine/g' \
		< $< > $@
	chmod +x $@

quake2: quake2.in
	sed -e 's/@self@/quake2/g' \
		-e 's/@role@/client/g' \
		-e 's/@options@//g' \
		-e 's/@alternative@/quake2-engine/g' \
		< $< > $@
	chmod +x $@

quake2-server: quake2.in
	sed -e 's/@self@/quake2-server/g' \
		-e 's/@role@/dedicated server/g' \
		-e 's/@options@/+set dedicated 1/g' \
		-e 's/@alternative@/quake2-engine-server/g' \
		< $< > $@
	chmod +x $@

quake-server: quake.in
	sed -e 's/@self@/quake-server/g' \
		-e 's/@role@/server/g' \
		-e 's/@options@/-dedicated/g' \
		-e 's/@alternative@/quake-engine-server/g' \
		< $< > $@
	chmod +x $@

tmp-dissolution.svg: quake1+2.svg Makefile
	sed -e 's/#c17d11/#999984/' \
		-e 's/#d5b582/#dede95/' \
		-e 's/#5f3b01/#403f31/' \
		-e 's/#e9b96e/#dede95/' \
		< $< > $@

tmp-armagon.svg: quake1+2.svg Makefile
	sed -e 's/#c17d11/#565248/' \
		-e 's/#d5b582/#aba390/' \
		-e 's/#5f3b01/#000000/' \
		-e 's/#e9b96e/#aba390/' \
		< $< > $@

24/quake.png: 22/quake.png
	install -d 24
	convert -bordercolor Transparent -border 1x1 $< $@

24/quake-%.png: 22/quake-%.png
	install -d 24
	convert -bordercolor Transparent -border 1x1 $< $@

24/quake2.png: 22/quake2.png
	install -d 24
	convert -bordercolor Transparent -border 1x1 $< $@

%/quake.png: quake1+2.svg
	install -d $*
	inkscape \
		--export-area=0:0:$*:$* \
		--export-width=$* \
		--export-height=$* \
		--export-id=layer-quake-$* \
		--export-id-only \
		--export-png=$@ \
		$<

%/quake-armagon.png: tmp-armagon.svg
	install -d $*
	inkscape \
		--export-area=0:0:$*:$* \
		--export-width=$* \
		--export-height=$* \
		--export-id=layer-quake-$* \
		--export-id-only \
		--export-png=$@ \
		$<

%/quake-dissolution.png: tmp-dissolution.svg
	install -d $*
	inkscape \
		--export-area=0:0:$*:$* \
		--export-width=$* \
		--export-height=$* \
		--export-id=layer-quake-$* \
		--export-id-only \
		--export-png=$@ \
		$<

%/quake2.png: quake1+2.svg
	install -d $*
	inkscape \
		--export-area=0:0:$*:$* \
		--export-width=$* \
		--export-height=$* \
		--export-id=layer-quake2-$* \
		--export-id-only \
		--export-png=$@ \
		$<

%.xpm: 32/%.png
	convert $< $@

clean: 
	rm -f $(obj) tmp.svg tmp-*.svg
	rm -rf 16 22 24 32 48 256

quake.svg: quake1+2.svg Makefile
	xmlstarlet ed -d "//*[local-name() = 'g' and @id != 'layer-quake-256']" < $< > tmp.svg
	inkscape \
		--export-area-page \
		--export-plain-svg=$@ \
		tmp.svg
	rm -f tmp.svg

quake-%.svg: tmp-%.svg Makefile
	xmlstarlet ed -d "//*[local-name() = 'g' and @id != 'layer-quake-256']" < $< > tmp.svg
	inkscape \
		--export-area-page \
		--export-plain-svg=$@ \
		tmp.svg
	rm -f tmp.svg

quake2.svg: quake1+2.svg Makefile
	xmlstarlet ed -d "//*[local-name() = 'g' and @id != 'layer-quake2-256']" < $< > tmp.svg
	inkscape \
		--export-area-page \
		--export-plain-svg=$@ \
		tmp.svg
	rm -f tmp.svg
