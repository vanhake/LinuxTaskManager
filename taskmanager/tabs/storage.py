"""Registerkarte „Speicherplatz“: Laufwerksbelegung und Ordneranalyse (Treemap)."""

import os
import stat
import threading
import time

from gi.repository import Gio, GLib, Gtk, Pango

from .. import actions, util
from ..widgets import Treemap, UsageBar, card, set_text, styled_label
from . import Tab, scrolled

MAX_FILES = 40  # größte Dateien je Ordner einzeln, Rest zusammengefasst


class Node:
    __slots__ = ("name", "path", "size", "children", "is_dir", "parent", "count")

    def __init__(self, name, path, is_dir, parent=None):
        self.name, self.path, self.is_dir, self.parent = name, path, is_dir, parent
        self.size = 0
        self.children = []
        self.count = 0


class Scanner(threading.Thread):
    """Ermittelt Ordnergrößen (belegter Platz, wie du) ohne Dateisystemgrenzen zu überschreiten."""

    def __init__(self, root, on_progress, on_done):
        super().__init__(daemon=True)
        self.root = root
        self.on_progress = on_progress
        self.on_done = on_done
        self.cancelled = False
        self.files = 0
        self.errors = 0
        self._t = 0

    def run(self):
        try:
            dev = os.lstat(self.root).st_dev
        except OSError as e:
            GLib.idle_add(self.on_done, None, str(e))
            return
        node = Node(os.path.basename(self.root.rstrip("/")) or "/", self.root, True)
        self._scan(node, dev)
        GLib.idle_add(self.on_done, None if self.cancelled else node, None)

    def _scan(self, node, dev):
        files = []
        other = 0
        other_n = 0
        try:
            it = os.scandir(node.path)
        except OSError:
            self.errors += 1
            return
        with it:
            for e in it:
                if self.cancelled:
                    return
                try:
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    self.errors += 1
                    continue
                size = st.st_blocks * 512
                if stat.S_ISDIR(st.st_mode):
                    if st.st_dev != dev:  # andere Partition / Netzlaufwerk
                        continue
                    child = Node(e.name, e.path, True, node)
                    self._scan(child, dev)
                    child.size += size
                    node.children.append(child)
                    node.size += child.size
                    node.count += child.count + 1
                else:
                    self.files += 1
                    node.size += size
                    node.count += 1
                    files.append((size, e.name, e.path))
                now = time.monotonic()
                if now - self._t > 0.15:
                    self._t = now
                    GLib.idle_add(self.on_progress, self.files, node.path)
        files.sort(reverse=True)
        for size, name, path in files[:MAX_FILES]:
            f = Node(name, path, False, node)
            f.size = size
            node.children.append(f)
        for size, _, _ in files[MAX_FILES:]:
            other += size
            other_n += 1
        if other_n:
            f = Node(f"({other_n} weitere Dateien)", node.path, False, node)
            f.size = other
            node.children.append(f)
        node.children.sort(key=lambda n: n.size, reverse=True)


