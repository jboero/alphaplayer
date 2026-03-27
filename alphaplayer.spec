%global pypi_name alphaplayer
%global app_id   io.github.alphaplayer

Name:           %{pypi_name}
Version:        1.2
Release:        1%{?dist}
Summary:        Transparent VP9/WebM video overlay player for Wayland and X11

License:        LGPL-3.0-or-later
URL:            https://github.com/jboero/alphaplayer
Source0:        %{pypi_source %{pypi_name}}

BuildArch:      noarch
BuildRequires:  python3-devel
BuildRequires:  pyproject-rpm-macros
BuildRequires:  python3-setuptools
BuildRequires:  python3-wheel
BuildRequires:  python3-pip
BuildRequires:  desktop-file-utils
BuildRequires:  ImageMagick

Requires:       python3-gobject
Requires:       gtk4
Requires:       gstreamer1
Requires:       gstreamer1-plugins-base
Requires:       gstreamer1-plugins-good
Requires:       gstreamer1-plugin-gtk4

Recommends:     gtk4-layer-shell
Recommends:     wmctrl
Recommends:     xdotool
Recommends:     xprop

%description
AlphaPlayer is a lightweight video overlay player for Linux that renders
VP9/WebM videos with alpha transparency directly on your desktop. It supports
Wayland (via gtk4-layer-shell) and X11, playlists, remote URL streaming,
adjustable opacity, keep-above/below stacking, and a minimal auto-hiding
control bar.

Ideal for transparent mascots, HUDs, tutorials, streaming overlays, or any
use case where you want video composited over your desktop.

%prep
%autosetup -n %{pypi_name}-%{version}

%generate_buildrequires
%pyproject_buildrequires

%build
%pyproject_wheel

%install
%pyproject_install
%pyproject_save_files %{pypi_name}

# Desktop file
install -Dpm 0644 %{pypi_name}.desktop \
    %{buildroot}%{_datadir}/applications/%{pypi_name}.desktop
desktop-file-validate %{buildroot}%{_datadir}/applications/%{pypi_name}.desktop

# Icon -- convert WebP to PNG for desktop icon theme compatibility
convert %{pypi_name}/%{pypi_name}_icon.webp %{pypi_name}_icon.png
install -Dpm 0644 %{pypi_name}_icon.png \
    %{buildroot}%{_datadir}/icons/hicolor/256x256/apps/%{pypi_name}.png

%post
/bin/touch --no-create %{_datadir}/icons/hicolor &>/dev/null || :

%postun
if [ $1 -eq 0 ]; then
    /bin/touch --no-create %{_datadir}/icons/hicolor &>/dev/null || :
    /usr/bin/gtk-update-icon-cache %{_datadir}/icons/hicolor &>/dev/null || :
fi

%posttrans
/usr/bin/gtk-update-icon-cache %{_datadir}/icons/hicolor &>/dev/null || :

%files -f %{pyproject_files}
%license LICENSE
%doc README.md
%{_bindir}/%{pypi_name}
%{_bindir}/%{pypi_name}-gui
%{_datadir}/applications/%{pypi_name}.desktop
%{_datadir}/icons/hicolor/256x256/apps/%{pypi_name}.png

%changelog
* Fri Mar 27 2026 John Boero <jboero@users.noreply.github.com> - 1.2-1
- Add --exit flag for tutorial/learning platform use
- Add HTTP/HTTPS URL streaming support
- Initial COPR package
