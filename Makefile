# Makefile - used for building icon

obj = quake quake.xpm


all: $(obj)

quake: quake.sh
	cp $< $@
	chmod +x $@

quake.xpm: quake.png
	convert -resize 32x32 $< $@

clean: 
	rm -f $(obj)
