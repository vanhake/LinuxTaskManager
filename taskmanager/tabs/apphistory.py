"""Registerkarte „App-Verlauf“: kumulierte Nutzung je Programm."""

import time

from gi.repository import GdkPixbuf, GObject, Gtk

from .. import actions, icons, util
from ..treesync import TreeSync
from ..widgets import heat_cell_func
from . import Tab, fmt_func, scrolled, text_column

I64 = GObject.TYPE_INT64
C_ICON, C_NAME, C_CPU, C_READ, C_WRITE, C_TOTAL, C_USER = range(7)


class AppHistoryTab(Tab):
    title = "App-Verlauf"

    def __init__(self, app):
        super().__init__(app)
        self.history = app.history
        self.store = Gtk.ListStore(GdkPixbuf.Pixbuf, str, float, I64, I64, I64, str)
        self.sync = TreeSync(self.store)
        self.filter = self.store.filter_new()
        self.filter.set_visible_func(self._visible)
        self.sorted = Gtk.TreeModelSort.new_with_model(self.filter)
        self.sorted.set_sort_column_id(C_CPU, Gtk.SortType.DESCENDING)
        view = self.view = Gtk.TreeView(model=self.sorted)
        view.set_enable_search(False)

        col = Gtk.TreeViewColumn("Name")
        pix = Gtk.CellRendererPixbuf()
        col.pack_start(pix, False)
        col.add_attribute(pix, "pixbuf", C_ICON)
        txt = Gtk.CellRendererText()
        col.pack_start(txt, True)
        col.add_attribute(txt, "text", C_NAME)
        col.set_expand(True)
        col.set_resizable(True)
        col.set_sort_column_id(C_NAME)
        view.append_column(col)

        def heat_column(title, colid, fmt, scale_func):
            cell = Gtk.CellRendererText(xalign=1.0)
            column = Gtk.TreeViewColumn(title, cell)
            column.set_cell_data_func(cell, heat_cell_func(colid, fmt, scale_func))
            column.set_sort_column_id(colid)
            column.set_resizable(True)
            column.set_alignment(1.0)
            column.set_min_width(120)
            view.append_column(column)

        self._max = {"cpu": 1.0, "io": 1.0}
        heat_column("CPU-Zeit", C_CPU, util.cpu_time, lambda v: v / self._max["cpu"])
        heat_column("Datenträger gelesen", C_READ, util.size, lambda v: v / self._max["io"])
        heat_column("Datenträger geschrieben", C_WRITE, util.size, lambda v: v / self._max["io"])
        heat_column("E/A gesamt", C_TOTAL, util.size, lambda v: v / self._max["io"])
        text_column(view, "Benutzer", C_USER, C_USER)

        self.since = Gtk.Label(xalign=0)
        self.since.set_line_wrap(True)
        reset = Gtk.Button(label="Verlauf löschen")
        reset.connect("clicked", self._on_reset)
        self.search = Gtk.SearchEntry(placeholder_text="Programm suchen…")
        self.search.connect("search-changed", lambda e: self.filter.refilter())
        top = Gtk.Box(spacing=8, margin=10)
        top.pack_start(self.since, True, True, 0)
        top.pack_end(reset, False, False, 0)
        top.pack_end(self.search, False, False, 0)
        hint = Gtk.Label(
            label="Erfasst wird, solange der Taskmanager läuft. Die Daten werden in "
                  "~/.local/share/linux-taskmanager/ gespeichert.",
            xalign=0, margin=6)
        hint.get_style_context().add_class("dim-label")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.pack_start(top, False, False, 0)
        box.pack_start(scrolled(view), True, True, 0)
        box.pack_start(hint, False, False, 0)
        self.widget = box
        self._last = 0

    def _visible(self, model, it, data):
        q = self.search.get_text().strip().lower()
        return not q or q in (model.get_value(it, C_NAME) or "").lower()

    def _on_reset(self, button):
        if actions.confirm(self.app.window, "Möchten Sie den App-Verlauf löschen?",
                           "Alle gesammelten Nutzungsdaten werden zurückgesetzt.", "Verlauf löschen"):
            self.history.reset()
            self.update(None, force=True)

    def on_shown(self):
        self.update(None, force=True)

    def update(self, snap, force=False):
        # Kumulierte Werte ändern sich langsam – höchstens alle 3 s neu aufbauen
        if not force and time.monotonic() - self._last < 3:
            return
        self._last = time.monotonic()
        self.since.set_markup(
            f"Ressourcennutzung seit <b>{util.datetime(self.history.since)}</b> für alle Programme "
            "des Systems.")
        rows = []
        mx_cpu = mx_io = 1.0
        for name, (cpu, rd, wr, user) in self.history.data.items():
            mx_cpu = max(mx_cpu, cpu)
            mx_io = max(mx_io, rd, wr, rd + wr)
            rows.append((name, None, [icons.for_process(name), name, float(cpu), int(rd), int(wr),
                                      int(rd + wr), user]))
        self._max["cpu"], self._max["io"] = mx_cpu, mx_io
        self.sync.sync(rows)
