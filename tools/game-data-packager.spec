# Fedora/RPMFusion version now at:
# https://pkgs.rpmfusion.org/cgit/free/game-data-packager.git/tree/game-data-packager.spec

# SuSE version now at:
# https://build.opensuse.org/package/view_file/games:tools/game-data-packager/game-data-packager.spec

# This is a preliminary version for Mageia

#define gitdate 20160112
# git log --oneline -1
%define gitversion 50f64b6

%if 0%{?gitdate}
%define gver .git%{gitdate}%{gitversion}
%endif

Name:          game-data-packager
Version:       45
Release:       1%{?gver}
Summary:       Installer for game data files
License:       GPLv2 and GPLv2+
Url:           https://wiki.debian.org/Games/GameDataPackager
%if 0%{?gitdate}
# git archive --prefix=game-data-packager-44/ --format tar.gz master > ../rpmbuild/SOURCES/game-data-packager-`date +%Y%m%d`.tar.gz
Source:        game-data-packager-%{gitdate}.tar.gz
%else
Source:        http://http.debian.net/debian/pool/contrib/g/game-data-packager/game-data-packager_%{version}.tar.xz
%endif
BuildArch:     noarch
BuildRequires: ImageMagick
BuildRequires: inkscape
BuildRequires: python3
BuildRequires: python3-yaml
BuildRequires: python3-pyflakes
BuildRequires: zip
Requires: python3-yaml
# download
Recommends: lgogdownloader
Suggests: steam
# rip
Suggests: cdparanoia
Suggests: vorbis-tools
# extract
Suggests: arj
Suggests: cabextract
Recommends: innoextract
Suggests: lha
Suggests: p7zip-plugins
Suggests: xdelta
Suggests: unar
Suggests: unrar
Suggests: unshield
Suggests: unzip

%global __python %{__python3}

%description
Various games are divided into two logical parts: engine and data.
.
game-data-packager is a tool which builds .rpm files for game
data which cannot be distributed (such as commercial game data).

%package -n doom2-masterlevels
Summary: "Master Levels for Doom II" launcher
Requires: python3-gobject-base
Requires: gobject-introspection
%description -n doom2-masterlevels
This GUI let you select a WAD to play &
show it's description.

%prep
%autosetup
rm -v data/soltys.xpm
#convert data/soltys.xpm out/soltys.png
#convert: improper image header `data/soltys.xpm' @ error/xpm.c/ReadXPMImage/348.
#convert: no images defined `out/soltys.png' @ error/convert.c/ConvertImageCommand/3257.

%build
make %{?_smp_mflags}

%check
make check

%install
make DESTDIR=$RPM_BUILD_ROOT bindir=/usr/bin datadir=/usr/share install
find $RPM_BUILD_ROOT/usr/share/game-data-packager/game_data_packager -name '*.py' -exec chmod 755 {} \;
#E: python-bytecode-inconsistent-mtime
python3 -m compileall $RPM_BUILD_ROOT/usr/share/game-data-packager/game_data_packager/version.py
find $RPM_BUILD_ROOT/etc/game-data-packager -empty -exec sh -c "echo '# we need more mirrors' > {}" \;
rm -rvf $RPM_BUILD_ROOT/etc/apparmor.d

%files
%doc doc/adding_a_game.mdwn
%{_mandir}/man6/game-data-packager.*
%{_mandir}/fr/man6/game-data-packager.*
%config(noreplace) %attr(644, root, root) /etc/game-data-packager.conf
%config(noreplace) %attr(644, root, root) /etc/game-data-packager/*
/usr/bin/game-data-packager
/usr/share/bash-completion/completions/game-data-packager
/usr/share/game-data-packager
%license COPYING

%files -n doom2-masterlevels
%{_mandir}/man6/doom2-masterlevels.*
/usr/bin/doom2-masterlevels
/usr/share/applications/doom2-masterlevels.desktop
/usr/share/pixmaps/doom2-masterlevels.png
%license COPYING

%changelog
* Sat Jul 23 2016 Alexandre Detiste <alexandre.detiste@gmail.com> - 45-1
- Initial port to Mageia, skip one icon that makes ImageMagick choke