class StorageTab(Tab):
    title = "Speicherplatz"
    icon = "drive-harddisk-symbolic"

    def __init__(self, app):
        super().__init__(app)
        self.scanner = None
        self.root = None
        self.current = None
        self.mount_cards = {}

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, margin=18)

        head = Gtk.Box(spacing=10)
        head.pack_start(styled_label("Laufwerke", "tm-h1"), False, False, 0)
        self.summary = styled_label("", "tm-dim")
        head.pack_end(self.summary, False, False, 0)
        outer.pack_start(head, False, False, 0)

        self.flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=14,
                                row_spacing=14, homogeneous=True, max_children_per_line=4,
                                min_children_per_line=1)
        outer.pack_start(self.flow, False, False, 0)

        # ------------------------------------------------ Ordneranalyse
        an = card("Ordneranalyse")
        bar = Gtk.Box(spacing=8)
        self.up_btn = Gtk.Button.new_from_icon_name("go-up-symbolic", Gtk.IconSize.BUTTON)
        self.up_btn.set_tooltip_text("Übergeordneter Ordner")
        self.up_btn.connect("clicked", lambda *_: self._go_up())
        self.path_label = styled_label("Noch keine Analyse", "tm-mid", ellipsize=Pango.EllipsizeMode.START)
        self.path_label.set_hexpand(True)
        home_btn = Gtk.Button(label="Persönlicher Ordner")
        home_btn.get_style_context().add_class("tm-primary")
        home_btn.connect("clicked", lambda *_: self.analyze(os.path.expanduser("~")))
        choose_btn = Gtk.Button(label="Ordner wählen…")
        choose_btn.connect("clicked", lambda *_: self._choose())
        self.open_btn = Gtk.Button.new_from_icon_name("folder-open-symbolic", Gtk.IconSize.BUTTON)
        self.open_btn.set_tooltip_text("Im Dateimanager öffnen")
        self.open_btn.connect("clicked", lambda *_: self._open(self.current.path if self.current else None))
        self.cancel_btn = Gtk.Button(label="Abbrechen")
        self.cancel_btn.get_style_context().add_class("tm-danger")
        self.cancel_btn.connect("clicked", lambda *_: self._cancel())
        self.spinner = Gtk.Spinner()
        for w in (self.up_btn, self.path_label):
            bar.pack_start(w, w is self.path_label, True, 0)
        for w in (self.spinner, self.cancel_btn, self.open_btn, choose_btn, home_btn):
            bar.pack_end(w, False, False, 0)
        an.pack_start(bar, False, False, 0)
        self.progress = styled_label("Wähle einen Ordner oder ein Laufwerk zum Analysieren. "
                                     "Gezählt wird der tatsächlich belegte Platz.", "tm-dim",
                                     ellipsize=Pango.EllipsizeMode.MIDDLE)
        an.pack_start(self.progress, False, False, 0)

        self.treemap = Treemap()
        self.treemap.format_size = util.size
        self.treemap.activate = self._on_treemap
        self.treemap.set_vexpand(True)

        self.store = Gtk.ListStore(object, str, str, float, str, str)  # node, icon, name, pct, size, pcttext
        view = self.view = Gtk.TreeView(model=self.store)
        view.set_headers_visible(True)
        col = Gtk.TreeViewColumn("Name")
        pix = Gtk.CellRendererPixbuf()
        col.pack_start(pix, False)
        col.add_attribute(pix, "icon-name", 1)
        txt = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END)
        col.pack_start(txt, True)
        col.add_attribute(txt, "text", 2)
        col.set_expand(True)
        view.append_column(col)
        prog = Gtk.CellRendererProgress()
        pc = Gtk.TreeViewColumn("Anteil", prog, value=3, text=5)
        pc.set_min_width(110)
        view.append_column(pc)
        sc = Gtk.TreeViewColumn("Größe", Gtk.CellRendererText(xalign=1), text=4)
        sc.set_alignment(1)
        view.append_column(sc)
        view.connect("row-activated", self._on_row)
        view.connect("button-press-event", self._on_button)

        paned = Gtk.Paned()
        paned.pack1(self.treemap, True, False)
        lst = scrolled(view)
        lst.set_size_request(340, -1)
        paned.pack2(lst, False, False)
        paned.set_size_request(-1, 420)
        an.pack_start(paned, True, True, 0)
        outer.pack_start(an, True, True, 0)

        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.add(outer)
        self.widget = sw
        self._set_busy(False)

    # ------------------------------------------------------ Laufwerkskacheln
    def update(self, s):
        total = used = 0
        keys = [m["mount"] for m in s.mounts]
        for k in list(self.mount_cards):
            if k not in keys:
                child = self.mount_cards.pop(k)["card"].get_parent()
                self.flow.remove(child)
        for m in s.mounts:
            total += m["total"]
            used += m["used"]
            c = self.mount_cards.get(m["mount"])
            if c is None:
                c = self.mount_cards[m["mount"]] = self._mount_card(m)
                self.flow.add(c["card"])
                self.flow.show_all()
            set_text(c["pct"], util.pct(m["percent"]))
            c["bar"].set_fraction(m["percent"] / 100)
            set_text(c["used"], f"{util.size(m['used'])} belegt")
            set_text(c["free"], f"{util.size(m['free'])} frei von {util.size(m['total'])}")
        set_text(self.summary, f"Gesamt: {util.size(used)} von {util.size(total)} belegt")

    def _mount_card(self, m):
        title = "System" if m["mount"] == "/" else os.path.basename(m["mount"]) or m["mount"]
        c = card()
        head = Gtk.Box(spacing=10)
        head.pack_start(Gtk.Image.new_from_icon_name(
            "drive-harddisk-system-symbolic" if m["mount"] == "/" else "drive-harddisk-symbolic",
            Gtk.IconSize.LARGE_TOOLBAR), False, False, 0)
        names = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        names.pack_start(styled_label(title, "tm-mid"), False, False, 0)
        names.pack_start(styled_label(f"{m['mount']} · {m['device']} · {m['fstype']}", "tm-dim",
                                      ellipsize=Pango.EllipsizeMode.END), False, False, 0)
        head.pack_start(names, True, True, 0)
        pct = styled_label("", "tm-big", xalign=1)
        head.pack_end(pct, False, False, 0)
        c.pack_start(head, False, False, 0)
        bar = UsageBar("disk", height=14)
        c.pack_start(bar, False, False, 0)
        info = Gtk.Box()
        used = styled_label("", "tm-num")
        free = styled_label("", "tm-dim tm-num", xalign=1)
        info.pack_start(used, False, False, 0)
        info.pack_end(free, False, False, 0)
        c.pack_start(info, False, False, 0)
        btn = Gtk.Button(label="Analysieren")
        btn.set_halign(Gtk.Align.END)
        btn.connect("clicked", lambda *_: self.analyze(m["mount"]))
        c.pack_start(btn, False, False, 0)
        c.set_size_request(260, -1)
        return {"card": c, "pct": pct, "bar": bar, "used": used, "free": free}

    # ---------------------------------------------------------- Analyse
    def analyze(self, path):
        self._cancel()
        self.root = None
        self.current = None
        self.store.clear()
        self.treemap.set_items([])
        set_text(self.path_label, path)
        self.scanner = Scanner(path, self._on_progress, self._on_done)
        self._started = time.monotonic()
        self._set_busy(True)
        self.scanner.start()

    def _cancel(self):
        if self.scanner is not None:
            self.scanner.cancelled = True
            self.scanner = None
            self._set_busy(False)
            self.progress.set_text("Analyse abgebrochen.")

    def _set_busy(self, busy):
        self.cancel_btn.set_visible(busy)
        self.cancel_btn.set_no_show_all(not busy)
        if busy:
            self.spinner.start()
        else:
            self.spinner.stop()
        self.up_btn.set_sensitive(not busy and self.current is not None and self.current.parent is not None)
        self.open_btn.set_sensitive(self.current is not None)

    def _on_progress(self, files, path):
        if self.scanner is not None:
            self.progress.set_text(f"{util.num(files, 0)} Dateien gelesen … {path}")
        return False

    def _on_done(self, node, error):
        sc = self.scanner
        self.scanner = None
        self._set_busy(False)
        if error:
            actions.message(self.app.window, "Analyse fehlgeschlagen", error)
            return False
        if node is None:
            return False
        secs = time.monotonic() - self._started
        errs = f", {sc.errors} ohne Zugriff" if sc and sc.errors else ""
        self.progress.set_text(f"{util.num(sc.files if sc else 0, 0)} Dateien in {util.num(secs, 1)} s "
                               f"analysiert{errs}. Klicke auf Ordner, um tiefer zu gehen.")
        self.root = node
        self.show_node(node)
        return False

    def show_node(self, node):
        self.current = node
        set_text(self.path_label, f"{node.path}  —  {util.size(node.size)}")
        self.treemap.set_items([(c.name, c.size, c, c.is_dir) for c in node.children])
        self.store.clear()
        total = node.size or 1
        for c in node.children:
            frac = c.size / total * 100
            self.store.append([c, "folder-symbolic" if c.is_dir else "text-x-generic-symbolic", c.name,
                               frac, util.size(c.size), util.pct(frac, 1)])
        self._set_busy(False)

    def _go_up(self):
        if self.current is not None and self.current.parent is not None:
            self.show_node(self.current.parent)

    def _on_treemap(self, item, event):
        node = item[2]
        if event.button == 3:
            self._menu(node, event)
        elif node.is_dir and node.children:
            self.show_node(node)

    def _on_row(self, view, path, column):
        node = self.store[path][0]
        if node.is_dir and node.children:
            self.show_node(node)

    def _on_button(self, view, event):
        if event.button != 3:
            return False
        hit = view.get_path_at_pos(int(event.x), int(event.y))
        if not hit:
            return False
        view.get_selection().select_path(hit[0])
        self._menu(self.store[hit[0]][0], event)
        return True

    def _menu(self, node, event):
        menu = Gtk.Menu()
        if node.is_dir:
            mi = Gtk.MenuItem(label="Öffnen (in Analyse)")
            mi.connect("activate", lambda *_: self.show_node(node))
            mi.set_sensitive(bool(node.children))
            menu.append(mi)
        mi = Gtk.MenuItem(label="Im Dateimanager zeigen")
        mi.connect("activate", lambda *_: self._open(node.path if node.is_dir else os.path.dirname(node.path)))
        menu.append(mi)
        menu.show_all()
        menu.attach_to_widget(self.widget, None)
        menu.popup_at_pointer(event)

    def _open(self, path):
        if not path:
            return
        try:
            Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(path).get_uri(), None)
        except GLib.Error as e:
            actions.message(self.app.window, "Ordner konnte nicht geöffnet werden", e.message)

    def _choose(self):
        fc = Gtk.FileChooserNative.new("Ordner zum Analysieren wählen", self.app.window,
                                       Gtk.FileChooserAction.SELECT_FOLDER, "Analysieren", None)
        if fc.run() == Gtk.ResponseType.ACCEPT:
            self.analyze(fc.get_filename())
