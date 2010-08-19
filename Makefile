ALL = \
	build/quake3-tango.png \
	build/quake3.xpm \
	build/quake332.xpm

all: $(ALL)

build/%.png: %.xcf
	install -d build
	xcf2png -o $@ $<

build/quake3.xpm: build/quake3-tango.png
	convert $< $@

build/quake332.xpm: build/quake3-tango.png
	convert -resize 32x32 $< $@

clean:
	rm -rf build
