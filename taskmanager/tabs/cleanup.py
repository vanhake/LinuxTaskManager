"""Fenster „Speicherplatz freigeben“: Bereinigen und selten genutzte Programme."""

import os
import re
import threading
import time

import psutil
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, GObject, Gtk, Pango

from .. import actions, cleanup, icons, util
from ..i18n import _
from ..widgets import card, set_text, styled_label
from . import scrolled

AGES = [(30, "30 Tagen"), (90, "90 Tagen"), (180, "180 Tagen"), (365, "1 Jahr"), (0, "Alle anzeigen")]
P_SEL, P_ICON, P_NAME, P_KIND, P_PKG, P_SIZE, P_LAST, P_DAYS, P_PROT, P_REASON, P_INST = range(11)


def free_space():
    """Freier Platz auf / und dem Laufwerk des persönlichen Ordners (ohne Doppelzählung)."""
    seen, total = set(), 0
    for path in ("/", os.path.expanduser("~")):
        try:
            dev = os.stat(path).st_dev
            if dev in seen:
                continue
            seen.add(dev)
            total += psutil.disk_usage(path).free
        except OSError:
            pass
    return total


def run_root(script, on_done, on_line=None, argv=None):
    """Skript mit Administratorrechten (pkexec → Passwortabfrage) ausführen.

    on_line(text) erhält jede Ausgabezeile sofort (Fortschritt/Live-Protokoll),
    on_done(status, gesamte_ausgabe) am Ende. argv nur für Tests (ohne pkexec).
    """
    try:
        proc = Gio.Subprocess.new(argv or ["pkexec", "/bin/sh", "-c", script],
                                  Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_MERGE)
    except GLib.Error as e:
        on_done(-1, e.message)
        return
    stream = Gio.DataInputStream.new(proc.get_stdout_pipe())
    lines = []

    def finished(p, res):
        try:
            p.wait_finish(res)
        except GLib.Error:
            pass
        status = p.get_exit_status() if p.get_if_exited() else -1
        on_done(status, "\n".join(lines))

    def got_line(st, res):
        try:
            data, _length = st.read_line_finish_utf8(res)
        except GLib.Error:
            data = None
        if data is None:  # Ende der Ausgabe
            proc.wait_async(None, finished)
            return
        data = data.rstrip("\r")
        lines.append(data)
        if on_line:
            on_line(data)
        st.read_line_async(GLib.PRIORITY_DEFAULT, None, got_line)

    stream.read_line_async(GLib.PRIORITY_DEFAULT, None, got_line)


