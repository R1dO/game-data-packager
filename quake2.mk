# VERSION, PACKAGE must be supplied by caller

srcdir = ${CURDIR}
builddir = ${CURDIR}/build
outdir = ${CURDIR}/out

deb = ${outdir}/${PACKAGE}_${VERSION}_all.deb

all:
	install -d ${outdir}/quake2
	install -m644 quake2/cd.md5sums ${outdir}/quake2/
	install -m644 quake2/demo.md5sums ${outdir}/quake2/
	install -m644 quake2/patch.md5sums ${outdir}/quake2/
all: ${deb}

${deb}: \
		${builddir}/${PACKAGE}/DEBIAN/md5sums \
		${builddir}/${PACKAGE}/DEBIAN/control
	cd ${builddir} && \
	if [ `id -u` -eq 0 ]; then \
		dpkg-deb -b ${PACKAGE} $@ ; \
	else \
		fakeroot dpkg-deb -b ${PACKAGE} $@ ; \
	fi

${builddir}/${PACKAGE}/DEBIAN/md5sums: \
		${builddir}/${PACKAGE}/usr/share/doc/${PACKAGE}/changelog.gz \
		${builddir}/${PACKAGE}/usr/share/doc/${PACKAGE}/copyright
	install -d `dirname $@`
	cd ${builddir}/${PACKAGE} && find usr/ -type f  -print0 |\
		xargs -0 md5sum > DEBIAN/md5sums
	chmod 0644 $@

${builddir}/${PACKAGE}/usr/share/doc/${PACKAGE}/changelog.gz: \
		debian/changelog
	install -d `dirname $@`
	gzip -c9 $< > $@
	chmod 0644 $@

${builddir}/${PACKAGE}/usr/share/doc/${PACKAGE}/copyright: \
		quake2/${PACKAGE}.copyright
	install -d `dirname $@`
	install -m644 $< $@

${builddir}/${PACKAGE}/DEBIAN/control: \
		quake2/${PACKAGE}.control
	install -d `dirname $@`
	m4 -DVERSION=${VERSION} < $< > $@
	chmod 0644 $@

clean:
	rm -rf ${deb} ${builddir}/${PACKAGE}
	rm -rf ${outdir}/quake2
