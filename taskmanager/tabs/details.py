"""Registerkarte „Details“: flache Liste aller Prozesse mit vielen Spalten."""

from gi.repository import GdkPixbuf, GObject, Gdk, Gtk, Pango

from .. import actions, icons, util
from ..treesync import TreeSync
from ..widgets import heat_cell_func
from . import Tab, scrolled

I64 = GObject.TYPE_INT64
# (Titel, Typ, Formatierer, rechtsbündig, Heatmap-Skala)
COLUMNS = [
    ("Name", str, None, False, None),
    ("PID", int, str, True, None),
    ("PPID", int, str, True, None),
    ("Status", str, None, False, None),
    ("Benutzer", str, None, False, None),
    ("CPU", float, lambda v: util.num(v, 1), True, lambda v: v / 100),
    ("CPU-Zeit", float, util.cpu_time, True, None),
    ("Arbeitsspeicher (privat)", I64, util.mb, True, None),
    ("RSS", I64, util.mb, True, None),
    ("Virtuell", I64, util.mb, True, None),
    ("Threads", int, str, True, None),
    ("Handles", int, lambda v: "–" if v < 0 else str(v), True, None),
    ("Priorität", int, actions.priority_name, False, None),
    ("Lesen/s", float, lambda v: "–" if v < 0 else util.rate(v), True, None),
    ("Schreiben/s", float, lambda v: "–" if v < 0 else util.rate(v), True, None),
    ("Gestartet", float, util.datetime, False, None),
    ("Pfad", str, None, False, None),
    ("Befehlszeile", str, None, False, None),
]
OFFSET = 1  # Spalte 0 = Symbol
C_NAME, C_PID = OFFSET + 0, OFFSET + 1
C_CMD = OFFSET + len(COLUMNS) - 1
C_USER = OFFSET + 4


