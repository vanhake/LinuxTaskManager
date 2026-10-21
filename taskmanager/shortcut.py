"""Globales Tastenkürzel Strg+Umschalt+Esc (Cinnamon) für den aktuellen Benutzer.

Cinnamon speichert eigene Tastenkürzel benutzerbezogen in gsettings – ein
systemweit installiertes Paket (.deb) kann sie daher nicht selbst anlegen.
"""

import os
import shutil

from gi.repository import Gio

from . import launcher

LIST_SCHEMA = "org.cinnamon.desktop.keybindings"
ITEM_SCHEMA = "org.cinnamon.desktop.keybindings.custom-keybinding"
ITEM_PATH = "/org/cinnamon/desktop/keybindings/custom-keybindings/{}/"
BINDING = "<Primary><Shift>Escape"
NAME = "Taskmanager"


def available():
    source = Gio.SettingsSchemaSource.get_default()
    return bool(source and source.lookup(LIST_SCHEMA, True) and source.lookup(ITEM_SCHEMA, True))


def command():
    """Befehl, den Cinnamon beim Tastendruck ausführt."""
    installed = "/usr/lib/linux-taskmanager"
    if os.path.dirname(os.path.dirname(os.path.abspath(launcher.__file__))) == installed \
            and shutil.which("linux-taskmanager"):
        return "linux-taskmanager"
    return launcher.desktop_exec()


def _item(kb_id):
    return Gio.Settings.new_with_path(ITEM_SCHEMA, ITEM_PATH.format(kb_id))


def _ours():
    """IDs der Tastenkürzel, die zum Taskmanager gehören."""
    if not available():
        return []
    ids = Gio.Settings.new(LIST_SCHEMA).get_strv("custom-list")
    found = []
    for kb_id in ids:
        s = _item(kb_id)
        cmd = s.get_string("command")
        if s.get_string("name") == NAME or "taskmanager" in cmd:
            found.append(kb_id)
    return found


def is_enabled():
    return bool(_ours())


def conflict():
    """Name eines fremden Tastenkürzels mit derselben Tastenkombination, sonst None."""
    if not available():
        return None
    mine = set(_ours())
    for kb_id in Gio.Settings.new(LIST_SCHEMA).get_strv("custom-list"):
        if kb_id in mine:
            continue
        s = _item(kb_id)
        if BINDING in s.get_strv("binding"):
            return s.get_string("name") or kb_id
    return None


def enable():
    if not available():
        return False
    disable()
    lst = Gio.Settings.new(LIST_SCHEMA)
    ids = lst.get_strv("custom-list")
    n = 0
    while f"custom{n}" in ids:
        n += 1
    kb_id = f"custom{n}"
    s = _item(kb_id)
    s.set_string("name", NAME)
    s.set_string("command", command())
    s.set_strv("binding", [BINDING])
    # Liste erst zuletzt ändern – darauf reagiert Cinnamon
    lst.set_strv("custom-list", ids + [kb_id])
    Gio.Settings.sync()
    return True


def disable():
    if not available():
        return
    lst = Gio.Settings.new(LIST_SCHEMA)
    ours = _ours()
    if not ours:
        return
    lst.set_strv("custom-list", [i for i in lst.get_strv("custom-list") if i not in ours])
    for kb_id in ours:
        s = _item(kb_id)
        for key in ("name", "command", "binding"):
            s.reset(key)
    Gio.Settings.sync()
