# Makefile - used for building icon

obj = \
	quake \
	quake.xpm \
	16/quake.png \
	22/quake.png \
	24/quake.png \
	32/quake.png \
	48/quake.png \
	256/quake.png

all: $(obj)

quake: quake.sh
	cp $< $@
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
	rm -f $(obj)
	rm -rf 16 22 24 32 48 256
