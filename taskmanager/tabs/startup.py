"""Registerkarte „Autostart“: XDG-Autostart-Einträge verwalten."""

import glob
import os
import re

from gi.repository import GdkPixbuf, Gio, GLib, Gtk, Pango

from .. import actions, icons
from . import Tab, scrolled, text_column

SYSTEM_DIRS = [os.path.join(d, "autostart") for d in
               (os.environ.get("XDG_CONFIG_DIRS") or "/etc/xdg").split(":")]
USER_DIR = os.path.join(GLib.get_user_config_dir(), "autostart")
GROUP = "Desktop Entry"
C_FILE, C_PATH, C_ICON, C_NAME, C_COMMENT, C_STATUS, C_ENABLED, C_DELAY, C_CMD, C_SOURCE, C_USERONLY = range(11)


def _desktops():
    return {d.lower() for d in os.environ.get("XDG_CURRENT_DESKTOP", "").split(":") if d}


def _get(kf, key, default="", locale=True):
    try:
        if locale:
            return kf.get_locale_string(GROUP, key, None)
        return kf.get_string(GROUP, key)
    except GLib.Error:
        return default


def _get_bool(kf, key, default=False):
    try:
        return kf.get_boolean(GROUP, key)
    except GLib.Error:
        return default


def _get_list(kf, key):
    try:
        return [x.lower() for x in kf.get_string_list(GROUP, key)]
    except GLib.Error:
        return []


def _load(path):
    kf = GLib.KeyFile()
    try:
        kf.load_from_file(path, GLib.KeyFileFlags.KEEP_COMMENTS | GLib.KeyFileFlags.KEEP_TRANSLATIONS)
    except GLib.Error:
        return None
    return kf


def _applies(kf):
    desk = _desktops()
    only = _get_list(kf, "OnlyShowIn")
    not_in = _get_list(kf, "NotShowIn")
    if only and not (desk & set(only)):
        return False
    if desk & set(not_in):
        return False
    try_exec = _get(kf, "TryExec", locale=False)
    if try_exec and not GLib.find_program_in_path(try_exec) and not os.path.exists(try_exec):
        return False
    return True


def _enabled(kf):
    if _get_bool(kf, "Hidden"):
        return False
    for key in ("X-GNOME-Autostart-enabled", "X-MATE-Autostart-enabled"):
        try:
            return kf.get_boolean(GROUP, key)
        except GLib.Error:  # Schlüssel fehlt
            pass
    return True


def _has_group(kf):
    return kf.has_group(GROUP)


