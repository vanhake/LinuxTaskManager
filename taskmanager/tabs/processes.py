"""Registerkarte „Prozesse“: Apps, Hintergrund- und Systemprozesse."""

import os

from gi.repository import GdkPixbuf, GObject, Gdk, Gtk, Pango

from .. import actions, icons, util
from ..treesync import TreeSync
from ..widgets import column_header, heat_cell_func, set_header
from . import CURRENT_USER, Tab, compare, escape, scrolled, text_column

try:
    import gi
    gi.require_version("Wnck", "3.0")
    from gi.repository import Wnck
except (ImportError, ValueError):
    Wnck = None

# Spalten des Modells
C_KEY, C_ICON, C_NAME, C_PID, C_STATUS, C_CPU, C_MEM, C_DISK, C_USER, C_KIND, C_ORDER, \
    C_WEIGHT, C_TIP = range(13)
K_GROUP, K_APP, K_CHILD, K_PROC = range(4)

GROUPS = [("g:apps", "Apps"), ("g:bg", "Hintergrundprozesse"), ("g:sys", "Systemprozesse")]


def _is_kernel_thread(p):
    return p.pid == 2 or p.ppid == 2


class ProcessesTab(Tab):
    title = "Prozesse"

    def __init__(self, app):
        super().__init__(app)
        self.query = ""
        self.screen = None
        if Wnck is not None and os.environ.get("XDG_SESSION_TYPE") != "wayland":
            try:
                self.screen = Wnck.Screen.get_default()
                if self.screen:
                    self.screen.force_update()
            except Exception:
                self.screen = None

        self.store = Gtk.TreeStore(str, GdkPixbuf.Pixbuf, str, int, str, float, GObject.TYPE_INT64,
                                   float, str, int, int, int, str)
        self.sync = TreeSync(self.store)
        self.filter = self.store.filter_new()
        self.filter.set_visible_func(self._visible)
        self.sorted = Gtk.TreeModelSort.new_with_model(self.filter)
        for col in (C_NAME, C_PID, C_STATUS, C_CPU, C_MEM, C_DISK, C_USER):
            self.sorted.set_sort_func(col, self._sort, col)
        self.sorted.set_sort_column_id(C_NAME, Gtk.SortType.ASCENDING)

        view = self.view = Gtk.TreeView(model=self.sorted)
        view.set_tooltip_column(C_TIP)
        view.set_enable_search(False)

        # Name mit Symbol
        col = Gtk.TreeViewColumn("Name")
        pix = Gtk.CellRendererPixbuf()
        col.pack_start(pix, False)
        col.add_attribute(pix, "pixbuf", C_ICON)
        txt = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END)
        col.pack_start(txt, True)
        col.add_attribute(txt, "text", C_NAME)
        col.add_attribute(txt, "weight", C_WEIGHT)
        col.set_expand(True)
        col.set_resizable(True)
        col.set_min_width(240)
        col.set_sort_column_id(C_NAME)
        col.set_widget(column_header("Name"))
        view.append_column(col)
        view.set_expander_column(col)

        c = text_column(view, "PID", C_PID, C_PID, 1.0,
                        func=lambda co, ce, m, it, d: ce.set_property(
                            "text", str(m.get_value(it, C_PID)) if m.get_value(it, C_PID) > 0 else ""))
        c.set_widget(column_header("PID"))
        c = text_column(view, "Status", C_STATUS, C_STATUS)
        c.set_widget(column_header("Status"))

        total_mem = self.app.mem_total
        self.h_cpu = column_header("CPU", "0 %")
        self.h_mem = column_header("Arbeitsspeicher", "0 %")
        self.h_disk = column_header("Datenträger", "0 %")
        for title, colid, header, fmt, scale in (
                ("CPU", C_CPU, self.h_cpu, lambda v: "" if v < 0 else util.pct(v, 1),
                 lambda v: v / 100),
                ("Arbeitsspeicher", C_MEM, self.h_mem, lambda v: "" if v < 0 else util.mb(v),
                 lambda v: v / (total_mem * 0.15)),
                ("Datenträger", C_DISK, self.h_disk,
                 lambda v: "" if v == -1 else ("–" if v == -2 else util.mb_rate(v)),
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

        c = text_column(view, "Benutzer", C_USER, C_USER)
        c.set_widget(column_header("Benutzer"))

        view.connect("button-press-event", self._on_button)
        view.connect("key-press-event", self._on_key)
        view.connect("row-activated", self._on_activated)
        view.get_selection().connect("changed", self._on_selection)

        self.search = Gtk.SearchEntry(placeholder_text="Name oder PID suchen…", width_chars=30)
        self.search.connect("search-changed", self._on_search)
        self.end_button = Gtk.Button(label="Task beenden")
        self.end_button.set_sensitive(False)
        self.end_button.get_style_context().add_class("tm-danger")
        self.end_button.connect("clicked", lambda *_: self.end_selected())

        top = Gtk.Box(spacing=8, margin=10)
        top.pack_start(self.search, False, False, 0)
        bottom = Gtk.Box(spacing=8, margin=10)
        bottom.pack_end(self.end_button, False, False, 0)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.pack_start(top, False, False, 0)
        box.pack_start(scrolled(view), True, True, 0)
        box.pack_start(bottom, False, False, 0)
        self.widget = box

    # --------------------------------------------------------------- Daten
    def _apps(self, procs):
        apps = {}
        if self.screen is None:
            return apps
        try:
            windows = self.screen.get_windows()
        except Exception:
            return apps
        for w in windows:
            if w.get_window_type() != Wnck.WindowType.NORMAL or w.is_skip_tasklist():
                continue
            pid = w.get_pid()
            if pid not in procs:
                continue
            a = apps.get(pid)
            if a is None:
                name = icons.app_name(w.get_class_group_name() or "", procs[pid].name)
                apps[pid] = a = {"name": name, "titles": [], "icon": w.get_mini_icon()}
            a["titles"].append(w.get_name() or "")
        return apps

    def update(self, snap):
        procs = snap.procs
        set_header(self.h_cpu, "CPU", util.pct(snap.cpu))
        set_header(self.h_mem, "Arbeitsspeicher", util.pct(snap.vm.percent))
        disk = max((d["active"] for d in snap.disks.values()), default=0)
        set_header(self.h_disk, "Datenträger", util.pct(disk))

        visible = {pid: p for pid, p in procs.items() if not _is_kernel_thread(p)}
        rows = []
        grouped = self.app.settings["group_by_type"]

        def proc_values(p, kind, key, order=0):
            disk_rate = -2.0 if p.read_rate is None else p.read_rate + (p.write_rate or 0)
            tip = escape(p.cmdline or p.name)
            return [key, icons.for_process(p.name, p.exe), p.name, p.pid, util.status_short(p.status),
                    p.cpu, p.mem, disk_rate, p.user, kind, order, Pango.Weight.NORMAL, tip]

        if not grouped:
            for pid, p in visible.items():
                key = f"p:{pid}"
                rows.append((key, None, proc_values(p, K_PROC, key)))
            self.sync.sync(rows)
            self._after_sync()
            return

        apps = self._apps(visible)
        owner = {}
        for pid in visible:
            chain = []
            cur = pid
            found = None
            while cur and cur in visible and len(chain) < 100:
                if cur in owner:
                    found = owner[cur]
                    break
                chain.append(cur)
                if cur in apps:
                    found = cur
                    break
                cur = visible[cur].ppid
            for c in chain:
                owner[c] = found

        members = {a: [] for a in apps}
        bg, sysp = [], []
        for pid, p in visible.items():
            a = owner.get(pid)
            if a is not None:
                members[a].append(p)
            elif p.user == CURRENT_USER:
                bg.append(p)
            else:
                sysp.append(p)

        def group_row(order, key, title, count):
            return (key, None, [key, None, f"{title} ({count})", -1, "", -1.0, -1, -1.0, "", K_GROUP,
                                order, Pango.Weight.BOLD, ""])

        if apps:
            rows.append(group_row(0, *GROUPS[0], len(apps)))
            for apid, info in apps.items():
                mem = members[apid]
                main = visible[apid]
                key = f"a:{apid}"
                rates = [m.read_rate for m in mem if m.read_rate is not None]
                disk_rate = sum((m.read_rate or 0) + (m.write_rate or 0) for m in mem) if rates else -2.0
                name = info["name"] + (f" ({len(mem)})" if len(mem) > 1 else "")
                tip = escape("\n".join(t for t in info["titles"] if t))
                status = util.status_short(main.status)
                rows.append((key, "g:apps", [
                    key, info["icon"] or icons.for_process(main.name, main.exe), name, apid, status,
                    sum(m.cpu for m in mem), sum(m.mem for m in mem), disk_rate, main.user,
                    K_APP, 0, Pango.Weight.NORMAL, tip]))
                if len(mem) > 1:
                    for m in sorted(mem, key=lambda m: m.pid):
                        ck = f"c:{m.pid}"
                        rows.append((ck, key, proc_values(m, K_CHILD, ck)))
        for order, plist in ((1, bg), (2, sysp)):
            if not plist:
                continue
            gkey, title = GROUPS[order]
            rows.append(group_row(order, gkey, title, len(plist)))
            for p in plist:
                key = f"p:{p.pid}"
                rows.append((key, gkey, proc_values(p, K_PROC, key)))

        first = not self.sync.iters
        self.sync.sync(rows)
        if first:
            # Gruppen beim ersten Mal aufklappen
            for gkey, _ in GROUPS:
                it = self.sync.iters.get(gkey)
                if it is not None:
                    self._expand_store_iter(it)
        else:
            for gkey, _ in GROUPS:
                it = self.sync.iters.get(gkey)
                if it is not None and gkey not in self._seen_groups:
                    self._expand_store_iter(it)
        self._seen_groups = {g for g, _ in GROUPS if g in self.sync.iters}
        self._after_sync()

    _seen_groups = set()

    def _expand_store_iter(self, store_it):
        ok, fit = self.filter.convert_child_iter_to_iter(store_it)
        if not ok:
            return
        ok, sit = self.sorted.convert_child_iter_to_iter(fit)
        if not ok:
            return
        self.view.expand_row(self.sorted.get_path(sit), False)

    def _after_sync(self):
        if self.query:
            self.filter.refilter()
        self._on_selection(self.view.get_selection())

    # ------------------------------------------------------- Filter/Sortierung
    def _match(self, model, it):
        q = self.query
        name = (model.get_value(it, C_NAME) or "").lower()
        return q in name or q == str(model.get_value(it, C_PID))

    def _visible(self, model, it, data):
        if not self.query:
            return True
        kind = model.get_value(it, C_KIND)
        if kind == K_GROUP:
            # Gruppe nur zeigen, wenn mindestens ein Eintrag passt
            child = model.iter_children(it)
            while child is not None:
                if self._visible(model, child, data):
                    return True
                child = model.iter_next(child)
            return False
        if self._match(model, it):
            return True
        if kind == K_CHILD:
            parent = model.iter_parent(it)
            return parent is not None and self._match(model, parent)
        if kind == K_APP:
            child = model.iter_children(it)
            while child is not None:
                if self._match(model, child):
                    return True
                child = model.iter_next(child)
        return False

    def _sort(self, model, a, b, col):
        ka, kb = model.get_value(a, C_KIND), model.get_value(b, C_KIND)
        if ka == K_GROUP or kb == K_GROUP:
            # Gruppen immer in fester Reihenfolge, unabhängig von der Sortierrichtung
            r = compare(model.get_value(a, C_ORDER), model.get_value(b, C_ORDER))
            _, order = self.sorted.get_sort_column_id()
            return -r if order == Gtk.SortType.DESCENDING else r
        r = compare(model.get_value(a, col), model.get_value(b, col))
        if r == 0 and col != C_NAME:
            r = compare(model.get_value(a, C_NAME), model.get_value(b, C_NAME))
        return r

    def _on_search(self, entry):
        self.query = entry.get_text().strip().lower()
        self.filter.refilter()
        if self.query:
            self.view.expand_all()

    # ---------------------------------------------------------- Interaktion
    def _selected(self):
        model, it = self.view.get_selection().get_selected()
        if it is None or model.get_value(it, C_KIND) == K_GROUP:
            return None, None
        name = model.get_value(it, C_NAME)
        return model.get_value(it, C_PID), name

    def _on_selection(self, sel):
        pid, _ = self._selected()
        self.end_button.set_sensitive(pid is not None)

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

    def _on_activated(self, view, path, column):
        if view.row_expanded(path):
            view.collapse_row(path)
        else:
            view.expand_row(path, False)

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