class CleanupWindow(Gtk.Window):
    def __init__(self, app):
        super().__init__(title=_("Speicherplatz freigeben"), transient_for=app.window, modal=True)
        self.app = app
        self.get_style_context().add_class("tm-root")
        work = app._workarea()
        self.set_default_size(min(980, work.width - 40) if work else 980,
                              min(660, work.height - 20) if work else 660)
        self.set_position(Gtk.WindowPosition.CENTER_ON_PARENT)
        self.busy = False
        self.cats = []
        self.cat_rows = {}

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin=18)
        head = Gtk.Box(spacing=12)
        head.pack_start(styled_label(_("Speicherplatz freigeben"), "tm-h1"), False, False, 0)
        self.free_chip = styled_label("", "tm-chip")
        self.free_chip.set_valign(Gtk.Align.CENTER)
        head.pack_end(self.free_chip, False, False, 0)
        outer.pack_start(head, False, False, 0)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        switcher = Gtk.StackSwitcher(stack=self.stack)
        switcher.get_style_context().add_class("linked")
        outer.pack_start(switcher, False, False, 0)
        self.stack.add_titled(self._build_clean_page(), "clean", _("Bereinigen"))
        self.stack.add_titled(self._build_programs_page(), "programs", _("Selten genutzte Programme"))

        top = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        top.pack_start(self.stack, True, True, 0)
        top.pack_start(self._build_progress(), False, False, 0)

        # Protokoll unten, Trenner frei verschiebbar
        logbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin_top=8)
        lhead = Gtk.Box(spacing=8)
        lhead.pack_start(styled_label(_("PROTOKOLL"), "tm-card-title"), False, False, 0)
        lhead.pack_start(styled_label(_("Trennlinie ziehen, um das Protokoll zu vergrößern"), "tm-dim"),
                         False, False, 0)
        copy = Gtk.Button(label=_("Kopieren"))
        copy.connect("clicked", lambda *_x: self._copy_log())
        lhead.pack_end(copy, False, False, 0)
        logbox.pack_start(lhead, False, False, 0)
        self.log = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                                left_margin=8, right_margin=8, top_margin=6, bottom_margin=6)
        self._log_end = self.log.get_buffer().create_mark("ende", self.log.get_buffer().get_end_iter(), False)
        lsw = scrolled(self.log)
        lsw.set_margin_start(0)
        lsw.set_margin_end(0)
        logbox.pack_start(lsw, True, True, 0)

        self.paned = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL, wide_handle=True)
        self.paned.pack1(top, True, False)
        self.paned.pack2(logbox, True, False)
        self._paned_init = False
        self.paned.connect("size-allocate", self._on_paned_alloc)
        outer.pack_start(self.paned, True, True, 0)

        self.add(outer)
        self.show_all()
        self._update_free()
        self.scan_categories()
        self.programs_loaded = False
        self.stack.connect("notify::visible-child-name", self._on_page)

    # ================================================================ Fortschritt
    def _build_progress(self):
        self.prog_rev = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.get_style_context().add_class("tm-card")
        line = Gtk.Box(spacing=10)
        self.prog_spinner = Gtk.Spinner()
        line.pack_start(self.prog_spinner, False, False, 0)
        self.prog_step = styled_label("", "tm-mid", ellipsize=Pango.EllipsizeMode.END)
        line.pack_start(self.prog_step, True, True, 0)
        self.prog_time = styled_label("", "tm-dim tm-num", xalign=1)
        line.pack_end(self.prog_time, False, False, 0)
        box.pack_start(line, False, False, 0)
        self.prog_bar = Gtk.ProgressBar(show_text=True)
        box.pack_start(self.prog_bar, False, False, 0)
        self.prog_detail = styled_label("", "tm-dim", ellipsize=Pango.EllipsizeMode.MIDDLE)
        box.pack_start(self.prog_detail, False, False, 0)
        self.prog_rev.add(box)
        self._prog_timer = None
        return self.prog_rev

    def progress_start(self, total, title):
        """Fortschrittsanzeige für `total` Schritte einblenden."""
        self._prog_total = max(1, total)
        self._prog_done = 0
        self._prog_sub = 0.0
        self._prog_known = False
        self._prog_waiting = False
        self._prog_t0 = time.monotonic()
        self._prog_last_activity = time.monotonic()
        set_text(self.prog_step, title)
        set_text(self.prog_detail, "")
        self.prog_bar.set_fraction(0)
        self.prog_bar.set_text("0 %")
        self.prog_spinner.start()
        self.prog_rev.set_reveal_child(True)
        self._show_log(big=True)
        if self._prog_timer is None:
            self._prog_timer = GLib.timeout_add(150, self._prog_tick)

    def progress_step(self, index, title):
        """Schritt `index` (0-basiert) beginnt."""
        self._prog_done = index
        self._prog_sub = 0.0
        self._prog_known = False
        self._prog_waiting = False
        set_text(self.prog_step, _("Schritt {0} von {1}: {2}").format(index + 1, self._prog_total, title))
        set_text(self.prog_detail, "")
        self._prog_last_activity = time.monotonic()
        self._prog_update()

    def progress_sub(self, percent):
        """Fortschritt innerhalb des aktuellen Schritts (0–100), z. B. von apt."""
        self._prog_sub = max(0.0, min(1.0, percent / 100.0))
        self._prog_known = True
        self._prog_update()

    def progress_detail(self, text):
        self._prog_last_activity = time.monotonic()
        set_text(self.prog_detail, text)

    def progress_wait(self, text):
        """Warten auf den Benutzer (Passwortabfrage) – Balken pulsiert."""
        self._prog_waiting = True
        set_text(self.prog_detail, text)

    def progress_end(self):
        if self._prog_timer is not None:
            GLib.source_remove(self._prog_timer)
            self._prog_timer = None
        self.prog_spinner.stop()
        self.prog_bar.set_fraction(1.0)
        self.prog_bar.set_text("100 %")
        GLib.timeout_add(1500, lambda: self.prog_rev.set_reveal_child(False) or False)

    def _prog_update(self):
        frac = (self._prog_done + self._prog_sub) / self._prog_total
        self.prog_bar.set_fraction(frac)
        self.prog_bar.set_text(util.pct(frac * 100))

    def _prog_tick(self):
        secs = int(time.monotonic() - self._prog_t0)
        idle = int(time.monotonic() - self._prog_last_activity)
        txt = _("läuft seit {0}").format(f"{secs // 60}:{secs % 60:02d}")
        if idle >= 10:
            txt += "  ·  " + _("letzte Ausgabe vor {0} s").format(idle)
        set_text(self.prog_time, txt)
        if self._prog_waiting:
            # Warten auf die Passworteingabe: Balken pulsiert
            self.prog_bar.set_pulse_step(0.04)
            self.prog_bar.pulse()
            self.prog_bar.set_text(_("wartet auf Passwort …"))
        elif not self._prog_known:
            # Schritt ohne Prozentangabe: Gesamtfortschritt halten, Spinner + Zeit zeigen Aktivität
            frac = (self._prog_done + self._prog_sub) / self._prog_total
            self.prog_bar.set_fraction(frac)
            self.prog_bar.set_text(util.pct(frac * 100) + "  ·  " + _("arbeitet …"))
        return True

    def _on_root_line(self, line, titles):
        """Live-Ausgabe des Root-Skripts auswerten (Schrittmarken, apt-Fortschritt)."""
        if self._prog_waiting:  # sobald Ausgabe kommt, ist das Passwort eingegeben
            set_text(self.clean_status, _("Wird bereinigt …"))
        self._prog_waiting = False
        m = re.match(r"^### (\d+)$", line)
        if m:
            i = int(m.group(1))
            self.progress_step(self._root_offset + i, titles[i] if i < len(titles) else "")
            return
        m = re.match(r"^### rc=(\d+)$", line)
        if m:
            return
        m = re.match(r"^(pmstatus|dlstatus):[^:]*:([\d.]+):(.*)$", line)
        if m:  # maschinenlesbarer apt-Fortschritt
            self.progress_sub(float(m.group(2)))
            self.progress_detail(m.group(3))
            return
        self.progress_detail(line)
        self._log(line)

    # ================================================================ Seite 1
    def _build_clean_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.cat_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.cat_list.get_style_context().add_class("tm-devlist")
        sw = scrolled(self.cat_list)
        sw.set_margin_start(0)
        sw.set_margin_end(0)
        box.pack_start(sw, True, True, 0)
        foot = Gtk.Box(spacing=10)
        self.sel_label = styled_label("", "tm-mid")
        foot.pack_start(self.sel_label, False, False, 0)
        self.clean_status = styled_label("", "tm-dim", ellipsize=Pango.EllipsizeMode.END)
        foot.pack_start(self.clean_status, True, True, 0)
        self.spinner = Gtk.Spinner()
        foot.pack_start(self.spinner, False, False, 0)
        self.rescan_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON)
        self.rescan_btn.set_tooltip_text(_("Neu ermitteln"))
        self.rescan_btn.connect("clicked", lambda *_x: self.scan_categories())
        foot.pack_start(self.rescan_btn, False, False, 0)
        self.clean_btn = Gtk.Button(label=_("Ausgewählte bereinigen"))
        self.clean_btn.get_style_context().add_class("tm-primary")
        self.clean_btn.connect("clicked", lambda *_x: self.clean_selected())
        foot.pack_start(self.clean_btn, False, False, 0)
        box.pack_start(foot, False, False, 0)
        return box

    def _update_free(self):
        set_text(self.free_chip, _("Frei: {0}").format(util.size(free_space())))

    def _set_busy(self, busy, text=""):
        self.busy = busy
        self.clean_btn.set_sensitive(not busy)
        self.rescan_btn.set_sensitive(not busy)
        if hasattr(self, "remove_btn"):
            self.remove_btn.set_sensitive(not busy)
        (self.spinner.start if busy else self.spinner.stop)()
        set_text(self.clean_status, text)

    def scan_categories(self):
        if self.busy:
            return
        self._set_busy(True, _("Wird ermittelt …"))
        for child in self.cat_list.get_children():
            self.cat_list.remove(child)
        cats = cleanup.categories()

        def work():
            for c in cats:
                try:
                    c.scan()
                except Exception as e:  # einzelne Kategorie darf den Rest nicht verhindern
                    c.available = False
                    c.note = str(e)
            GLib.idle_add(self._show_categories, cats)
        threading.Thread(target=work, daemon=True).start()

    def _show_categories(self, cats):
        self.cats = [c for c in cats if c.available]
        self.cat_rows = {}
        for c in self.cats:
            self.cat_list.add(self._cat_row(c))
        self.cat_list.show_all()
        self._set_busy(False)
        self._update_selection()
        return False

    def _cat_row(self, c):
        row = Gtk.ListBoxRow()
        row.set_activatable(False)
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin=8)
        line = Gtk.Box(spacing=12)
        check = Gtk.CheckButton()
        check.set_active(c.default and (c.size is None or c.size > 0))
        check.set_valign(Gtk.Align.CENTER)
        check.connect("toggled", lambda *_x: self._update_selection())
        line.pack_start(check, False, False, 0)
        line.pack_start(Gtk.Image.new_from_icon_name(c.icon, Gtk.IconSize.LARGE_TOOLBAR), False, False, 0)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        title = Gtk.Box(spacing=8)
        title.pack_start(styled_label(c.title, "tm-mid"), False, False, 0)
        if c.root:
            chip = styled_label(_("🔒 Passwort"), "tm-chip")
            chip.set_tooltip_text(_("Benötigt Administratorrechte – das Passwort wird beim Bereinigen abgefragt"))
            title.pack_start(chip, False, False, 0)
        texts.pack_start(title, False, False, 0)
        texts.pack_start(styled_label(c.description, "tm-dim", ellipsize=Pango.EllipsizeMode.END), False, False, 0)
        if c.note:
            texts.pack_start(styled_label("ⓘ " + c.note, "tm-dim", ellipsize=Pango.EllipsizeMode.END), False, False, 0)
        line.pack_start(texts, True, True, 0)
        size = styled_label(util.size(c.size) if c.size is not None else _("unbekannt"), "tm-mid", xalign=1)
        line.pack_start(size, False, False, 0)
        vbox.pack_start(line, False, False, 0)

        sub_checks = {}
        if c.key == "cache" and getattr(c, "parts", None):
            exp = Gtk.Expander(label=_("Ordner auswählen ({0})").format(len(c.parts)))
            grid = Gtk.Grid(column_spacing=24, row_spacing=2, margin_start=36)
            for i, (bytes_, name) in enumerate(c.parts):
                cb = Gtk.CheckButton(label=f"{name}  ({util.size(bytes_)})")
                cb.set_active(True)
                cb.connect("toggled", lambda *_x: self._update_selection())
                grid.attach(cb, i % 2, i // 2, 1, 1)
                sub_checks[name] = (cb, bytes_)
            exp.add(grid)
            vbox.pack_start(exp, False, False, 0)
        elif c.details:
            exp = Gtk.Expander(label=_("Details"))
            lbl = styled_label("\n".join(c.details), "tm-dim tm-num", margin_start=36, selectable=True)
            exp.add(lbl)
            vbox.pack_start(exp, False, False, 0)
        row.add(vbox)
        self.cat_rows[c.key] = (c, check, size, sub_checks)
        return row

    def _selected_cats(self):
        result = []
        for key, (c, check, _size, subs) in self.cat_rows.items():
            if check.get_active():
                if subs:
                    c.selected = [n for n, (cb, _b) in subs.items() if cb.get_active()]
                    if not c.selected:
                        continue
                result.append(c)
        return result

    def _selected_size(self, cats):
        total, unknown = 0, False
        for c in cats:
            subs = self.cat_rows[c.key][3]
            if subs:
                total += sum(b for n, (cb, b) in subs.items() if cb.get_active())
            elif c.size is None:
                unknown = True
            else:
                total += c.size
        return total, unknown

    def _update_selection(self):
        cats = self._selected_cats()
        total, unknown = self._selected_size(cats)
        text = _("Ausgewählt: {0}").format(util.size(total)) + (_(" + unbekannt") if unknown else "")
        set_text(self.sel_label, text)
        self.clean_btn.set_sensitive(bool(cats) and not self.busy)

    def clean_selected(self):
        cats = self._selected_cats()
        if not cats or self.busy:
            return
        total, unknown = self._selected_size(cats)
        lines = "\n".join("• " + c.title for c in cats)
        root = any(c.root for c in cats)
        warn = ""
        if any(c.key == "trash" for c in cats):
            warn += "\n\n" + _("Achtung: Der Papierkorb wird endgültig geleert.")
        if any(c.key == "cache" for c in cats):
            warn += "\n\n" + _("Bitte vorher Browser und andere Programme schließen.")
        if root:
            warn += "\n\n" + _("Für einen Teil der Schritte werden Administratorrechte benötigt – das Passwort wird gleich abgefragt.")
        title = (_("Mindestens {0} freigeben?") if unknown else _("{0} freigeben?")).format(util.size(total))
        if not actions.confirm(self, title,
                               lines + warn, _("Bereinigen")):
            return
        before = free_space()
        self._set_busy(True, _("Wird bereinigt …"))
        self._log_clear()
        user_cats = [c for c in cats if not c.root or c.key == "flatpak"]
        root_titles = [c.title for c in cats for _cmd in c.root_commands()]
        self._root_offset = len(user_cats)
        self.progress_start(len(user_cats) + len(root_titles), _("Wird bereinigt …"))

        def user_work():
            freed = 0
            for i, c in enumerate(user_cats):
                GLib.idle_add(self.progress_step, i, c.title)
                try:
                    n = c.clean()
                    freed += n
                    if not c.root:  # Root-Schritte werden nach dem Passwort-Teil protokolliert
                        GLib.idle_add(self._log, f"✓ {c.title}: {util.size(n)}")
                except Exception as e:
                    GLib.idle_add(self._log, f"✗ {c.title}: {e}")
            GLib.idle_add(after_user)

        def after_user():
            cmds, titles = [], []
            for c in cats:
                for cmd in c.root_commands():
                    cmds.append(cmd)
                    titles.append(c.title)
            if not cmds:
                finish()
                return False
            set_text(self.clean_status, _("Warte auf Passwort …"))
            self.progress_step(self._root_offset, titles[0])
            self.progress_wait(_("Bitte das Administrator-Passwort eingeben …"))

            def root_done(status, output):
                if status in (126, 127):
                    self._log(_("Abgebrochen – keine Administratorrechte erteilt."))
                else:
                    rcs = cleanup.step_results(output)
                    for i, t in enumerate(titles):
                        self._log(("✓ " if rcs.get(i) == 0 else "✗ ") + t)
                finish()
            run_root(cleanup.root_script(cmds), root_done, on_line=lambda l: self._on_root_line(l, titles))
            return False

        def finish():
            freed = max(0, free_space() - before)
            self.progress_end()
            self._set_busy(False)
            self._update_free()
            msg = _("Fertig – {0} freigegeben.").format(util.size(freed))
            self._log(msg)
            self.app.recorder.event("info", "cleanup", msg)
            self.scan_categories()
            actions.message(self, msg, _("Details stehen im Protokoll."), kind=Gtk.MessageType.INFO)

        threading.Thread(target=user_work, daemon=True).start()

    # ================================================================ Seite 2
    def _build_programs_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        top = Gtk.Box(spacing=10)
        top.pack_start(styled_label(_("Nicht benutzt seit mindestens:"), "tm-dim"), False, False, 0)
        self.age = Gtk.ComboBoxText()
        for days, label in AGES:
            self.age.append(str(days), _(label))
        self.age.set_active_id("90")
        self.age.connect("changed", lambda *_x: self.pfilter.refilter() or self._update_psel())
        top.pack_start(self.age, False, False, 0)
        self.psearch = Gtk.SearchEntry(placeholder_text=_("Programm suchen…"))
        self.psearch.connect("search-changed", lambda *_x: self.pfilter.refilter())
        top.pack_start(self.psearch, False, False, 0)
        self.pcount = styled_label("", "tm-dim", xalign=1)
        top.pack_end(self.pcount, False, False, 0)
        box.pack_start(top, False, False, 0)

        self.pstore = Gtk.ListStore(bool, GdkPixbuf.Pixbuf, str, str, str, GObject.TYPE_INT64, str, int, bool, str, str)
        self.pfilter = self.pstore.filter_new()
        self.pfilter.set_visible_func(self._pvisible)
        sort = Gtk.TreeModelSort.new_with_model(self.pfilter)
        sort.set_sort_column_id(P_DAYS, Gtk.SortType.DESCENDING)
        self.psort = sort
        view = self.pview = Gtk.TreeView(model=sort)
        toggle = Gtk.CellRendererToggle()
        toggle.connect("toggled", self._on_toggle)
        col = Gtk.TreeViewColumn("", toggle, active=P_SEL)
        col.set_cell_data_func(toggle, lambda c, cell, m, it, d: cell.set_property(
            "activatable", not m.get_value(it, P_PROT)) or cell.set_property("sensitive", not m.get_value(it, P_PROT)))
        view.append_column(col)
        c = Gtk.TreeViewColumn(_("Programm"))
        pix = Gtk.CellRendererPixbuf()
        c.pack_start(pix, False)
        c.add_attribute(pix, "pixbuf", P_ICON)
        txt = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END)
        c.pack_start(txt, True)
        c.add_attribute(txt, "text", P_NAME)
        c.set_expand(True)
        c.set_sort_column_id(P_NAME)
        c.set_cell_data_func(txt, lambda co, cell, m, it, d: cell.set_property(
            "foreground", "#888888" if m.get_value(it, P_PROT) else None) or cell.set_property(
            "foreground-set", m.get_value(it, P_PROT)))
        view.append_column(c)
        for title, colid, xalign in ((_("Typ"), P_KIND, 0), (_("Paket"), P_PKG, 0)):
            r = Gtk.CellRendererText(xalign=xalign, ellipsize=Pango.EllipsizeMode.END)
            c = Gtk.TreeViewColumn(title, r, text=colid)
            c.set_sort_column_id(colid)
            c.set_resizable(True)
            if colid == P_PKG:
                c.set_min_width(180)
            view.append_column(c)
        r = Gtk.CellRendererText(xalign=1)
        c = Gtk.TreeViewColumn(_("Größe"), r)
        c.set_cell_data_func(r, lambda co, cell, m, it, d: cell.set_property(
            "text", util.size(m.get_value(it, P_SIZE)) if m.get_value(it, P_SIZE) > 0 else "–"))
        c.set_sort_column_id(P_SIZE)
        c.set_alignment(1)
        view.append_column(c)
        r = Gtk.CellRendererText(xalign=1)
        c = Gtk.TreeViewColumn(_("Nicht benutzt seit"), r, text=P_LAST)
        c.set_sort_column_id(P_DAYS)
        c.set_alignment(1)
        view.append_column(c)
        r = Gtk.CellRendererText()
        c = Gtk.TreeViewColumn("", r, text=P_REASON)
        r.set_property("foreground", "#888888")
        view.append_column(c)
        psw = scrolled(view)
        psw.set_margin_start(0)
        psw.set_margin_end(0)
        box.pack_start(psw, True, True, 0)

        hint = _("„Nicht benutzt seit“ beruht auf dem letzten Zugriff auf die Programmdatei: Das Programm wurde "
                 "mindestens so lange nicht gestartet. Systembestandteile sind ausgegraut und geschützt.")
        if cleanup.noatime_warning():
            hint = _("Achtung: Das Dateisystem speichert keine Zugriffszeiten (noatime) – die Angaben sind "
                     "nicht zuverlässig.")
        h = styled_label(hint, "tm-dim")
        h.set_line_wrap(True)
        box.pack_start(h, False, False, 0)

        foot = Gtk.Box(spacing=10)
        self.psel_label = styled_label("", "tm-mid")
        foot.pack_start(self.psel_label, True, True, 0)
        self.pspinner = Gtk.Spinner()
        foot.pack_start(self.pspinner, False, False, 0)
        self.remove_btn = Gtk.Button(label=_("Ausgewählte deinstallieren"))
        self.remove_btn.get_style_context().add_class("tm-danger")
        self.remove_btn.connect("clicked", lambda *_x: self.remove_selected())
        foot.pack_start(self.remove_btn, False, False, 0)
        box.pack_start(foot, False, False, 0)
        return box

    def _on_page(self, stack, pspec):
        if stack.get_visible_child_name() == "programs" and not self.programs_loaded:
            self.load_programs()

    def load_programs(self):
        self.programs_loaded = True
        self.pspinner.start()
        set_text(self.psel_label, _("Wird ermittelt …"))

        def work():
            progs = cleanup.programs()
            GLib.idle_add(self._show_programs, progs)
        threading.Thread(target=work, daemon=True).start()

    def _show_programs(self, progs):
        self.pspinner.stop()
        self.pstore.clear()
        now = time.time()
        for p in progs:
            days = int((now - p.last_used) / 86400) if p.last_used else 99999
            if p.last_used is None:
                last = _("nie gestartet")
            elif days < 1:
                last = _("heute")
            else:
                last = _("{0} Tagen").format(util.num(days, 0)) + (_(" (seit Installation)") if p.never else "")
            kind = "Flatpak" if p.kind == "flatpak" else _("Paket")
            self.pstore.append([False, icons.for_gicon(p.icon), p.name, kind, p.package, int(p.size or 0), last,
                                days, p.protected, p.reason, p.installation or ""])
        self._update_psel()
        return False

    def _pvisible(self, model, it, data):
        days = int(self.age.get_active_id() or 0)
        if days and model.get_value(it, P_DAYS) < days:
            return False
        q = self.psearch.get_text().strip().lower()
        return not q or q in (model.get_value(it, P_NAME) or "").lower() or q in (model.get_value(it, P_PKG) or "").lower()

    def _on_toggle(self, cell, path):
        it = self.psort.get_iter(path)
        fit = self.psort.convert_iter_to_child_iter(it)
        sit = self.pfilter.convert_iter_to_child_iter(fit)
        if self.pstore[sit][P_PROT]:
            return
        self.pstore[sit][P_SEL] = not self.pstore[sit][P_SEL]
        self._update_psel()

    def _selected_programs(self):
        return [row for row in self.pstore if row[P_SEL]]

    def _update_psel(self):
        sel = self._selected_programs()
        visible = len(self.pfilter)
        set_text(self.pcount, _("{0} Programme").format(visible))
        size = sum(r[P_SIZE] for r in sel)
        set_text(self.psel_label, _("{0} ausgewählt · {1}").format(len(sel), util.size(size)) if sel else
                 _("Programme zum Deinstallieren anhaken"))
        self.remove_btn.set_sensitive(bool(sel) and not self.busy)

    def remove_selected(self):
        sel = self._selected_programs()
        if not sel or self.busy:
            return
        debs = [r[P_PKG] for r in sel if r[P_KIND] != "Flatpak"]
        flats = [(r[P_PKG], r[P_INST] or "system") for r in sel if r[P_KIND] == "Flatpak"]
        names = "\n".join("• " + r[P_NAME] for r in sel)
        self._set_busy(True, "")
        self.pspinner.start()

        def work():
            removed = cleanup.simulate_remove(debs) if debs else []
            GLib.idle_add(self._confirm_remove, sel, debs, flats, names, removed)
        threading.Thread(target=work, daemon=True).start()

    def _confirm_remove(self, sel, debs, flats, names, removed):
        self.pspinner.stop()
        self._set_busy(False)
        critical = cleanup.critical_in(removed)
        if critical:
            actions.message(self, _("Deinstallation nicht möglich"),
                            _("Dabei würden Systembestandteile entfernt: {0}").format(", ".join(critical[:8])))
            return False
        extra = [p for p in removed if p.split(":")[0] not in debs]
        size = cleanup.package_sizes(removed) + sum(r[P_SIZE] for r in sel if r[P_KIND] == "Flatpak")
        text = names
        if extra:
            text += "\n\n" + _("Zusätzlich entfernte Pakete ({0}):").format(len(extra)) + "\n" + \
                ", ".join(extra[:20]) + (" …" if len(extra) > 20 else "")
        text += "\n\n" + _("Gibt etwa {0} frei. Für die Deinstallation wird das Administrator-Passwort abgefragt.").format(
            util.size(size))
        if not actions.confirm(self, _("{0} Programm(e) deinstallieren?").format(len(sel)), text, _("Deinstallieren")):
            return False
        before = free_space()
        self._set_busy(True, "")
        self.pspinner.start()
        self._log_clear()
        set_text(self.psel_label, _("Warte auf Passwort …"))
        user_flats = [f for f in flats if f[1] == "user"]
        cmds = cleanup.remove_commands(debs, flats)
        titles = [_("Pakete deinstallieren") if c.startswith("DEBIAN_FRONTEND") else c.split()[-1] for c in cmds]
        self._root_offset = len(user_flats)
        self.progress_start(len(user_flats) + len(cmds), _("Wird deinstalliert …"))

        def finish(status, output):
            self.pspinner.stop()
            self.progress_end()
            self._set_busy(False)
            if status in (126, 127):
                self._log(_("Abgebrochen – keine Administratorrechte erteilt."))
            freed = max(0, free_space() - before)
            msg = _("Deinstallation beendet – {0} freigegeben.").format(util.size(freed))
            self._log(msg)
            self._update_free()
            if status not in (126, 127):
                self.app.recorder.event("info", "cleanup", msg)
                actions.message(self, msg, _("Details stehen im Protokoll."), kind=Gtk.MessageType.INFO)
            self.load_programs()

        def user_part():
            for i, f in enumerate(user_flats):
                GLib.idle_add(self.progress_step, i, f[0])
                cleanup.user_flatpak_remove([f])
            GLib.idle_add(root_part)

        def root_part():
            if cmds:
                self.progress_step(self._root_offset, titles[0])
                self.progress_wait(_("Bitte das Administrator-Passwort eingeben …"))
                run_root(cleanup.root_script(cmds), finish, on_line=lambda l: self._on_root_line(l, titles))
            else:
                finish(0, "")
            return False

        threading.Thread(target=user_part, daemon=True).start()
        return False

    # ================================================================ Protokoll
    def _log_clear(self):
        self.log.get_buffer().set_text("")

    def _log(self, text):
        if not text:
            return False
        buf = self.log.get_buffer()
        buf.insert(buf.get_end_iter(), text + "\n")
        buf.move_mark(self._log_end, buf.get_end_iter())
        self.log.scroll_mark_onscreen(self._log_end)  # immer die neueste Zeile zeigen
        return False

    def _copy_log(self):
        buf = self.log.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(text, -1)

    def _on_paned_alloc(self, paned, alloc):
        if not self._paned_init and alloc.height > 200:
            self._paned_init = True
            paned.set_position(alloc.height - 150)  # anfangs: Protokoll klein (ca. 5 Zeilen)

    def _show_log(self, big=False):
        h = self.paned.get_allocated_height()
        if big and h > 300 and self.paned.get_position() > h * 0.6:
            self.paned.set_position(int(h * 0.5))


def open_cleanup(app):
    win = CleanupWindow(app)
    win.present()
    return win
