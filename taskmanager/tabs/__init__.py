"""Gemeinsame Bausteine für die Registerkarten."""

import getpass

from gi.repository import GLib, Gtk, Pango

CURRENT_USER = getpass.getuser()


class Tab:
    title = ""

    def __init__(self, app):
        self.app = app
        self.widget = None

    def update(self, snap):
        """Mit neuem Snapshot aktualisieren (nur wenn sichtbar)."""

    def on_shown(self):
        pass

    def focus_search(self):
        entry = getattr(self, "search", None)
        if entry is not None:
            entry.grab_focus()

    def end_selected(self):
        pass


def scrolled(child):
    sw = Gtk.ScrolledWindow()
    sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
    sw.set_shadow_type(Gtk.ShadowType.IN)
    sw.add(child)
    sw.set_vexpand(True)
    sw.set_margin_start(12)
    sw.set_margin_end(12)
    return sw


def text_column(view, title, col, sort_col=None, xalign=0.0, expand=False, func=None,
                width=None, weight_col=None, ellipsize=False):
    cell = Gtk.CellRendererText(xalign=xalign)
    if ellipsize:
        cell.set_property("ellipsize", Pango.EllipsizeMode.END)
    column = Gtk.TreeViewColumn(title, cell, text=col)
    if weight_col is not None:
        column.add_attribute(cell, "weight", weight_col)
    if func is not None:
        column.set_cell_data_func(cell, func)
    column.set_resizable(True)
    column.set_expand(expand)
    column.set_alignment(xalign)
    if width:
        column.set_fixed_width(width)
        column.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
    if sort_col is not None:
        column.set_sort_column_id(sort_col)
    view.append_column(column)
    return column


def fmt_func(col, formatter):
    def func(column, cell, model, it, data):
        cell.set_property("text", formatter(model.get_value(it, col)))
    return func


def selected_value(view, col):
    model, it = view.get_selection().get_selected()
    if it is None:
        return None
    return model.get_value(it, col)


def toolbar_row(*widgets_left, right=()):
    box = Gtk.Box(spacing=8, margin=10)
    for w in widgets_left:
        box.pack_start(w, False, False, 0)
    for w in reversed(right):
        box.pack_end(w, False, False, 0)
    return box


def escape(text):
    return GLib.markup_escape_text(text or "")


def compare(a, b):
    if isinstance(a, str):
        a, b = a.lower(), (b or "").lower()
    return (a > b) - (a < b)
