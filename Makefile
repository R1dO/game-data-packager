ALL = \
	build/quake3 \
	build/quake3-server \
	build/quake3.png \
	build/quake3.xpm \
	build/quake332.xpm \
	build/quake3-teamarena.png \
	build/quake3-teamarena.xpm \
	build/quake3-teamarena32.xpm

all: $(ALL)

build/quake3: quake3.in Makefile
	install -d build
	sed \
		-e 's!@IOQ3BINARY@!ioquake3!' \
		-e 's!@IOQ3SELF@!quake3!' \
		-e 's!@IOQ3ROLE@!client!' \
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

clean:
	rm -rf build
