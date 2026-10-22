#!/bin/bash
# Erstellt die Release-Dateien in dist/:
#   linux-taskmanager_<version>_all.deb   – Paket für Linux Mint/Ubuntu/Debian (Doppelklick installiert)
#   linux-taskmanager-<version>.pyz       – einzelne, direkt ausführbare Datei (ohne Installation)
#   Taskmanager-<version>-x86_64.AppImage – AppImage (benötigt tools/runtime-x86_64, siehe unten)
set -euo pipefail

ROOT="$(dirname "$(readlink -f "$0")")"
cd "$ROOT"
VERSION=$(python3 -c 'import sys; sys.path.insert(0, "taskmanager"); from version import VERSION; print(VERSION)')
PKG=linux-taskmanager
DIST="$ROOT/dist"
BUILD="$(mktemp -d)"
trap 'rm -rf "$BUILD"' EXIT

echo "Baue $PKG $VERSION …"
rm -rf "$DIST"
mkdir -p "$DIST"

copy_package() {   # $1 = Zielordner
    mkdir -p "$1"
    (cd "$ROOT" && find taskmanager \( -name '*.py' -o -name '*.svg' \) -not -path '*/__pycache__/*' -print0 \
        | xargs -0 -I{} install -D -m 644 {} "$1/{}")
}

# ------------------------------------------------------------------ .pyz
PYZ_SRC="$BUILD/pyz"
copy_package "$PYZ_SRC"
cat > "$PYZ_SRC/__main__.py" <<'EOF'
import sys

# Schutz für Benchmark-Arbeitsprozesse (multiprocessing „spawn“ lädt diese Datei als „__mp_main__“)
if __name__ == "__main__":
    from taskmanager.start import main
    sys.exit(main())
EOF
python3 -m zipapp "$PYZ_SRC" -o "$DIST/$PKG-$VERSION.pyz" -p "/usr/bin/env python3" -c
chmod 755 "$DIST/$PKG-$VERSION.pyz"

# ------------------------------------------------------------------ .deb
DEB="$BUILD/deb"
copy_package "$DEB/usr/lib/$PKG"

install -d "$DEB/usr/bin"
cat > "$DEB/usr/bin/$PKG" <<EOF
#!/bin/sh
exec env PYTHONPATH=/usr/lib/$PKG /usr/bin/python3 -m taskmanager "\$@"
EOF
chmod 755 "$DEB/usr/bin/$PKG"

install -d "$DEB/usr/share/applications"
cat > "$DEB/usr/share/applications/$PKG.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Task Manager
Name[de]=Taskmanager
GenericName=Task Manager
GenericName[de]=Taskmanager
Comment=Monitor processes, performance, startup apps, users and services
Comment[de]=Prozesse, Leistung, Autostart, Benutzer und Dienste überwachen
Exec=$PKG
Icon=$PKG
Terminal=false
Categories=System;Monitor;GTK;
Keywords=task;manager;taskmanager;prozess;process;cpu;ram;speicher;memory;dienste;services;
StartupWMClass=Taskmanager
EOF

install -D -m 644 "$ROOT/taskmanager/assets/$PKG.svg" "$DEB/usr/share/icons/hicolor/scalable/apps/$PKG.svg"

install -d "$DEB/usr/share/doc/$PKG"
cat > "$DEB/usr/share/doc/$PKG/copyright" <<EOF
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: Linux Taskmanager
Source: https://github.com/vanhake/LinuxTaskManager

Files: *
Copyright: 2026 vanhake
License: GPL-3+
 This program is free software: you can redistribute it and/or modify
 it under the terms of the GNU General Public License as published by
 the Free Software Foundation, either version 3 of the License, or
 (at your option) any later version.
 .
 On Debian systems, the complete text of the GNU General Public License
 version 3 can be found in "/usr/share/common-licenses/GPL-3".
EOF
printf '%s (%s) stable; urgency=low\n\n  * Release %s, siehe https://github.com/vanhake/LinuxTaskManager/releases\n\n -- vanhake <29869352+vanhake@users.noreply.github.com>  %s\n' \
    "$PKG" "$VERSION" "$VERSION" "$(LC_ALL=C date -R)" | gzip -9n > "$DEB/usr/share/doc/$PKG/changelog.gz"

