"""Hauptanwendung: Kopfleiste, Seitenleiste, Seiten, Farbschemata, Mini-Modus."""

import os
import sys

import psutil
from gi.repository import Gdk, Gio, GLib, Gtk

from . import actions, i18n, launcher, shortcut, sysinfo, theme, util
from .i18n import _
from .history import AppHistory
from .mini import MiniWindow
from .sampler import Sampler
from .settings import Settings
from .tabs.apphistory import AppHistoryTab
from .tabs.connections import ConnectionsTab
from .recorder import Recorder
from .tabs.benchmark import BenchmarkTab
from .tabs.details import DetailsTab
from .tabs.systemrecorder import SystemRecorderTab
from .tabs.overview import OverviewTab
from .tabs.performance import PerformanceTab
from .tabs.processes import ProcessesTab
from .tabs.services import ServicesTab
from .tabs.startup import StartupTab
from .tabs.storage import StorageTab
from .tabs.users import UsersTab
from .widgets import styled_label

# per Umgebungsvariable änderbar (z. B. für Tests neben einer laufenden Instanz)
APP_ID = os.environ.get("TASKMANAGER_APP_ID", "de.local.LinuxTaskmanager")
from .version import VERSION  # noqa: E402
SPEEDS = [(_("Hoch"), 0.5), (_("Normal"), 1.0), (_("Niedrig"), 4.0)]

# (Name, Klasse, Titel, Symbol)
PAGES = [
    ("overview", OverviewTab, _("Übersicht"), "view-grid-symbolic"),
    ("processes", ProcessesTab, _("Prozesse"), "view-list-symbolic"),
    ("performance", PerformanceTab, _("Leistung"), "power-profile-performance-symbolic"),
    ("sysrec", SystemRecorderTab, _("Systemrekorder"), "media-record-symbolic"),
    ("benchmark", BenchmarkTab, _("CPU-Benchmark"), "speedometer-symbolic"),
    ("storage", StorageTab, _("Speicherplatz"), "drive-harddisk-symbolic"),
    ("connections", ConnectionsTab, _("Verbindungen"), "network-transmit-receive-symbolic"),
    ("apphistory", AppHistoryTab, _("App-Verlauf"), "document-open-recent-symbolic"),
    ("startup", StartupTab, _("Autostart"), "system-run-symbolic"),
    ("users", UsersTab, i18n.C_("Seite", "Benutzer"), "system-users-symbolic"),
    ("details", DetailsTab, _("Details"), "format-justify-fill-symbolic"),
    ("services", ServicesTab, _("Dienste"), "emblem-system-symbolic"),
]