class StartupTab(Tab):
    title = "Autostart"

    def __init__(self, app):
        super().__init__(app)
        self.store = Gtk.ListStore(str, str, GdkPixbuf.Pixbuf, str, str, str, bool, str, str, str, bool)
        self.store.set_sort_column_id(C_NAME, Gtk.SortType.ASCENDING)
        view = self.view = Gtk.TreeView(model=self.store)
        view.set_tooltip_column(C_CMD)

        col = Gtk.TreeViewColumn("Name")
        pix = Gtk.CellRendererPixbuf()
        col.pack_start(pix, False)
        col.add_attribute(pix, "pixbuf", C_ICON)
        txt = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END)
        col.pack_start(txt, True)
        col.add_attribute(txt, "text", C_NAME)
        col.set_sort_column_id(C_NAME)
        col.set_resizable(True)
        col.set_min_width(220)
        view.append_column(col)
        text_column(view, "Beschreibung", C_COMMENT, C_COMMENT, ellipsize=True, width=260)
        text_column(view, "Status", C_STATUS, C_STATUS)
        text_column(view, "Verzögerung", C_DELAY, C_DELAY, 1.0)
        text_column(view, "Quelle", C_SOURCE, C_SOURCE)
        text_column(view, "Befehl", C_CMD, C_CMD, expand=True, ellipsize=True)
        view.get_selection().connect("changed", lambda s: self._update_buttons())
        view.connect("row-activated", lambda *a: self._toggle())
        view.connect("button-press-event", self._on_button)

        self.toggle_btn = Gtk.Button(label="Deaktivieren")
        self.toggle_btn.connect("clicked", lambda *_: self._toggle())
        add_btn = Gtk.Button(label="Hinzufügen…")
        add_btn.connect("clicked", lambda *_: self._add())
        self.remove_btn = Gtk.Button(label="Entfernen")
        self.remove_btn.connect("clicked", lambda *_: self._remove())
        folder_btn = Gtk.Button(label="Ordner öffnen")
        folder_btn.connect("clicked", lambda *_: self._open_folder())
        refresh = Gtk.Button.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON)
        refresh.set_tooltip_text("Neu laden")
        refresh.connect("clicked", lambda *_: self.reload())
        self.info = Gtk.Label(xalign=0)
        self.info.get_style_context().add_class("dim-label")

        bottom = Gtk.Box(spacing=8, margin=10)
        bottom.pack_start(self.info, True, True, 0)
        for w in (refresh, folder_btn, add_btn, self.remove_btn, self.toggle_btn):
            bottom.pack_start(w, False, False, 0)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.pack_start(scrolled(view), True, True, 0)
        box.pack_start(bottom, False, False, 0)
        self.widget = box
        self._loaded = False

    def on_shown(self):
        if not self._loaded:
            self.reload()

    def reload(self):
        self._loaded = True
        selected = self._selected_file()
        entries = {}
        for d in reversed(SYSTEM_DIRS):
            for path in glob.glob(os.path.join(d, "*.desktop")):
                entries[os.path.basename(path)] = ("System", path)
        for path in glob.glob(os.path.join(USER_DIR, "*.desktop")):
            fn = os.path.basename(path)
            src = "System (angepasst)" if fn in entries else "Benutzer"
            entries[fn] = (src, path)
        self.store.clear()
        enabled_count = 0
        for fn, (source, path) in entries.items():
            kf = _load(path)
            if kf is None or not _has_group(kf) or not _applies(kf):
                continue
            if _get(kf, "Type", "Application", locale=False) != "Application":
                continue
            en = _enabled(kf)
            enabled_count += en
            delay = _get(kf, "X-GNOME-Autostart-Delay", locale=False)
            exec_ = _get(kf, "Exec", locale=False)
            name = _get(kf, "Name") or fn[:-8]
            it = self.store.append([
                fn, path, icons.for_icon_string(_get(kf, "Icon", locale=False)), name,
                _get(kf, "Comment"), "Aktiviert" if en else "Deaktiviert", en,
                f"{delay} s" if delay and delay != "0" else "", exec_, source, source == "Benutzer",
            ])
            if fn == selected:
                self.view.get_selection().select_iter(it)
        self.info.set_text(f"{len(self.store)} Einträge, davon {enabled_count} aktiviert")
        self._update_buttons()

    def _selected_row(self):
        model, it = self.view.get_selection().get_selected()
        return (model, it) if it is not None else (None, None)

    def _selected_file(self):
        model, it = self._selected_row()
        return model.get_value(it, C_FILE) if it else None

    def _update_buttons(self):
        model, it = self._selected_row()
        self.toggle_btn.set_sensitive(it is not None)
        self.remove_btn.set_sensitive(bool(it) and model.get_value(it, C_USERONLY))
        if it is not None:
            self.toggle_btn.set_label("Deaktivieren" if model.get_value(it, C_ENABLED) else "Aktivieren")

    def _toggle(self):
        model, it = self._selected_row()
        if it is None:
            return
        fn, path, enabled = model.get_value(it, C_FILE), model.get_value(it, C_PATH), \
            model.get_value(it, C_ENABLED)
        kf = _load(path)
        if kf is None:
            return
        kf.set_boolean(GROUP, "X-GNOME-Autostart-enabled", not enabled)
        if not enabled and _get_bool(kf, "Hidden"):
            kf.set_boolean(GROUP, "Hidden", False)
        target = os.path.join(USER_DIR, fn)
        try:
            os.makedirs(USER_DIR, exist_ok=True)
            kf.save_to_file(target)
        except (GLib.Error, OSError) as e:
            actions.message(self.app.window, "Eintrag konnte nicht gespeichert werden", str(e))
            return
        self.reload()

    def _remove(self):
        model, it = self._selected_row()
        if it is None or not model.get_value(it, C_USERONLY):
            return
        name, path = model.get_value(it, C_NAME), model.get_value(it, C_PATH)
        if not actions.confirm(self.app.window, f"Autostart-Eintrag „{name}“ entfernen?",
                               f"Die Datei {path} wird in den Papierkorb verschoben.", "Entfernen"):
            return
        try:
            Gio.File.new_for_path(path).trash(None)
        except GLib.Error as e:
            actions.message(self.app.window, "Entfernen fehlgeschlagen", e.message)
        self.reload()

    def _add(self):
        d = Gtk.Dialog(title="Autostart-Eintrag hinzufügen", transient_for=self.app.window, modal=True)
        d.add_button("Abbrechen", Gtk.ResponseType.CANCEL)
        d.add_button("Hinzufügen", Gtk.ResponseType.OK)
        d.set_default_response(Gtk.ResponseType.OK)
        grid = Gtk.Grid(column_spacing=10, row_spacing=8, margin=16)
        name = Gtk.Entry(hexpand=True, activates_default=True)
        cmd = Gtk.Entry(hexpand=True, activates_default=True)
        comment = Gtk.Entry(hexpand=True, activates_default=True)
        delay = Gtk.SpinButton.new_with_range(0, 600, 1)
        for i, (lbl, w) in enumerate((("Name:", name), ("Befehl:", cmd), ("Beschreibung:", comment),
                                      ("Verzögerung (s):", delay))):
            grid.attach(Gtk.Label(label=lbl, xalign=0), 0, i, 1, 1)
            grid.attach(w, 1, i, 1, 1)
        d.get_content_area().add(grid)
        d.set_default_size(460, -1)
        d.show_all()
        while d.run() == Gtk.ResponseType.OK:
            n, c = name.get_text().strip(), cmd.get_text().strip()
            if not n or not c:
                actions.message(d, "Name und Befehl sind erforderlich.")
                continue
            kf = GLib.KeyFile()
            kf.set_string(GROUP, "Type", "Application")
            kf.set_string(GROUP, "Name", n)
            kf.set_string(GROUP, "Exec", c)
            if comment.get_text().strip():
                kf.set_string(GROUP, "Comment", comment.get_text().strip())
            kf.set_boolean(GROUP, "X-GNOME-Autostart-enabled", True)
            if delay.get_value_as_int():
                kf.set_string(GROUP, "X-GNOME-Autostart-Delay", str(delay.get_value_as_int()))
            base = re.sub(r"[^A-Za-z0-9_-]+", "-", n).strip("-").lower() or "eintrag"
            path = os.path.join(USER_DIR, base + ".desktop")
            i = 1
            while os.path.exists(path):
                i += 1
                path = os.path.join(USER_DIR, f"{base}-{i}.desktop")
            try:
                os.makedirs(USER_DIR, exist_ok=True)
                kf.save_to_file(path)
            except (GLib.Error, OSError) as e:
                actions.message(d, "Speichern fehlgeschlagen", str(e))
                continue
            break
        d.destroy()
        self.reload()

    def _open_folder(self):
        model, it = self._selected_row()
        folder = os.path.dirname(model.get_value(it, C_PATH)) if it else USER_DIR
        os.makedirs(USER_DIR, exist_ok=True)
        try:
            Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(folder).get_uri(), None)
        except GLib.Error as e:
            actions.message(self.app.window, "Ordner konnte nicht geöffnet werden", e.message)

    def _on_button(self, view, event):
        if event.button != 3:
            return False
        hit = view.get_path_at_pos(int(event.x), int(event.y))
        if not hit:
            return False
        view.get_selection().select_path(hit[0])
        model, it = self._selected_row()
        menu = Gtk.Menu()
        en = model.get_value(it, C_ENABLED)
        for label, cb, sensitive in (("Deaktivieren" if en else "Aktivieren", self._toggle, True),
                                     ("Dateispeicherort öffnen", self._open_folder, True),
                                     ("Entfernen", self._remove, model.get_value(it, C_USERONLY))):
            mi = Gtk.MenuItem(label=label)
            mi.set_sensitive(sensitive)
            mi.connect("activate", lambda *_, f=cb: f())
            menu.append(mi)
        menu.show_all()
        menu.attach_to_widget(view, None)
        menu.popup_at_pointer(event)
        return True
