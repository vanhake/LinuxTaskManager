"""Zuordnung Prozessname → Symbol über installierte .desktop-Dateien."""

import os

from gi.repository import Gio, Gtk

SIZE = 16
_theme = None
_by_exe = None
_cache = {}


_names = {}


def _index():
    global _by_exe
    _by_exe = {}
    for app in Gio.AppInfo.get_all():
        exe = app.get_executable()
        icon = app.get_icon()
        keys = []
        if exe:
            keys.append(os.path.basename(exe))
        if isinstance(app, Gio.DesktopAppInfo):
            wm = app.get_startup_wm_class()
            if wm:
                keys.append(wm.lower())
            app_id = (app.get_id() or "")[:-8]  # ohne .desktop
            if app_id:
                keys.append(app_id.lower())
        for k in keys:
            if icon is not None:
                _by_exe.setdefault(k, icon)
            _names.setdefault(k, app.get_name())


def app_name(wm_class, proc_name):
    """Anzeigename einer App (aus .desktop-Datei), sonst Fensterklasse."""
    if _by_exe is None:
        _index()
    for k in (wm_class.lower(), proc_name.lower()):
        if k in _names:
            return _names[k]
    return wm_class[:1].upper() + wm_class[1:] if wm_class else proc_name


def _load(gicon):
    global _theme
    if _theme is None:
        _theme = Gtk.IconTheme.get_default()
    try:
        info = _theme.lookup_by_gicon(gicon, SIZE, Gtk.IconLookupFlags.FORCE_SIZE)
        if info:
            return info.load_icon()
    except Exception:
        pass
    return None


def named(name):
    key = ("named", name)
    if key not in _cache:
        _cache[key] = _load(Gio.ThemedIcon.new(name))
    return _cache[key]


def for_process(name, exe=""):
    """Symbol für einen Prozess oder generisches Programmsymbol."""
    if _by_exe is None:
        _index()
    key = (name, exe)
    if key in _cache:
        return _cache[key]
    gicon = _by_exe.get(name) or _by_exe.get(os.path.basename(exe)) or _by_exe.get(name.lower())
    pix = _load(gicon) if gicon else None
    if pix is None:
        pix = named("application-x-executable")
    _cache[key] = pix
    return pix


def for_icon_string(icon):
    """Symbol aus Icon=-Eintrag einer .desktop-Datei."""
    if not icon:
        return named("application-x-executable")
    key = ("icon", icon)
    if key not in _cache:
        try:
            gicon = Gio.Icon.new_for_string(icon)
        except Exception:
            gicon = None
        _cache[key] = (_load(gicon) if gicon else None) or named("application-x-executable")
    return _cache[key]


def app_icons():
    """Programmlogo in mehreren Größen (funktioniert auch innerhalb der .pyz-Datei)."""
    from gi.repository import GdkPixbuf
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "linux-taskmanager.svg")
    try:
        # über den Modul-Loader: funktioniert im Ordner und innerhalb der .pyz (zipimport)
        data = __loader__.get_data(path)
    except (OSError, AttributeError):
        return []
    result = []
    for size in (16, 24, 32, 48, 64, 128, 256):
        loader = GdkPixbuf.PixbufLoader()
        loader.set_size(size, size)
        try:
            loader.write(data)
            loader.close()
            result.append(loader.get_pixbuf())
        except Exception:
            continue
    return result


def for_gicon(gicon):
    """Symbol aus einem Gio.Icon (z. B. von Gio.AppInfo.get_icon())."""
    if gicon is None:
        return named("application-x-executable")
    key = ("gicon", gicon.to_string())
    if key not in _cache:
        _cache[key] = _load(gicon) or named("application-x-executable")
    return _cache[key]
