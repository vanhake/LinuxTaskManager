"""Registerkarte „Dienste“: systemd-Dienste anzeigen und steuern."""

from ..i18n import _

import os
import subprocess
import threading
import time

from gi.repository import Gdk, GLib, Gtk, Pango

from .. import actions
from ..treesync import TreeSync
from . import Tab, scrolled, text_column

C_NAME, C_PID, C_DESC, C_STATUS, C_START, C_ACTIVE, C_RAWSTATE = range(7)

ACTIVE_DE = {
    "active": _("Wird ausgeführt"),
    "inactive": _("Beendet"),
    "failed": _("Fehler"),
    "activating": _("Wird gestartet"),
    "deactivating": _("Wird beendet"),
    "reloading": _("Wird neu geladen"),
}
START_DE = {
    "enabled": _("Automatisch"),
    "enabled-runtime": _("Automatisch (temporär)"),
    "disabled": _("Manuell"),
    "static": _("Statisch"),
    "masked": _("Deaktiviert (maskiert)"),
    "masked-runtime": _("Deaktiviert (temporär)"),
    "indirect": _("Indirekt"),
    "generated": _("Generiert"),
    "alias": _("Alias"),
    "transient": _("Temporär"),
    "linked": _("Verknüpft"),
}


def _systemctl(user, *args):
    cmd = ["systemctl", "--no-pager", "--plain", "--no-legend"]
    if user:
        cmd.append("--user")
    cmd += list(args)
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10,
                              env=dict(os.environ, LC_ALL="C")).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def load_services(user):
    """Liest Dienste ein (läuft im Hintergrund-Thread)."""
    services = {}
    for line in _systemctl(user, "list-units", "--type=service", "--all").splitlines():
        parts = line.split(None, 4)
        if len(parts) < 4:
            continue
        unit, load, active, sub = parts[:4]
        desc = parts[4] if len(parts) > 4 else ""
        if load == "not-found":
            continue
        services[unit] = {"active": active, "sub": sub, "desc": desc, "state": "", "pid": 0}
    for line in _systemctl(user, "list-unit-files", "--type=service").splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        unit, state = parts[0], parts[1]
        if unit.endswith("@.service"):
            continue
        s = services.setdefault(unit, {"active": "inactive", "sub": "dead", "desc": "", "pid": 0})
        s["state"] = state
    names = list(services)
    # MainPID und fehlende Beschreibungen in Blöcken abfragen
    for i in range(0, len(names), 150):
        chunk = names[i:i + 150]
        out = _systemctl(user, "show", "-p", _("Id"), "-p", _("MainPID"), "-p", _("Description"),
                         "-p", _("UnitFileState"), *chunk)
        cur = {}
        for line in out.splitlines() + [""]:
            if not line.strip():
                unit = cur.get("Id")
                if unit in services:
                    s = services[unit]
                    try:
                        s["pid"] = int(cur.get("MainPID", "0"))
                    except ValueError:
                        pass
                    if not s["desc"]:
                        s["desc"] = cur.get("Description", "")
                    if not s.get("state"):
                        s["state"] = cur.get("UnitFileState", "")
                cur = {}
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                cur[k] = v
    return services