install -d "$DEB/DEBIAN"
SIZE=$(du -sk --exclude=DEBIAN "$DEB" | cut -f1)
cat > "$DEB/DEBIAN/control" <<EOF
Package: $PKG
Version: $VERSION
Section: utils
Priority: optional
Architecture: all
Depends: python3 (>= 3.8), python3-gi, python3-gi-cairo, gir1.2-gtk-3.0, python3-psutil
Recommends: gir1.2-wnck-3.0, pkexec | policykit-1
Installed-Size: $SIZE
Maintainer: vanhake <29869352+vanhake@users.noreply.github.com>
Homepage: https://github.com/vanhake/LinuxTaskManager
Description: Modern task manager for Linux Mint (German/English)
 Task manager inspired by the Windows Task Manager: dashboard, processes,
 performance graphs, system recorder with rewind, CPU benchmark, disk space
 analysis, network connections, startup apps, users and systemd services.
 .
 Moderner Taskmanager im Stil des Windows-Taskmanagers mit Übersicht,
 Systemrekorder, CPU-Benchmark und Festplattenanalyse.
EOF
cat > "$DEB/DEBIAN/postinst" <<EOF
#!/bin/sh
set -e
if command -v py3compile >/dev/null 2>&1; then
    py3compile -p $PKG /usr/lib/$PKG
fi
EOF
cat > "$DEB/DEBIAN/prerm" <<EOF
#!/bin/sh
set -e
if command -v py3clean >/dev/null 2>&1; then
    py3clean -p $PKG
fi
EOF
find "$DEB" -type d -exec chmod 755 {} +
find "$DEB" -type f -exec chmod 644 {} +
chmod 755 "$DEB/DEBIAN/postinst" "$DEB/DEBIAN/prerm" "$DEB/usr/bin/$PKG"
dpkg-deb --build --root-owner-group -Zxz "$DEB" "$DIST/${PKG}_${VERSION}_all.deb" >/dev/null

# ------------------------------------------------------------------ .AppImage
# Schlanke AppImage: nutzt Python/GTK des Systems (wie .deb/.pyz). Die offizielle Laufzeit
# (https://github.com/AppImage/type2-runtime) muss einmalig nach tools/runtime-x86_64 geladen werden.
RUNTIME="$ROOT/tools/runtime-x86_64"
if [[ -f "$RUNTIME" ]] && command -v mksquashfs >/dev/null; then
    APPDIR="$BUILD/AppDir"
    copy_package "$APPDIR/usr/lib/$PKG"
    printf '%s\n' '#!/bin/sh' \
        'HERE="$(dirname "$(readlink -f "$0")")"' \
        'exec env PYTHONPATH="$HERE/usr/lib/linux-taskmanager" python3 -m taskmanager "$@"' > "$APPDIR/AppRun"
    chmod 755 "$APPDIR/AppRun"
    sed -e "s|^Exec=.*|Exec=$PKG|" "$DEB/usr/share/applications/$PKG.desktop" > "$APPDIR/$PKG.desktop"
    echo "X-AppImage-Version=$VERSION" >> "$APPDIR/$PKG.desktop"
    install -m 644 "$ROOT/taskmanager/assets/$PKG.svg" "$APPDIR/$PKG.svg"
    ln -s "$PKG.svg" "$APPDIR/.DirIcon"
    install -D -m 644 "$APPDIR/$PKG.desktop" "$APPDIR/usr/share/applications/$PKG.desktop"
    install -D -m 644 "$ROOT/taskmanager/assets/$PKG.svg" "$APPDIR/usr/share/icons/hicolor/scalable/apps/$PKG.svg"
    find "$APPDIR" -type d -exec chmod 755 {} +
    find "$APPDIR" -type f -exec chmod 644 {} +
    chmod 755 "$APPDIR/AppRun"
    mksquashfs "$APPDIR" "$BUILD/app.squashfs" -root-owned -noappend -comp zstd -Xcompression-level 19 -quiet >/dev/null
    cat "$RUNTIME" "$BUILD/app.squashfs" > "$DIST/Taskmanager-$VERSION-x86_64.AppImage"
    chmod 755 "$DIST/Taskmanager-$VERSION-x86_64.AppImage"
else
    echo "Hinweis: AppImage übersprungen – tools/runtime-x86_64 fehlt. Download:"
    echo "  https://github.com/AppImage/type2-runtime/releases/download/continuous/runtime-x86_64"
fi

(cd "$DIST" && sha256sum ./* > SHA256SUMS)
echo "Fertig:"
ls -l "$DIST"
