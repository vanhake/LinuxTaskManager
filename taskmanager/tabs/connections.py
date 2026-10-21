"""Registerkarte „Verbindungen“: offene Netzwerkverbindungen je Prozess."""

import socket
import time

import psutil
from gi.repository import GdkPixbuf, Gdk, Gtk, Pango

from .. import actions, icons
from ..treesync import TreeSync
from ..widgets import set_text, styled_label
from . import Tab, scrolled, text_column

C_ICON, C_PROC, C_PID, C_PROTO, C_LOCAL, C_REMOTE, C_STATUS, C_RAW = range(8)
STATUS_DE = {
    "ESTABLISHED": "Verbunden", "LISTEN": "Lauscht", "TIME_WAIT": "Wartet (TIME_WAIT)",
    "CLOSE_WAIT": "Schließen wartet", "SYN_SENT": "Verbindet…", "SYN_RECV": "Verbindet…",
    "FIN_WAIT1": "Wird getrennt", "FIN_WAIT2": "Wird getrennt", "LAST_ACK": "Wird getrennt",
    "CLOSING": "Wird geschlossen", "NONE": "–", "CLOSE": "Geschlossen",
}


def _addr(a):
    if not a:
        return ""
    ip, port = a.ip, a.port
    return f"[{ip}]:{port}" if ":" in ip else f"{ip}:{port}"


class ConnectionsTab(Tab):
    title = "Verbindungen"
    icon = "network-transmit-receive-symbolic"

    def __init__(self, app):
        super().__init__(app)
        self.store = Gtk.ListStore(GdkPixbuf.Pixbuf, str, int, str, str, str, str, str)
        self.sync = TreeSync(self.store)
        self.filter = self.store.filter_new()
        self.filter.set_visible_func(self._visible)
        self.sorted = Gtk.TreeModelSort.new_with_model(self.filter)
        self.sorted.set_sort_column_id(C_PROC, Gtk.SortType.ASCENDING)
        view = self.view = Gtk.TreeView(model=self.sorted)
        view.set_enable_search(False)

        col = Gtk.TreeViewColumn("Prozess")
        pix = Gtk.CellRendererPixbuf()
        col.pack_start(pix, False)
        col.add_attribute(pix, "pixbuf", C_ICON)
        txt = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END)
        col.pack_start(txt, True)
        col.add_attribute(txt, "text", C_PROC)
        col.set_sort_column_id(C_PROC)
        col.set_resizable(True)
        col.set_min_width(200)
        view.append_column(col)
        text_column(view, "PID", C_PID, C_PID, 1.0,
                    func=lambda co, ce, m, it, d: ce.set_property(
                        "text", str(m.get_value(it, C_PID)) if m.get_value(it, C_PID) > 0 else "–"))
        text_column(view, "Protokoll", C_PROTO, C_PROTO)
        text_column(view, "Lokale Adresse", C_LOCAL, C_LOCAL, width=230, ellipsize=True)
        text_column(view, "Remote-Adresse", C_REMOTE, C_REMOTE, expand=True, ellipsize=True)
        text_column(view, "Status", C_STATUS, C_STATUS, width=150)
        view.connect("button-press-event", self._on_button)

        self.search = Gtk.SearchEntry(placeholder_text="Prozess, Adresse oder Port…", width_chars=30)
        self.search.connect("search-changed", lambda e: self.filter.refilter())
        self.state = Gtk.ComboBoxText()
        for k, label in (("all", "Alle"), ("est", "Nur verbundene"), ("listen", "Nur lauschende")):
            self.state.append(k, label)
        self.state.set_active_id("all")
        self.state.connect("changed", lambda c: self.filter.refilter())
        self.summary = styled_label("", "tm-dim")
        top = Gtk.Box(spacing=8, margin=10)
        top.pack_start(self.search, False, False, 0)
        top.pack_start(self.state, False, False, 0)
        top.pack_end(self.summary, False, False, 0)
        hint = styled_label("Ohne Root-Rechte wird der Prozess nur für eigene Verbindungen angezeigt.",
                            "tm-dim", margin=8)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.pack_start(top, False, False, 0)
        sw = scrolled(view)
        sw.set_margin_start(10)
        sw.set_margin_end(10)
        box.pack_start(sw, True, True, 0)
        box.pack_start(hint, False, False, 0)
        self.widget = box
        self._last = 0

    def on_shown(self):
        self._last = 0

    def update(self, snap):
        if time.monotonic() - self._last < 2:
            return
        self._last = time.monotonic()
        try:
            conns = psutil.net_connections("inet")
        except (psutil.Error, OSError):
            return
        procs = snap.procs
        rows = []
        est = listen = 0
        for c in conns:
            proto = ("TCP" if c.type == socket.SOCK_STREAM else "UDP") + \
                    ("6" if c.family == socket.AF_INET6 else "")
            st = c.status if c.type == socket.SOCK_STREAM else "NONE"
            est += st == "ESTABLISHED"
            listen += st == "LISTEN"
            p = procs.get(c.pid) if c.pid else None
            name = p.name if p else ("System / anderer Benutzer" if not c.pid else str(c.pid))
            key = (c.pid, proto, _addr(c.laddr), _addr(c.raddr))
            rows.append((key, None, [icons.for_process(p.name, p.exe) if p else icons.named("network-server"),
                                     name, c.pid or 0, proto, _addr(c.laddr), _addr(c.raddr) or "–",
                                     STATUS_DE.get(st, st), st]))
        # Doppelte Schlüssel (z. B. gleiche UDP-Sockets) zusammenfassen
        seen = {}
        for r in rows:
            seen[r[0]] = r
        self.sync.sync(list(seen.values()))
        set_text(self.summary, f"{len(conns)} Verbindungen · {est} verbunden · {listen} lauschend")
        self.filter.refilter()

    def _visible(self, model, it, data):
        st = model.get_value(it, C_RAW)
        mode = self.state.get_active_id()
        if mode == "est" and st != "ESTABLISHED":
            return False
        if mode == "listen" and st != "LISTEN":
            return False
        q = self.search.get_text().strip().lower()
        if not q:
            return True
        return any(q in (model.get_value(it, c) or "").lower() for c in (C_PROC, C_LOCAL, C_REMOTE))

    def _on_button(self, view, event):
        if event.type != Gdk.EventType.BUTTON_PRESS or event.button != 3:
            return False
        hit = view.get_path_at_pos(int(event.x), int(event.y))
        if not hit:
            return False
        view.get_selection().select_path(hit[0])
        model, it = view.get_selection().get_selected()
        pid, name = model.get_value(it, C_PID), model.get_value(it, C_PROC)
        if not pid:
            return True
        menu = actions.process_menu(self.app.window, pid, name, goto_details=self.app.goto_details)
        menu.attach_to_widget(view, None)
        menu.popup_at_pointer(event)
        return True