class TaskManager(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.window = None
        self.mini = None
        self.last_snapshot = None

    def do_startup(self):
        Gtk.Application.do_startup(self)
        self.settings = Settings()
        theme.apply(self.settings["theme"])
        self.mem_total = psutil.virtual_memory().total
        self.history = AppHistory()
        self.host = sysinfo.hostname()
        self.recorder = Recorder(self.settings, role="gui")
        self.sampler = Sampler(self._on_snapshot, self.settings["interval"], self.settings["paused"])

    def do_activate(self):
        if self.window is not None:
            self.window.present()
            return
        self._build_window()
        self.sampler.start()

    def do_shutdown(self):
        if self.window is not None:
            self.settings["page"] = self.current_name
            self.benchmark.shutdown()
        self.settings.save()
        self.history.save()
        self.sampler.stop()
        self.recorder.close()
        Gtk.Application.do_shutdown(self)

    # ------------------------------------------------------------- Fenster
    def _build_window(self):
        s = self.settings
        win = self.window = Gtk.ApplicationWindow(application=self, title=_("Taskmanager"))
        win.get_style_context().add_class("tm-root")
        win.set_icon_name("utilities-system-monitor")
        # Startgröße an den nutzbaren Bildschirmbereich anpassen (z. B. 1280×720)
        work = self._workarea()
        w = max(s["width"], 1100)
        h = max(s["height"], 760)
        if work:
            w, h = min(w, work.width), min(h, work.height)
        win.set_default_size(w, h)
        if s["maximized"]:
            win.maximize()
        win.set_keep_above(s["always_on_top"])
        win.connect("configure-event", self._on_configure)
        win.connect("window-state-event", self._on_state)
        win.connect("key-press-event", self._on_key)

        # Kopfleiste
        hb = self.headerbar = Gtk.HeaderBar(show_close_button=True)
        hb.set_title(_("TASKMANAGER"))
        win.set_titlebar(hb)
        menu_btn = Gtk.MenuButton()
        menu_btn.set_image(Gtk.Image.new_from_icon_name("open-menu-symbolic", Gtk.IconSize.BUTTON))
        menu_btn.set_tooltip_text(_("Menü"))
        menu_btn.set_popup(self._build_menu())
        hb.pack_end(menu_btn)
        mini_btn = Gtk.Button.new_from_icon_name("view-restore-symbolic", Gtk.IconSize.BUTTON)
        mini_btn.set_tooltip_text(_("Mini-Modus (Strg+M)"))
        mini_btn.connect("clicked", lambda *_xx: self.toggle_mini(True))
        hb.pack_end(mini_btn)
        refresh = Gtk.Button.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON)
        refresh.set_tooltip_text(_("Jetzt aktualisieren (F5)"))
        refresh.connect("clicked", lambda *_xx: self.refresh_now())
        hb.pack_end(refresh)
        new_task = Gtk.Button.new_from_icon_name("list-add-symbolic", Gtk.IconSize.BUTTON)
        new_task.set_tooltip_text(_("Neuen Task ausführen (Strg+N)"))
        new_task.connect("clicked", lambda *_xx: actions.run_new_task(self.window))
        hb.pack_start(new_task)
        self.rec_chip = Gtk.Button(label=_("● REC"))
        self.rec_chip.set_relief(Gtk.ReliefStyle.NONE)
        self.rec_chip.get_style_context().add_class("tm-rec")
        self.rec_chip.set_tooltip_text(_("Systemrekorder zeichnet auf – klicken zum Öffnen"))
        self.rec_chip.connect("clicked", lambda *_xx: self.show_page("sysrec"))
        self.rec_chip.set_no_show_all(True)
        hb.pack_start(self.rec_chip)
        self.paused_chip = styled_label(_("⏸ ANGEHALTEN"), "tm-chip")
        self.paused_chip.set_no_show_all(True)
        hb.pack_start(self.paused_chip)

        # Seiten
        self.tabs = {}
        self.stack = Gtk.Stack()
        # nur die sichtbare Seite bestimmt die Mindestgröße (sonst zählt die breiteste Seite)
        self.stack.set_hhomogeneous(False)
        self.stack.set_vhomogeneous(False)
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(120)
        for name, cls, title, icon in PAGES:
            tab = cls(self)
            tab.name = name
            self.tabs[name] = tab
            setattr(self, name, tab)
            self.stack.add_named(tab.widget, name)

        # Seitenleiste
        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        side.get_style_context().add_class("tm-sidebar")
        side.set_size_request(205, -1)
        brand = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin=16, margin_bottom=8)
        brand.pack_start(styled_label(_("◢ TASKMANAGER"), "tm-brand"), False, False, 0)
        brand.pack_start(styled_label(_("FÜR LINUX"), "tm-brand-sub"), False, False, 0)
        side.pack_start(brand, False, False, 0)
        self.nav = Gtk.ListBox()
        self.nav.set_selection_mode(Gtk.SelectionMode.BROWSE)
        self.nav_rows = {}
        for i, (name, cls, title, icon) in enumerate(PAGES):
            row = Gtk.ListBoxRow()
            row.page = name
            box = Gtk.Box(spacing=12)
            box.pack_start(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU), False, False, 0)
            box.pack_start(Gtk.Label(label=title, xalign=0), True, True, 0)
            if i < 9:
                hint = styled_label(f"^{i + 1}", "tm-dim")
                hint.set_opacity(0.5)
                box.pack_end(hint, False, False, 0)
            row.add(box)
            row.set_tooltip_text(_('{0} (Strg+{1})').format(title, (i + 1) % 10))
            self.nav.add(row)
            self.nav_rows[name] = row
        self.nav.connect("row-selected", self._on_nav)
        nav_sw = Gtk.ScrolledWindow()
        nav_sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        nav_sw.set_propagate_natural_height(True)
        nav_sw.add(self.nav)
        side.pack_start(nav_sw, True, True, 0)
        foot = styled_label(f"v{VERSION}  ·  {self.host}", "tm-dim", margin=10)
        foot.set_valign(Gtk.Align.END)
        side.pack_end(foot, False, False, 0)

        body = Gtk.Box()
        body.pack_start(side, False, False, 0)
        body.pack_start(self.stack, True, True, 0)
        win.add(body)
        win.show_all()

        self.current_name = None
        page = {"flight": "sysrec"}.get(s["page"], s["page"])  # alter Seitenname
        start = page if page in self.tabs else "overview"
        self.nav.select_row(self.nav_rows[start])
        self._update_paused()
        theme.on_change(self._on_theme_changed)

    @staticmethod
    def _workarea():
        display = Gdk.Display.get_default()
        mon = display.get_primary_monitor() or display.get_monitor(0) if display else None
        return mon.get_workarea() if mon else None

    def _build_menu(self):
        menu = Gtk.Menu()

        def item(label, cb, parent=menu, accel=None):
            mi = Gtk.MenuItem.new_with_mnemonic(label)
            if accel:
                child = mi.get_child()
                key, mods = Gtk.accelerator_parse(accel)
                child.set_accel(key, mods)
            mi.connect("activate", lambda *_xx: cb())
            parent.append(mi)
            return mi

        item(_("_Neuen Task ausführen…"), lambda: actions.run_new_task(self.window), accel="<Control>n")
        item(_("_Mini-Modus"), lambda: self.toggle_mini(True), accel="<Control>m")
        item(_("_Jetzt aktualisieren"), self.refresh_now, accel="F5")
        menu.append(Gtk.SeparatorMenuItem())

        def radio_sub(label, options, current, on_select):
            top = Gtk.MenuItem.new_with_mnemonic(label)
            sub = Gtk.Menu()
            group = None
            for text, value in options:
                ri = Gtk.RadioMenuItem.new_with_label_from_widget(group, text)
                group = group or ri
                ri.set_active(value == current)
                ri.connect("toggled", lambda w, v=value: w.get_active() and on_select(v))
                sub.append(ri)
            top.set_submenu(sub)
            menu.append(top)

        radio_sub(_("_Farbschema"), [(_(n), n) for n in theme.PALETTES], self.settings["theme"], self.set_theme)
        radio_sub(_("_Sprache / Language"), [(_(label), key) for key, label in i18n.LANGUAGES],
                  self.settings.get("language", "auto"), self._set_language)
        current = None if self.settings["paused"] else self.settings["interval"]
        radio_sub(_("_Aktualisierungsgeschwindigkeit"),
                  [(f"{l} ({util.num(v, 1 if v < 1 else 0)} s)", v) for l, v in SPEEDS] + [(_("Angehalten"), None)],
                  current, self._set_speed)

        def check(label, key, cb):
            ci = Gtk.CheckMenuItem.new_with_mnemonic(label)
            ci.set_active(self.settings[key])
            ci.connect("toggled", lambda w: cb(w.get_active()))
            menu.append(ci)

        check(_("Prozesse nach _Typ gruppieren"), "group_by_type", self._set_group)
        check(_("_Immer im Vordergrund"), "always_on_top", self._set_on_top)

        # globales Tastenkürzel (benutzerbezogen in Cinnamon)
        sc = Gtk.CheckMenuItem.new_with_mnemonic(_("_Tastenkürzel Strg+Umschalt+Esc"))
        if shortcut.available():
            sc.set_active(shortcut.is_enabled())
            sc.set_tooltip_text(_("Öffnet den Taskmanager systemweit mit Strg+Umschalt+Esc (wie unter Windows)"))
            sc.connect("toggled", self._set_shortcut)
        else:
            sc.set_sensitive(False)
            sc.set_tooltip_text(_("Nur unter Cinnamon verfügbar"))
        menu.append(sc)
        menu.append(Gtk.SeparatorMenuItem())
        item(_("Ü_ber Taskmanager"), self._about)
        item(_("_Beenden"), self.quit, accel="<Control>q")
        menu.show_all()
        return menu

    # ------------------------------------------------------------ Navigation
    def _on_nav(self, listbox, row):
        if row is None:
            return
        self.current_name = row.page
        self.stack.set_visible_child_name(row.page)
        tab = self.tabs[row.page]
        tab.on_shown()
        if self.last_snapshot is not None and row.page not in ("performance", "overview"):
            tab.update(self.last_snapshot)

    def show_page(self, name):
        self.nav.select_row(self.nav_rows[name])

    def goto_details(self, pid):
        self.show_page("details")
        self.details.select_pid(pid)

    # ------------------------------------------------------------ Ereignisse
    def _on_snapshot(self, snap):
        self.last_snapshot = snap
        self.history.add(snap)
        self.recorder.add(snap)
        self.rec_chip.set_visible(self.recorder.active and self.settings.get("fr_enabled", True))
        # Diese Seiten sammeln Verläufe und werden daher immer versorgt
        self.performance.feed(snap)
        self.overview.update(snap)
        self.benchmark.feed(snap)
        if self.mini is not None and self.mini.get_visible():
            self.mini.update(snap)
        name = self.current_name
        if name not in (None, "performance", "overview", "benchmark"):
            self.tabs[name].update(snap)
        self.headerbar.set_subtitle(
            _('{0}   ·   CPU {1}   ·   RAM {2}   ·   {3} Prozesse   ·   Betriebszeit {4}').format(self.host, util.pct(snap.cpu), util.pct(snap.vm.percent), len(snap.procs), util.uptime_text(snap.uptime)))
        return False

    def refresh_now(self):
        self.sampler.refresh_now()
        if self.current_name in ("startup", "services"):
            self.tabs[self.current_name].reload()

    def set_theme(self, name):
        self.settings["theme"] = name
        theme.apply(name)

    def _on_theme_changed(self):
        def redraw(w):
            if isinstance(w, Gtk.DrawingArea):
                w.queue_draw()
            if isinstance(w, Gtk.Container):
                w.forall(redraw)
        for win in (self.window, self.mini):
            if win is not None:
                redraw(win)
        if self.window is not None:
            self.benchmark.retheme()

    def _set_speed(self, value):
        if value is None:
            self.sampler.paused = True
            self.settings["paused"] = True
        else:
            self.sampler.paused = False
            self.settings["paused"] = False
            self.settings["interval"] = value
            self.sampler.set_interval(value)
            self.performance.set_interval(value)
        self._update_paused()

    def _update_paused(self):
        self.paused_chip.set_visible(self.sampler.paused)
        self.paused_chip.set_tooltip_text(_("Aktualisierung angehalten – F5 aktualisiert einmalig"))

    def _set_language(self, choice):
        if choice == self.settings.get("language", "auto"):
            return
        self.settings["language"] = choice
        new = i18n.system_language() if choice == "auto" else choice
        if new == i18n.LANG:
            self.settings.save()
            return
        # Hinweis in beiden Sprachen, da die Oberfläche noch die alte Sprache zeigt
        d = Gtk.MessageDialog(transient_for=self.window, modal=True, message_type=Gtk.MessageType.QUESTION,
                              buttons=Gtk.ButtonsType.NONE,
                              text="Neustart erforderlich / Restart required")
        d.format_secondary_text("Die Sprache wird nach einem Neustart des Taskmanagers übernommen.\n"
                                "The language will change after restarting the Task Manager.")
        d.add_button("Später / Later", Gtk.ResponseType.CANCEL)
        d.add_button("Jetzt neu starten / Restart now", Gtk.ResponseType.OK)
        d.set_default_response(Gtk.ResponseType.OK)
        r = d.run()
        d.destroy()
        self.settings.save()
        if r == Gtk.ResponseType.OK:
            self.restart()

    def restart(self):
        """Programm sauber beenden und im selben Prozess neu starten."""
        self.settings["page"] = self.current_name
        self.settings.save()
        self.history.save()
        self.benchmark.shutdown()
        self.sampler.stop()
        self.recorder.close()
        # gleiche Startart wie bisher (Projektordner, .deb oder .pyz)
        os.execve(sys.executable, launcher.argv(), launcher.env())

    def _set_group(self, active):
        self.settings["group_by_type"] = active
        self.processes.sync.clear()
        if self.last_snapshot:
            self.processes.update(self.last_snapshot)

    def _set_shortcut(self, item):
        if not item.get_active():
            shortcut.disable()
            return
        other = shortcut.conflict()
        if other and not actions.confirm(
                self.window, _("Strg+Umschalt+Esc ist bereits belegt"),
                _("Das Tastenkürzel „{0}“ verwendet dieselbe Kombination. Trotzdem einrichten?").format(other),
                _("Einrichten")):
            item.handler_block_by_func(self._set_shortcut)
            item.set_active(False)
            item.handler_unblock_by_func(self._set_shortcut)
            return
        shortcut.enable()

    def _set_on_top(self, active):
        self.settings["always_on_top"] = active
        self.window.set_keep_above(active)

    def toggle_mini(self, on):
        if on:
            if self.mini is None:
                self.mini = MiniWindow(self)
                self.add_window(self.mini)
            self.mini.show_all()
            if self.last_snapshot:
                self.mini.update(self.last_snapshot)
            self.window.iconify()
        else:
            if self.mini is not None:
                self.mini.hide()
            self.window.deiconify()
            self.window.present()

    def _about(self):
        d = Gtk.AboutDialog(transient_for=self.window, modal=True)
        d.set_program_name(_("Taskmanager für Linux"))
        d.set_version(VERSION)
        d.set_logo_icon_name("utilities-system-monitor")
        d.set_copyright(_("© 2026 vanhake"))
        d.set_license_type(Gtk.License.GPL_3_0)
        d.set_website("https://github.com/vanhake/LinuxTaskManager")
        d.set_website_label(_("Projekt auf GitHub"))
        d.set_comments(_("Prozesse, Leistung, Speicherplatz, Verbindungen, Autostart, Benutzer und "
                       "Dienste im Blick – inspiriert vom Windows-Taskmanager und TMOG."))
        d.run()
        d.destroy()

    def _on_configure(self, win, event):
        if not self.settings["maximized"]:
            w, h = win.get_size()
            self.settings["width"], self.settings["height"] = w, h
        return False

    def _on_state(self, win, event):
        self.settings["maximized"] = bool(event.new_window_state & Gdk.WindowState.MAXIMIZED)
        return False

    def _on_key(self, win, event):
        ctrl = event.state & Gdk.ModifierType.CONTROL_MASK
        kv = Gdk.keyval_to_lower(event.keyval)
        if event.keyval == Gdk.KEY_F5:
            self.refresh_now()
            return True
        if not ctrl:
            return False
        if kv == Gdk.KEY_f:
            self.tabs[self.current_name].focus_search()
        elif kv == Gdk.KEY_n:
            actions.run_new_task(self.window)
        elif kv == Gdk.KEY_m:
            self.toggle_mini(True)
        elif kv == Gdk.KEY_q:
            self.quit()
        elif Gdk.KEY_1 <= event.keyval <= Gdk.KEY_9:
            idx = event.keyval - Gdk.KEY_1
            if idx < len(PAGES):
                self.show_page(PAGES[idx][0])
        elif event.keyval == Gdk.KEY_0 and len(PAGES) >= 10:
            self.show_page(PAGES[9][0])
        else:
            return False
        return True


def main():
    GLib.set_prgname("taskmanager")
    GLib.set_application_name(_("Taskmanager"))
    app = TaskManager()
    return app.run(None)
