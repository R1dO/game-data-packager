# VERSION, PACKAGE must be supplied by caller

srcdir = ${CURDIR}
builddir = ${CURDIR}/build
outdir = ${CURDIR}/out

all:
	install -d ${outdir}/quake2
	m4 -DVERSION=${VERSION} < data/${PACKAGE}.control.in > ${outdir}/quake2/${PACKAGE}.control
	chmod 0644 ${outdir}/quake2/${PACKAGE}.control
	( \
		md5sum ${outdir}/changelog.gz | \
			sed 's# .*#  usr/share/doc/${PACKAGE}/changelog.gz#'; \
		md5sum data/${PACKAGE}.copyright | \
			sed 's# .*#  usr/share/doc/${PACKAGE}/copyright#'; \
	) > ${outdir}/quake2/${PACKAGE}.md5sums
	chmod 0644 ${outdir}/quake2/${PACKAGE}.md5sums

clean:
	rm -rf ${outdir}/quake2
