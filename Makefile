# Makefile - used for building icon

obj = \
	quake \
	quake-server \
	quake.xpm \
	16/quake.png \
	22/quake.png \
	24/quake.png \
	32/quake.png \
	48/quake.png \
	256/quake.png \
	quake.svg

all: $(obj)

quake: quake.in
	sed -e 's/@self@/quake/g' \
		-e 's/@role@/client/g' \
		-e 's/@options@//g' \
		-e 's/@alternative@/quake-engine/g' \
		< $< > $@
	chmod +x $@

quake-server: quake.in
	sed -e 's/@self@/quake-server/g' \
		-e 's/@role@/server/g' \
		-e 's/@options@/-dedicated/g' \
		-e 's/@alternative@/quake-engine-server/g' \
		< $< > $@
	chmod +x $@

24/quake.png: 22/quake.png
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

quake.xpm: 32/quake.png
	convert $< $@

clean: 
	rm -f $(obj) tmp.svg
	rm -rf 16 22 24 32 48 256

quake.svg: quake1+2.svg Makefile
	xmlstarlet ed -d "//*[local-name() = 'g' and @id != 'layer-quake-256']" < $< > tmp.svg
	inkscape \
		--export-area-page \
		--export-plain-svg=$@ \
		tmp.svg
	rm -f tmp.svg
