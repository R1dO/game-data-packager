# VERSION must be supplied by caller

srcdir = $(CURDIR)
builddir = $(CURDIR)/build
outdir = $(CURDIR)/out

LGENERALDEB = $(outdir)/lgeneral-data-nonfree_$(VERSION)_all.deb

$(LGENERALDEB): \
	$(builddir)/lgeneral-data-nonfree/DEBIAN/md5sums \
	$(builddir)/lgeneral-data-nonfree/DEBIAN/control \
	fixperms_lgeneral
	install -d $(builddir)/lgeneral-data-nonfree/usr/share/games/lgeneral
	cd $(builddir) && \
	if [ `id -u` -eq 0 ]; then \
		dpkg-deb -b lgeneral-data-nonfree $@ ; \
	else \
		fakeroot dpkg-deb -b lgeneral-data-nonfree $@ ; \
	fi

$(builddir)/lgeneral-data-nonfree/DEBIAN/md5sums: \
	$(builddir)/lgeneral-data-nonfree/usr/share/doc/lgeneral-data-nonfree/changelog.gz \
	$(builddir)/lgeneral-data-nonfree/usr/share/doc/lgeneral-data-nonfree/copyright
	install -d `dirname $@`
	cd $(builddir)/lgeneral-data-nonfree && find usr/ -type f  -print0 |\
		xargs -0 md5sum >DEBIAN/md5sums

$(builddir)/lgeneral-data-nonfree/usr/share/doc/lgeneral-data-nonfree/changelog.gz:
	install -d `dirname $@`
	gzip -c9 debian/changelog > $@

$(builddir)/lgeneral-data-nonfree/usr/share/doc/lgeneral-data-nonfree/copyright:
	install -d `dirname $@`
	m4 -DPACKAGE=$(PACKAGE) lgeneral-data-nonfree/copyright.in > $@

$(builddir)/lgeneral-data-nonfree/DEBIAN/control:
	install -d `dirname $@`
	m4 -DVERSION=$(VERSION) < lgeneral-data-nonfree/DEBIAN/control > $@

fixperms_lgeneral:
	find $(builddir)/lgeneral-data-nonfree -type f -print0 | xargs -0 chmod 644
	find $(builddir)/lgeneral-data-nonfree -type d -print0 | xargs -0 chmod 755

clean:
	rm -rf $(LGENERALDEB) $(builddir)/lgeneral-data-nonfree