class DetailsTab(Tab):
    title = "Details"

    def __init__(self, app):
        super().__init__(app)
        self.query = ""
        types = [GdkPixbuf.Pixbuf] + [c[1] for c in COLUMNS]
        self.store = Gtk.ListStore(*types)
        self.sync = TreeSync(self.store)
        self.filter = self.store.filter_new()
        self.filter.set_visible_func(self._visible)
        self.sorted = Gtk.TreeModelSort.new_with_model(self.filter)
        self.sorted.set_sort_column_id(C_NAME, Gtk.SortType.ASCENDING)
        view = self.view = Gtk.TreeView(model=self.sorted)
        view.set_enable_search(False)
        view.set_tooltip_column(-1)
        self.columns = {}
        hidden = set(self.app.settings["details_hidden_columns"])
        for i, (title, typ, fmt, right, heat) in enumerate(COLUMNS):
            col_id = OFFSET + i
            column = Gtk.TreeViewColumn(title)
            if i == 0:
                pix = Gtk.CellRendererPixbuf()
                column.pack_start(pix, False)
                column.add_attribute(pix, "pixbuf", 0)
            cell = Gtk.CellRendererText(xalign=1.0 if right else 0.0)
            if typ is str:
                cell.set_property("ellipsize", Pango.EllipsizeMode.END)
            column.pack_start(cell, True)
            if heat:
                column.set_cell_data_func(cell, heat_cell_func(col_id, fmt, heat))
            elif fmt:
                column.set_cell_data_func(cell, self._fmt(col_id, fmt))
            else:
                column.add_attribute(cell, "text", col_id)
            column.set_sort_column_id(col_id)
            column.set_resizable(True)
            column.set_reorderable(True)
            column.set_alignment(1.0 if right else 0.0)
            if title in ("Name",):
                column.set_min_width(180)
            if title in ("Befehlszeile", "Pfad"):
                column.set_min_width(250)
                column.set_expand(title == "Befehlszeile")
            column.set_visible(title not in hidden)
            view.append_column(column)
            self.columns[title] = column

        view.connect("button-press-event", self._on_button)
        view.connect("key-press-event", self._on_key)
        view.get_selection().connect("changed", lambda s: self._update_buttons())

        self.search = Gtk.SearchEntry(placeholder_text="Name, PID, Benutzer oder Befehl…", width_chars=34)
        self.search.connect("search-changed", self._on_search)
        cols_btn = Gtk.MenuButton(label="Spalten auswählen")
        cols_btn.set_popover(self._columns_popover(cols_btn))
        self.end_button = Gtk.Button(label="Task beenden")
        self.end_button.connect("clicked", lambda *_: self.end_selected())
        self.end_button.set_sensitive(False)
        self.end_button.get_style_context().add_class("tm-danger")
        top = Gtk.Box(spacing=8, margin=10)
        top.pack_start(self.search, False, False, 0)
        top.pack_end(cols_btn, False, False, 0)
        bottom = Gtk.Box(spacing=8, margin=10)
        bottom.pack_end(self.end_button, False, False, 0)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.pack_start(top, False, False, 0)
        box.pack_start(scrolled(view), True, True, 0)
        box.pack_start(bottom, False, False, 0)
        self.widget = box
        self._pending_select = None

    @staticmethod
    def _fmt(col, fmt):
        def func(column, cell, model, it, data):
            cell.set_property("text", fmt(model.get_value(it, col)))
        return func

    def _columns_popover(self, relative):
        pop = Gtk.Popover(relative_to=relative)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin=8, spacing=2)
        for title in self.columns:
            if title == "Name":
                continue
            cb = Gtk.CheckButton(label=title)
            cb.set_active(self.columns[title].get_visible())
            cb.connect("toggled", self._on_column_toggled, title)
            box.pack_start(cb, False, False, 0)
        box.show_all()
        pop.add(box)
        return pop

    def _on_column_toggled(self, cb, title):
        self.columns[title].set_visible(cb.get_active())
        self.app.settings["details_hidden_columns"] = [
            t for t, c in self.columns.items() if not c.get_visible()]

    def update(self, snap):
        rows = []
        for pid, p in snap.procs.items():
            vals = [
                icons.for_process(p.name, p.exe), p.name, pid, p.ppid, util.status_de(p.status), p.user,
                p.cpu, p.cpu_time, p.mem, p.rss, p.vms, p.threads,
                -1 if p.fds is None else p.fds, p.nice,
                -1.0 if p.read_rate is None else p.read_rate,
                -1.0 if p.write_rate is None else p.write_rate,
                p.create_time, p.exe, p.cmdline,
            ]
            rows.append((pid, None, vals))
        self.sync.sync(rows)
        if self.query:
            self.filter.refilter()
        if self._pending_select is not None:
            self.select_pid(self._pending_select)
        self._update_buttons()

    def select_pid(self, pid):
        it = self.sync.iters.get(pid)
        if it is None:
            self._pending_select = pid
            return
        self._pending_select = None
        if self.query:
            self.search.set_text("")
            self.query = ""
            self.filter.refilter()
        ok, fit = self.filter.convert_child_iter_to_iter(it)
        if not ok:
            return
        ok, sit = self.sorted.convert_child_iter_to_iter(fit)
        if not ok:
            return
        path = self.sorted.get_path(sit)
        self.view.get_selection().select_path(path)
        self.view.scroll_to_cell(path, None, True, 0.5, 0.0)
        self.view.grab_focus()

    def _visible(self, model, it, data):
        q = self.query
        if not q:
            return True
        return (q in (model.get_value(it, C_NAME) or "").lower()
                or q == str(model.get_value(it, C_PID))
                or q in (model.get_value(it, C_USER) or "").lower()
                or q in (model.get_value(it, C_CMD) or "").lower())

    def _on_search(self, entry):
        self.query = entry.get_text().strip().lower()
        self.filter.refilter()

    def _selected(self):
        model, it = self.view.get_selection().get_selected()
        if it is None:
            return None, None
        return model.get_value(it, C_PID), model.get_value(it, C_NAME)

    def _update_buttons(self):
        self.end_button.set_sensitive(self._selected()[0] is not None)

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
        menu = actions.process_menu(self.app.window, pid, name, details=True)
        menu.attach_to_widget(view, None)
        menu.popup_at_pointer(event)
        return True
