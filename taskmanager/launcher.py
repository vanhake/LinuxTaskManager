"""Startbefehle unabhängig davon, wie das Programm vorliegt.

Drei Varianten:
- Projektordner (git clone)      → python3 -m taskmanager, Paket über PYTHONPATH
- .deb-Installation (/usr/lib/…) → wie oben, nur anderer Ordner
- einzelne .pyz-Datei            → python3 /pfad/linux-taskmanager.pyz
"""

import os
import re
import sys

_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_PKG_DIR)


def appimage_path():
    """Pfad der .AppImage-Datei, wenn das Programm aus einer AppImage läuft.

    Die AppImage-Laufzeit setzt APPIMAGE (Datei) und APPDIR (temporärer Einhängepunkt).
    Startbefehle müssen auf die Datei zeigen – der Einhängepunkt verschwindet beim Beenden.
    """
    image, appdir = os.environ.get("APPIMAGE"), os.environ.get("APPDIR")
    if image and appdir and os.path.isfile(image) and _ROOT.startswith(appdir.rstrip("/") + "/"):
        return image
    return None


def zipapp_path():
    """Pfad der .pyz-Datei, wenn das Programm aus einem Zip-Archiv läuft."""
    return _ROOT if os.path.isfile(_ROOT) else None


def argv(*extra):
    """Argumentliste zum Starten (für execv/subprocess); dazu env() verwenden."""
    a = appimage_path()
    if a:
        return [a, *extra]
    z = zipapp_path()
    if z:
        return [sys.executable, z, *extra]
    return [sys.executable, "-m", "taskmanager", *extra]


def env():
    """Umgebung, in der das Paket gefunden wird – ohne das Arbeitsverzeichnis zu ändern."""
    e = dict(os.environ)
    if appimage_path():
        return e
    if not zipapp_path():
        old = e.get("PYTHONPATH")
        e["PYTHONPATH"] = _ROOT + (os.pathsep + old if old else "")
    return e


def _quote(arg):
    """Quoting nach der Desktop-Entry-Spezifikation (Exec-Schlüssel)."""
    if re.fullmatch(r"[A-Za-z0-9_./=:+@%-]+", arg):
        return arg
    inner = re.sub(r'(["`$\\])', r"\\\1", arg)
    # Schlüsseldatei-Ebene: Backslashes nochmals verdoppeln
    return '"' + inner.replace("\\", "\\\\") + '"'


def desktop_exec(*extra):
    """Exec-Zeile für .desktop-Dateien (z. B. Autostart des Hintergrunddienstes)."""
    a = appimage_path()
    z = zipapp_path()
    if a:
        parts = [a, *extra]
    elif z:
        parts = [sys.executable, z, *extra]
    else:
        parts = ["env", f"PYTHONPATH={_ROOT}", sys.executable, "-m", "taskmanager", *extra]
    return " ".join(_quote(p) for p in parts)
