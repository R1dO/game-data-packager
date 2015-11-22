Name:          game-data-packager
Version:       43
Release:       1
Summary:       Installer for game data files
License:       GPLv2 and GPLv2+
Url:           https://wiki.debian.org/Games/GameDataPackager
# git archive --prefix=game-data-packager/ --format tar.gz master > ../rpmbuild/SOURCES/game-data-packager.tar.gz
Source:        game-data-packager.tar.gz
#http://http.debian.net/debian/pool/contrib/g/game-data-packager/game-data-packager_${version}.tar.xz
BuildArch:     noarch
BuildRequires: ImageMagick
BuildRequires: inkscape
BuildRequires: python3
BuildRequires: python3-PyYAML
BuildRequires: zip
Requires: python3-PyYAML
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
%autosetup -n game-data-packager

%build
make %{?_smp_mflags}

%install
make DESTDIR=$RPM_BUILD_ROOT bindir=/usr/bin install
VERSION_PY=$RPM_BUILD_ROOT/usr/share/games/game-data-packager/game_data_packager/version.py
echo '#!/usr/bin/python3' > $VERSION_PY
echo 'GAME_PACKAGE_VERSION = """%{version}"""' >> $VERSION_PY
echo 'FORMAT = "rpm"' >> $VERSION_PY
echo 'DISTRO = "fedora"' >> $VERSION_PY
echo 'BINDIR = "usr/bin"' >> $VERSION_PY
echo 'ASSETS = "usr/share"' >> $VERSION_PY
rm $RPM_BUILD_ROOT/usr/share/games/game-data-packager/game_data_packager/util_arch.py
rm $RPM_BUILD_ROOT/usr/share/games/game-data-packager/game_data_packager/util_deb.py
rm $RPM_BUILD_ROOT/usr/share/games/game-data-packager/game_data_packager/util_suse.py
chmod 755 $RPM_BUILD_ROOT/usr/share/games/game-data-packager/game_data_packager/*.py
chmod 755 $RPM_BUILD_ROOT/usr/share/games/game-data-packager/game_data_packager/games/*.py
mkdir -p $RPM_BUILD_ROOT/usr/share/man/man6
install -m0644 doc/game-data-packager.6 $RPM_BUILD_ROOT/usr/share/man/man6
install -m0644 doc/doom2-masterlevels.6 $RPM_BUILD_ROOT/usr/share/man/man6

%clean
make clean

%files
%doc doc/adding_a_game.mdwn
%{_mandir}/man6/game-data-packager.*
%config(noreplace) %attr(644, root, root) /etc/game-data-packager.conf
%config(noreplace) %attr(644, root, root) /etc/game-data-packager/*
/usr/bin/game-data-packager
/usr/share/bash-completion/completions/game-data-packager
/usr/share/games/game-data-packager

%files -n doom2-masterlevels
%{_mandir}/man6/doom2-masterlevels.*
/usr/bin/doom2-masterlevels
/usr/share/applications/doom2-masterlevels.desktop

%changelog
* Sun Nov 08 2015 Alexandre Detiste <alexandre.detiste@gmail.com> - 43-1
- Initial port to Fedora
