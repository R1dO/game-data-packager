Name:          game-data-packager
Version:       43
Release:       1
Summary:       Installer for game data files
License:       GPLv2 and GPLv2+
Url:           https://wiki.debian.org/Games/GameDataPackager
# git archive --prefix=game-data-packager/ --format tar.gz master > ../rpmbuild/SOURCES/game-data-packager.tar.gz
Source:        game-data-packager.tar.gz
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
echo 'GAME_PACKAGE_VERSION = """%{version}"""' > game_data_packager/version.py
echo 'FORMAT = "rpm"' >> game_data_packager/version.py
echo 'BINDIR = "usr/bin"' >> game_data_packager/version.py
echo 'ASSETS = "usr/share"' >> game_data_packager/version.py
rm game_data_packager/util_deb.py

%install
install -D out/game-data-packager                  $RPM_BUILD_ROOT/usr/bin/game-data-packager

install -D data/bash-completion/game-data-packager $RPM_BUILD_ROOT/usr/share/bash-completion/completions/game-data-packager

mkdir -p                                           $RPM_BUILD_ROOT/etc/game-data-packager/
install etc/game-data-packager.conf                $RPM_BUILD_ROOT/etc/
install etc/*-mirrors                              $RPM_BUILD_ROOT/etc/game-data-packager/

mkdir -p                                           $RPM_BUILD_ROOT/usr/share/games/game-data-packager/
cp -Rv game_data_packager                          $RPM_BUILD_ROOT/usr/share/games/game-data-packager/
install out/*.copyright                            $RPM_BUILD_ROOT/usr/share/games/game-data-packager/
install out/*.png                                  $RPM_BUILD_ROOT/usr/share/games/game-data-packager/
install out/*.svgz                                 $RPM_BUILD_ROOT/usr/share/games/game-data-packager/
install out/bash_completion                        $RPM_BUILD_ROOT/usr/share/games/game-data-packager/
install out/changelog.gz                           $RPM_BUILD_ROOT/usr/share/games/game-data-packager/
install out/copyright                              $RPM_BUILD_ROOT/usr/share/games/game-data-packager/
install out/vfs.zip                                $RPM_BUILD_ROOT/usr/share/games/game-data-packager/

mkdir -p                                           $RPM_BUILD_ROOT/usr/share/man/man6/
install doc/game-data-packager.*                   $RPM_BUILD_ROOT/usr/share/man/man6/
install doc/doom2-masterlevels.*                   $RPM_BUILD_ROOT/usr/share/man/man6/

install -D runtime/doom2-masterlevels.py           $RPM_BUILD_ROOT/usr/bin/doom2-masterlevels
install -D runtime/doom2-masterlevels.desktop      $RPM_BUILD_ROOT/usr/share/applications/doom2-masterlevels.desktop

%clean
make clean

%files
%doc doc/adding_a_game.mdwn
%{_mandir}/man6/game-data-packager.*
/etc
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
