ALL = \
	build/quake3.png \
	build/quake3.xpm \
	build/quake332.xpm

all: $(ALL)

build/quake3.png: quake3-tango.xcf
	install -d build
	xcf2png -o $@ $<

build/quake3.xpm: build/quake3.png
	convert $< $@

build/quake332.xpm: build/quake3.png
	convert -resize 32x32 $< $@

clean:
	rm -rf build
