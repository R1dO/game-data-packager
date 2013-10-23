# VERSION, PACKAGE must be supplied by caller

srcdir = ${CURDIR}
builddir = ${CURDIR}/build
outdir = ${CURDIR}/out

all: do-${PACKAGE}

do-quake2-demo-data: do-common
	install -m644 quake2/demo.md5sums ${outdir}/quake2/
	cat quake2/demo.md5sums >> ${outdir}/quake2/${PACKAGE}.md5sums

do-quake2-full-data: do-common
	install -m644 quake2/cd.md5sums ${outdir}/quake2/
	install -m644 quake2/patch.md5sums ${outdir}/quake2/
	cat \
		quake2/cd.md5sums \
		quake2/patch.md5sums \
		>> ${outdir}/quake2/${PACKAGE}.md5sums

do-quake2-music: do-common
	:

do-quake2-xatrix: do-common
	:

do-quake2-rogue: do-common
	:

do-common:
	install -d ${outdir}/quake2
	install -m644 quake2/${PACKAGE}.copyright ${outdir}/quake2/
	m4 -DVERSION=${VERSION} < quake2/${PACKAGE}.control > ${outdir}/quake2/${PACKAGE}.control
	chmod 0644 ${outdir}/quake2/${PACKAGE}.control
	( \
		md5sum ${outdir}/changelog.gz | \
			sed 's# .*#  usr/share/doc/${PACKAGE}/changelog.gz#'; \
		md5sum ${outdir}/quake2/${PACKAGE}.copyright | \
			sed 's# .*#  usr/share/doc/${PACKAGE}/copyright#'; \
	) > ${outdir}/quake2/${PACKAGE}.md5sums
	chmod 0644 ${outdir}/quake2/${PACKAGE}.md5sums

clean:
	rm -rf ${outdir}/quake2