class ServicesTab(Tab):
    title = _("Dienste")

    def __init__(self, app):
        super().__init__(app)
        self.store = Gtk.ListStore(str, int, str, str, str, str, str)
        self.sync = TreeSync(self.store)
        self.filter = self.store.filter_new()
        self.filter.set_visible_func(self._visible)
        self.sorted = Gtk.TreeModelSort.new_with_model(self.filter)
        self.sorted.set_sort_column_id(C_NAME, Gtk.SortType.ASCENDING)
        view = self.view = Gtk.TreeView(model=self.sorted)
        view.set_enable_search(False)
        text_column(view, _("Name"), C_NAME, C_NAME, width=260, ellipsize=True)
        text_column(view, _("PID"), C_PID, C_PID, 1.0,
                    func=lambda co, ce, m, it, d: ce.set_property(
                        "text", str(m.get_value(it, C_PID)) if m.get_value(it, C_PID) else ""))
        text_column(view, _("Beschreibung"), C_DESC, C_DESC, expand=True, ellipsize=True, width=300)
        text_column(view, _("Status"), C_STATUS, C_STATUS, width=150)
        text_column(view, _("Starttyp"), C_START, C_START, width=130)
        view.set_tooltip_column(C_DESC)
        view.get_selection().connect("changed", lambda s: self._update_buttons())
        view.connect("button-press-event", self._on_button)

        self.scope = Gtk.ComboBoxText()
        self.scope.append("system", _("Systemdienste"))
        self.scope.append("user", _("Benutzerdienste"))
        self.scope.set_active_id("user" if self.app.settings["services_user"] else "system")
        self.scope.connect("changed", self._on_scope)
        self.search = Gtk.SearchEntry(placeholder_text=_("Dienst suchen…"), width_chars=28)
        self.search.connect("search-changed", lambda e: self.filter.refilter())
        self.running_only = Gtk.CheckButton(label=_("Nur laufende"))
        self.running_only.connect("toggled", lambda c: self.filter.refilter())
        self.info = Gtk.Label(xalign=0)
        self.info.get_style_context().add_class("dim-label")
        self.spinner = Gtk.Spinner()

        self.buttons = {}
        bottom = Gtk.Box(spacing=8, margin=10)
        bottom.pack_start(self.info, True, True, 0)
        bottom.pack_start(self.spinner, False, False, 0)
        for key, label in (("start", _("Starten")), ("stop", _("Beenden")), ("restart", _("Neu starten")),
                           ("enable", _("Autostart an")), ("disable", _("Autostart aus"))):
            b = Gtk.Button(label=label)
            b.connect("clicked", lambda _x, k=key: self._action(k))
            bottom.pack_start(b, False, False, 0)
            self.buttons[key] = b
        top = Gtk.Box(spacing=8, margin=10)
        for w in (self.scope, self.search, self.running_only):
            top.pack_start(w, False, False, 0)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.pack_start(top, False, False, 0)
        box.pack_start(scrolled(view), True, True, 0)
        box.pack_start(bottom, False, False, 0)
        self.widget = box
        self._loading = False
        self._last = 0
        self._update_buttons()

    @property
    def user(self):
        return self.scope.get_active_id() == "user"

    def _on_scope(self, combo):
        self.app.settings["services_user"] = self.user
        self.sync.clear()
        self.reload()

    def on_shown(self):
        self.reload()

    def update(self, snap):
        if time.monotonic() - self._last > 15:
            self.reload()

    def reload(self):
        if self._loading:
            return
        self._loading = True
        self._last = time.monotonic()
        self.spinner.start()
        user = self.user

        def work():
            data = load_services(user)
            GLib.idle_add(self._apply, user, data)
        threading.Thread(target=work, daemon=True).start()

    def _apply(self, user, data):
        self._loading = False
        self._last = time.monotonic()
        self.spinner.stop()
        if user != self.user:
            self.reload()
            return False
        rows = []
        running = 0
        for unit, s in data.items():
            name = unit[:-8] if unit.endswith(".service") else unit
            status = ACTIVE_DE.get(s["active"], s["active"])
            if s["active"] == "active" and s["sub"] == "exited":
                status = _("Aktiv (abgeschlossen)")
            elif s["active"] == "active" and s["sub"] not in ("running", ""):
                status += f" ({s['sub']})"
            running += s["active"] == "active" and s["sub"] == "running"
            rows.append((unit, None, [name, s["pid"], s["desc"], status,
                                      START_DE.get(s.get("state", ""), s.get("state", "") or "–"),
                                      s["active"], s.get("state", "")]))
        self.sync.sync(rows)
        self.info.set_text(_('{0} Dienste, {1} laufen').format(len(rows), running))
        self._update_buttons()
        return False

    def _visible(self, model, it, data):
        if self.running_only.get_active() and model.get_value(it, C_ACTIVE) != "active":
            return False
        q = self.search.get_text().strip().lower()
        return not q or q in (model.get_value(it, C_NAME) or "").lower() or \
            q in (model.get_value(it, C_DESC) or "").lower()

    def _selected(self):
        model, it = self.view.get_selection().get_selected()
        if it is None:
            return None
        return {"name": model.get_value(it, C_NAME), "active": model.get_value(it, C_ACTIVE),
                "state": model.get_value(it, C_RAWSTATE)}

    def _update_buttons(self):
        s = self._selected()
        for k, b in self.buttons.items():
            b.set_sensitive(s is not None)
        if s:
            active = s["active"] in ("active", "activating", "reloading")
            self.buttons["start"].set_sensitive(not active)
            self.buttons["stop"].set_sensitive(active)
            can_toggle = s["state"] in ("enabled", "disabled")
            self.buttons["enable"].set_sensitive(can_toggle and s["state"] == "disabled")
            self.buttons["disable"].set_sensitive(can_toggle and s["state"] == "enabled")

    def _action(self, action):
        s = self._selected()
        if not s:
            return
        unit = s["name"] + ".service"
        if action == "stop" and not self.user and not actions.confirm(
                self.app.window, _('Dienst „{0}“ beenden?').format(s['name']),
                _("Das Beenden von Systemdiensten kann die Funktion des Systems beeinträchtigen."),
                _("Beenden")):
            return
        cmd = ["systemctl"]
        if self.user:
            cmd.append("--user")
        else:
            cmd = ["pkexec"] + cmd
        cmd += [action, unit]
        self.spinner.start()
        actions.run_async(cmd, self.app.window, on_done=lambda ok: self.reload(),
                          error_text=_('Aktion „{0}“ für {1} fehlgeschlagen').format(action, unit))

    def _on_button(self, view, event):
        if event.type != Gdk.EventType.BUTTON_PRESS or event.button != 3:
            return False
        hit = view.get_path_at_pos(int(event.x), int(event.y))
        if not hit:
            return False
        view.get_selection().select_path(hit[0])
        menu = Gtk.Menu()
        for key, b in self.buttons.items():
            mi = Gtk.MenuItem(label=b.get_label())
            mi.set_sensitive(b.get_sensitive())
            mi.connect("activate", lambda _x, k=key: self._action(k))
            menu.append(mi)
        menu.append(Gtk.SeparatorMenuItem())
        mi = Gtk.MenuItem(label=_("Status anzeigen (journalctl)…"))
        mi.connect("activate", lambda *_xx: self._show_status())
        menu.append(mi)
        menu.show_all()
        menu.attach_to_widget(view, None)
        menu.popup_at_pointer(event)
        return True

    def _show_status(self):
        s = self._selected()
        if not s:
            return
        args = ["systemctl", "--no-pager", "-l", "-n", "30"]
        if self.user:
            args.append("--user")
        args += ["status", s["name"] + ".service"]
        try:
            out = subprocess.run(args, capture_output=True, text=True, timeout=5).stdout
        except (OSError, subprocess.SubprocessError) as e:
            out = str(e)
        d = Gtk.Dialog(title=f"Status: {s['name']}", transient_for=self.app.window, modal=True)
        d.add_button(_("Schließen"), Gtk.ResponseType.CLOSE)
        d.set_default_size(820, 480)
        tv = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.NONE)
        tv.get_buffer().set_text(out or _("(keine Ausgabe)"))
        sw = scrolled(tv)
        sw.set_margin_start(8)
        sw.set_margin_end(8)
        d.get_content_area().pack_start(sw, True, True, 0)
        d.show_all()
        d.run()
        d.destroy()
