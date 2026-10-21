"""Registerkarte „Benutzer“: Ressourcen je angemeldetem Benutzer."""

import psutil
from gi.repository import GdkPixbuf, GObject, Gdk, Gtk, Pango

from .. import actions, icons, util
from ..treesync import TreeSync
from ..widgets import column_header, heat_cell_func, set_header
from . import CURRENT_USER, Tab, escape, scrolled, text_column

C_KEY, C_ICON, C_NAME, C_PID, C_STATUS, C_CPU, C_MEM, C_DISK, C_SESSION, C_KIND, C_WEIGHT, C_TIP = range(12)
K_USER, K_PROC = 0, 1


class UsersTab(Tab):
    title = "Benutzer"

    def __init__(self, app):
        super().__init__(app)
        self.store = Gtk.TreeStore(str, GdkPixbuf.Pixbuf, str, int, str, float, GObject.TYPE_INT64,
                                   float, str, int, int, str)
        self.sync = TreeSync(self.store)
        self.sorted = Gtk.TreeModelSort.new_with_model(self.store)
        self.sorted.set_sort_column_id(C_NAME, Gtk.SortType.ASCENDING)
        view = self.view = Gtk.TreeView(model=self.sorted)
        view.set_tooltip_column(C_TIP)
        view.set_enable_search(False)

        col = Gtk.TreeViewColumn("Benutzer")
        pix = Gtk.CellRendererPixbuf()
        col.pack_start(pix, False)
        col.add_attribute(pix, "pixbuf", C_ICON)
        txt = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END)
        col.pack_start(txt, True)
        col.add_attribute(txt, "text", C_NAME)
        col.add_attribute(txt, "weight", C_WEIGHT)
        col.set_expand(True)
        col.set_resizable(True)
        col.set_min_width(220)
        col.set_sort_column_id(C_NAME)
        col.set_widget(column_header("Benutzer"))
        view.append_column(col)

        c = text_column(view, "PID", C_PID, C_PID, 1.0,
                        func=lambda co, ce, m, it, d: ce.set_property(
                            "text", str(m.get_value(it, C_PID)) if m.get_value(it, C_PID) > 0 else ""))
        c.set_widget(column_header("PID"))
        c = text_column(view, "Status", C_STATUS, C_STATUS)
        c.set_widget(column_header("Status"))
        total_mem = self.app.mem_total
        self.h_cpu = column_header("CPU", "0 %")
        self.h_mem = column_header("Arbeitsspeicher", "0 %")
        self.h_disk = column_header("Datenträger", "")
        for title, colid, header, fmt, scale in (
                ("CPU", C_CPU, self.h_cpu, lambda v: util.pct(v, 1), lambda v: v / 100),
                ("Arbeitsspeicher", C_MEM, self.h_mem, util.mb, lambda v: v / (total_mem * 0.5)),
                ("Datenträger", C_DISK, self.h_disk, lambda v: "–" if v < 0 else util.mb_rate(v),
                 lambda v: v / (20 * 1048576))):
            cell = Gtk.CellRendererText(xalign=1.0)
            column = Gtk.TreeViewColumn(title, cell)
            column.set_cell_data_func(cell, heat_cell_func(colid, fmt, scale))
            column.set_sort_column_id(colid)
            column.set_resizable(True)
            column.set_min_width(110)
            column.set_alignment(1.0)
            column.set_widget(header)
            view.append_column(column)
        c = text_column(view, "Sitzung", C_SESSION, C_SESSION, ellipsize=True)
        c.set_widget(column_header("Sitzung"))
        c.set_min_width(200)

        view.connect("button-press-event", self._on_button)
        view.connect("key-press-event", self._on_key)

        self.show_all = Gtk.CheckButton(label="Alle Benutzer mit Prozessen anzeigen (inkl. Systemkonten)")
        self.show_all.set_active(self.app.settings["users_show_all"])
        self.show_all.connect("toggled", self._on_toggle)
        top = Gtk.Box(spacing=8, margin=10)
        top.pack_start(self.show_all, False, False, 0)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.pack_start(top, False, False, 0)
        box.pack_start(scrolled(view), True, True, 0)
        self.widget = box
        self._expanded_once = False

    def _on_toggle(self, cb):
        self.app.settings["users_show_all"] = cb.get_active()
        if self.app.last_snapshot:
            self.update(self.app.last_snapshot)

    def update(self, snap):
        set_header(self.h_cpu, "CPU", util.pct(snap.cpu))
        set_header(self.h_mem, "Arbeitsspeicher", util.pct(snap.vm.percent))
        sessions = {}
        for u in psutil.users():
            desc = u.terminal or ""
            if u.host:
                desc += f" ({u.host})"
            desc += f", seit {util.datetime(u.started)[:-3]}"
            sessions.setdefault(u.name, []).append(desc.strip(", "))
        by_user = {}
        for p in snap.procs.values():
            if p.pid == 2 or p.ppid == 2:
                continue
            by_user.setdefault(p.user, []).append(p)
        names = set(sessions) | {CURRENT_USER}
        if self.show_all.get_active():
            names |= set(by_user)
        rows = []
        user_icon = icons.named("avatar-default") or icons.named("user-info")
        for name in sorted(names):
            plist = by_user.get(name, [])
            key = f"u:{name}"
            known = [p.read_rate for p in plist if p.read_rate is not None]
            disk = sum((p.read_rate or 0) + (p.write_rate or 0) for p in plist) if known else -1.0
            sess = "; ".join(sessions.get(name, [])) or ("nicht angemeldet" if name != CURRENT_USER else "")
            rows.append((key, None, [
                key, user_icon, f"{name} ({len(plist)})", -1, "Aktiv" if name in sessions else "",
                sum(p.cpu for p in plist), sum(p.mem for p in plist), disk, sess, K_USER,
                Pango.Weight.BOLD, escape(sess)]))
            for p in plist:
                pk = f"p:{p.pid}"
                rows.append((pk, key, [
                    pk, icons.for_process(p.name, p.exe), p.name, p.pid, util.status_short(p.status),
                    p.cpu, p.mem, -1.0 if p.read_rate is None else p.read_rate + (p.write_rate or 0),
                    "", K_PROC, Pango.Weight.NORMAL, escape(p.cmdline or p.name)]))
        self.sync.sync(rows)
        if not self._expanded_once:
            self._expanded_once = True
            it = self.sync.iters.get(f"u:{CURRENT_USER}")
            if it is not None:
                ok, sit = self.sorted.convert_child_iter_to_iter(it)
                if ok:
                    self.view.expand_row(self.sorted.get_path(sit), False)

    def _selected(self):
        model, it = self.view.get_selection().get_selected()
        if it is None or model.get_value(it, C_KIND) != K_PROC:
            return None, None
        return model.get_value(it, C_PID), model.get_value(it, C_NAME)

    def end_selected(self):
        pid, name = self._selected()
        if pid:
            actions.end_task(self.app.window, pid, name)
            self.app.sampler.refresh_now()

    def _on_key(self, view, event):
        if event.keyval == Gdk.KEY_Delete:
            self.end_selected()
            return True
        return False

    def _on_button(self, view, event):
        if event.type != Gdk.EventType.BUTTON_PRESS or event.button != 3:
            return False
        hit = view.get_path_at_pos(int(event.x), int(event.y))
        if not hit:
            return False
        view.get_selection().select_path(hit[0])
        pid, name = self._selected()
        if not pid:
            return True
        menu = actions.process_menu(self.app.window, pid, name, goto_details=self.app.goto_details)
        menu.attach_to_widget(view, None)
        menu.popup_at_pointer(event)
        return True
