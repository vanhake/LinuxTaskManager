"""Registerkarte „Leistung“: CPU, Arbeitsspeicher, Datenträger, Netzwerk, GPU."""

from ..i18n import _

import math
import time

from gi.repository import GLib, Gtk, Pango

from .. import sysinfo, util
from ..widgets import COLORS, HISTORY, Graph, SegmentBar
from . import Tab


def _dim(label):
    label.get_style_context().add_class("dim-label")
    return label


class DevicePage:
    """Detailseite eines Geräts mit Kopf, Graph(en) und Kennzahlen."""

    def __init__(self, title, subtitle, color):
        self.color = color
        self.dyn = {}
        self.static = {}
        self._dyn_count = 0
        self._static_count = 0
        box = self.widget = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=16)

        head = Gtk.Box(spacing=12)
        self.title = Gtk.Label(xalign=0)
        self.set_title(title)
        self.subtitle = Gtk.Label(xalign=1, ellipsize=Pango.EllipsizeMode.END)
        self.set_subtitle(subtitle)
        head.pack_start(self.title, False, False, 0)
        head.pack_end(self.subtitle, True, True, 0)
        box.pack_start(head, False, False, 4)

        self.graph_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.pack_start(self.graph_box, True, True, 0)

        # FlowBox: Kennzahlen und Details nebeneinander, bei schmalem Fenster untereinander
        stats = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=2,
                            column_spacing=40, row_spacing=14, margin_top=10, homogeneous=False)
        stats.set_valign(Gtk.Align.START)
        self.dyn_grid = Gtk.Grid(column_spacing=28, row_spacing=10)
        self.static_grid = Gtk.Grid(column_spacing=16, row_spacing=3)
        stats.add(self.dyn_grid)
        stats.add(self.static_grid)
        for child in stats.get_children():
            child.set_halign(Gtk.Align.START)
            child.set_can_focus(False)
        box.pack_start(stats, False, False, 0)

    def set_title(self, text):
        self.title.set_markup(f"<span size='xx-large'>{GLib.markup_escape_text(text)}</span>")

    def set_subtitle(self, text):
        self.subtitle.set_markup(f"<span size='large'>{GLib.markup_escape_text(text)}</span>")
        self.subtitle.set_tooltip_text(text)

    def add_graph(self, graph, caption, right="100 %", bottom=True, height=None):
        top = Gtk.Box()
        top.pack_start(_dim(Gtk.Label(label=caption, xalign=0)), True, True, 0)
        max_label = _dim(Gtk.Label(label=right, xalign=1))
        top.pack_end(max_label, False, False, 0)
        self.graph_box.pack_start(top, False, False, 0)
        if height:
            graph.set_size_request(200, height)
            self.graph_box.pack_start(graph, False, True, 0)
        else:
            self.graph_box.pack_start(graph, True, True, 0)
        if bottom:
            self.add_time_axis()
        return max_label

    def add_time_axis(self):
        bot = Gtk.Box()
        self.time_label = _dim(Gtk.Label(xalign=0))
        bot.pack_start(self.time_label, True, True, 0)
        bot.pack_end(_dim(Gtk.Label(label="0", xalign=1)), False, False, 0)
        self.graph_box.pack_start(bot, False, False, 0)

    def set_interval(self, interval):
        if hasattr(self, "time_label"):
            self.time_label.set_text(_('{0} Sekunden').format(util.num(HISTORY * interval, 0)))

    def add_dyn(self, key, caption, columns=3):
        i = self._dyn_count
        self._dyn_count += 1
        cell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        cell.pack_start(_dim(Gtk.Label(label=caption, xalign=0)), False, False, 0)
        value = Gtk.Label(xalign=0)
        cell.pack_start(value, False, False, 0)
        self.dyn_grid.attach(cell, i % columns, i // columns, 1, 1)
        self.dyn[key] = value

    def add_static(self, key, caption, value="–"):
        i = self._static_count
        self._static_count += 1
        self.static_grid.attach(_dim(Gtk.Label(label=caption + ":", xalign=0)), 0, i, 1, 1)
        v = Gtk.Label(label=value, xalign=0, selectable=True, wrap=True, max_width_chars=30)
        self.static_grid.attach(v, 1, i, 1, 1)
        self.static[key] = v

    def set(self, key, text):
        lbl = self.dyn.get(key)
        if lbl is not None:
            markup = f"<span size='x-large'>{GLib.markup_escape_text(text)}</span>"
            if lbl.get_label() != markup:
                lbl.set_markup(markup)
        else:
            lbl = self.static.get(key)
            if lbl is not None and lbl.get_text() != text:
                lbl.set_text(text)


class SidebarRow(Gtk.ListBoxRow):
    def __init__(self, key, color, title):
        super().__init__()
        self.key = key
        box = Gtk.Box(spacing=10, margin=6)
        self.graph = Graph(color, mini=True)
        box.pack_start(self.graph, False, False, 0)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.title = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        self.title.set_markup(f"<b>{GLib.markup_escape_text(title)}</b>")
        self.line1 = _dim(Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END))
        self.line2 = _dim(Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END))
        for w in (self.title, self.line1, self.line2):
            texts.pack_start(w, False, False, 0)
        box.pack_start(texts, True, True, 0)
        self.add(box)
        self.set_size_request(230, -1)

    def set_lines(self, l1, l2=""):
        if self.line1.get_text() != l1:
            self.line1.set_text(l1)
        if self.line2.get_text() != l2:
            self.line2.set_text(l2)


class Device:
    def __init__(self, key, row, page):
        self.key, self.row, self.page = key, row, page


class PerformanceTab(Tab):
    title = _("Leistung")

    def __init__(self, app):
        super().__init__(app)
        self.devices = {}
        self.order = []

        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.BROWSE)
        self.listbox.get_style_context().add_class("tm-devlist")
        self.listbox.connect("row-selected", self._on_row)
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.NONE)

        side = Gtk.ScrolledWindow()
        side.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        side.add(self.listbox)
        side.get_style_context().add_class("tm-devlist")
        paned = Gtk.Paned()
        paned.pack1(side, False, False)
        main = Gtk.ScrolledWindow()
        main.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        main.add(self.stack)
        paned.pack2(main, True, False)
        self.widget = paned

        self._build_cpu()
        self._build_mem()
        for i, name in enumerate(self.app.sampler.disks):
            self._build_disk(i, name)
        self.net_count = {_("Ethernet"): 0, _("WLAN"): 0, _("Virtuell"): 0}
        for name in self.app.sampler.adapters:
            self._build_net(name)
        for i, g in enumerate(self.app.sampler.gpus):
            self._build_gpu(i, g)
        self._net_static_t = 0
        self.listbox.select_row(self.devices["cpu"].row)
        self.set_interval(self.app.sampler.interval)

    def _add(self, key, title, page, color, position=None):
        row = SidebarRow(key, color, title)
        if position is None:
            self.listbox.add(row)
            self.order.append(key)
        else:
            self.listbox.insert(row, position)
            self.order.insert(position, key)
        self.stack.add_named(page.widget, key)
        dev = Device(key, row, page)
        self.devices[key] = dev
        row.show_all()
        page.widget.show_all()
        return dev

    def _on_row(self, listbox, row):
        if row is not None:
            self.stack.set_visible_child_name(row.key)

    def set_interval(self, interval):
        for d in self.devices.values():
            d.page.set_interval(interval)

    # ----------------------------------------------------------------- CPU
    def _build_cpu(self):
        info = self.cpu_info = sysinfo.cpu_info()
        color = COLORS["cpu"]
        page = DevicePage(_("CPU"), info["model"], color)
        self.cpu_graph = Graph(color)
        # Umschalten Gesamt / logische Prozessoren
        switch_box = Gtk.Box(spacing=6)
        self.cpu_mode = Gtk.ComboBoxText()
        self.cpu_mode.append("total", _("Gesamtauslastung"))
        self.cpu_mode.append("cores", _("Logische Prozessoren"))
        self.cpu_mode.set_active_id("total")
        switch_box.pack_end(self.cpu_mode, False, False, 0)
        switch_box.pack_end(_dim(Gtk.Label(label="Graph:")), False, False, 0)
        page.graph_box.pack_start(switch_box, False, False, 0)

        self.cpu_stack = Gtk.Stack()
        single = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        single.pack_start(self.cpu_graph, True, True, 0)
        self.cpu_stack.add_named(single, "total")
        n = info["logical"]
        cols = math.ceil(math.sqrt(n))
        if cols * (cols - 1) >= n:
            rows = cols - 1
        else:
            rows = cols
        grid = Gtk.Grid(column_spacing=4, row_spacing=4, column_homogeneous=True, row_homogeneous=True)
        self.core_graphs = []
        for i in range(n):
            g = Graph(color)
            g.set_size_request(60, 40)
            g.set_hexpand(True)
            g.set_vexpand(True)
            g.set_tooltip_text(_('Logischer Prozessor {0}').format(i))
            grid.attach(g, i % cols, i // cols, 1, 1)
            self.core_graphs.append(g)
        self.cpu_stack.add_named(grid, "cores")
        self.cpu_mode.connect("changed", lambda c: self.cpu_stack.set_visible_child_name(c.get_active_id()))

        top = Gtk.Box()
        top.pack_start(_dim(Gtk.Label(label=_("% Auslastung"), xalign=0)), True, True, 0)
        top.pack_end(_dim(Gtk.Label(label="100 %", xalign=1)), False, False, 0)
        page.graph_box.pack_start(top, False, False, 0)
        page.graph_box.pack_start(self.cpu_stack, True, True, 0)
        self.cpu_stack.set_size_request(-1, 220)
        page.add_time_axis()

        for key, cap in (("usage", _("Auslastung")), ("speed", _("Geschwindigkeit")), ("temp", _("Temperatur")),
                         ("procs", _("Prozesse")), ("threads", _("Threads")), ("handles", _("Handles")),
                         ("uptime", _("Betriebszeit"))):
            page.add_dyn(key, cap)
        page.add_static("base", _("Basisgeschwindigkeit"), util.ghz(info["base_mhz"]))
        page.add_static("sockets", _("Sockets"), str(info["sockets"]))
        page.add_static("cores", _("Kerne"), str(info["cores"]))
        page.add_static("logical", _("Logische Prozessoren"), str(info["logical"]))
        page.add_static("virt", _("Virtualisierung"), info["virtualization"])
        page.add_static("l1", _("L1-Cache"), info["l1"])
        page.add_static("l2", _("L2-Cache"), info["l2"])
        page.add_static("l3", _("L3-Cache"), info["l3"])
        self._add("cpu", _("CPU"), page, color)

    def _feed_cpu(self, s):
        d = self.devices["cpu"]
        self.cpu_graph.push(s.cpu)
        for g, v in zip(self.core_graphs, s.cpu_per_core):
            g.push(v)
        d.row.graph.push(s.cpu)
        speed = util.ghz(s.cpu_freq)
        d.row.set_lines(f"{util.pct(s.cpu)}  {speed}")
        p = d.page
        p.set("usage", util.pct(s.cpu))
        p.set("speed", speed)
        p.set("temp", f"{util.num(s.cpu_temp, 0)} °C" if s.cpu_temp is not None else "–")
        p.set("procs", util.num(len(s.procs), 0))
        p.set("threads", util.num(s.threads, 0))
        p.set("handles", util.num(s.handles, 0))
        p.set("uptime", util.duration(s.uptime))

    # ------------------------------------------------------- Arbeitsspeicher
    def _build_mem(self):
        color = COLORS["mem"]
        total = self.app.mem_total
        page = DevicePage(_("Arbeitsspeicher"), util.size(total), color)
        self.mem_graph = Graph(color)
        self.mem_max = page.add_graph(self.mem_graph, _("Speicherauslastung"), util.size(total))
        cap = Gtk.Label(label=_("Speicherzusammensetzung"), xalign=0, margin_top=8)
        page.graph_box.pack_start(_dim(cap), False, False, 0)
        self.mem_bar = SegmentBar(color)
        page.graph_box.pack_start(self.mem_bar, False, False, 0)
        for key, cap in (("used", _("In Verwendung")), ("avail", _("Verfügbar")), ("commit", _("Zugesichert")),
                         ("cached", _("Im Cache")), ("swap", _("Auslagerung (Swap)")),
                         ("shared", _("Gemeinsam genutzt"))):
            page.add_dyn(key, cap, columns=2)
        page.add_static("total", _("Gesamt"), util.size(total))
        page.add_static("buffers", _("Puffer"))
        page.add_static("dirty", _("Geändert (Dirty)"))
        page.add_static("slab", _("Kernel (Slab)"))
        page.add_static("swaptotal", _("Swap gesamt"))
        page.add_static("hw", _("Geschwindigkeit/Steckplätze"), _("nur mit Root (dmidecode) ermittelbar"))
        self._add("mem", _("Arbeitsspeicher"), page, color)

    def _feed_mem(self, s):
        d = self.devices["mem"]
        vm, sw, mi = s.vm, s.swap, s.meminfo
        used = vm.total - vm.available
        d.row.graph.push(vm.percent)
        self.mem_graph.push(vm.percent)
        d.row.set_lines(f"{util.size(used)}/{util.size(vm.total)} ({util.pct(vm.percent)})")
        p = d.page
        p.set("used", util.size(used))
        p.set("avail", util.size(vm.available))
        commit = mi.get("Committed_AS", 0)
        limit = mi.get("CommitLimit", 0)
        p.set("commit", f"{util.size(commit)}/{util.size(limit)}")
        cached = getattr(vm, "cached", 0) + mi.get("SReclaimable", 0)
        p.set("cached", util.size(cached))
        p.set("swap", f"{util.size(sw.used)}/{util.size(sw.total)}" if sw.total else "keine")
        p.set("shared", util.size(getattr(vm, "shared", 0)))
        p.set("buffers", util.size(getattr(vm, "buffers", 0)))
        p.set("dirty", util.size(mi.get("Dirty", 0)))
        p.set("slab", util.size(mi.get("Slab", 0)))
        p.set("swaptotal", util.size(sw.total))
        total = float(vm.total) or 1
        standby = max(0, vm.available - vm.free)
        self.mem_bar.set_segments([
            (used / total, 0.45, _('In Verwendung: {0}\nVon Programmen und Kernel belegt').format(util.size(used))),
            (standby / total, 0.18, _('Standby/Cache: {0}\nZwischengespeicherte Daten, bei Bedarf sofort freigebbar').format(util.size(standby))),
            (vm.free / total, 0.0, _('Frei: {0}\nUngenutzt').format(util.size(vm.free))),
        ])

    # ------------------------------------------------------------ Datenträger
    def _build_disk(self, index, name):
        info = sysinfo.disk_info(name)
        color = COLORS["disk"]
        title = _('Datenträger {0} ({1})').format(index, name)
        page = DevicePage(title, info["model"], color)
        g1 = Graph(color)
        page.add_graph(g1, _("Aktive Zeit"), "100 %", bottom=False)
        g2 = Graph(color, series=2, fixed_max=None, min_scale=1048576)
        lbl = page.add_graph(g2, _("Übertragungsrate (Lesen ─, Schreiben ┅)"), util.rate(1048576), height=90)
        g2.scale_changed = lambda v: lbl.set_text(util.rate(v))
        for key, cap in (("active", _("Aktive Zeit")), ("resp", _("Durchschn. Antwortzeit")),
                         ("read", _("Lesegeschwindigkeit")), ("write", _("Schreibgeschwindigkeit"))):
            page.add_dyn(key, cap, columns=2)
        page.add_static("cap", _("Kapazität"), util.size(info["capacity"]))
        page.add_static("fmt", _("Formatiert"), util.size(info["formatted"]) if info["formatted"] else "–")
        page.add_static("sys", _("Systemdatenträger"), _("Ja") if info["system"] else _("Nein"))
        page.add_static("swap", _("Auslagerung (Swap)"), _("Ja") if info["swap"] else _("Nein"))
        page.add_static("type", _("Typ"), info["type"])
        page.add_static("dev", _("Gerät"), f"/dev/{name}")
        dev = self._add(f"disk:{name}", title, page, color)
        dev.graphs = (g1, g2)
        dev.info = info

    def _feed_disk(self, dev, d):
        g1, g2 = dev.graphs
        g1.push(d["active"])
        g2.push(d["read"], d["write"])
        dev.row.graph.push(d["active"])
        dev.row.set_lines(dev.info["type"], util.pct(d["active"]))
        p = dev.page
        p.set("active", util.pct(d["active"]))
        p.set("resp", f"{util.num(d['resp'], 1)} ms")
        p.set("read", util.rate(d["read"]))
        p.set("write", util.rate(d["write"]))

    # --------------------------------------------------------------- Netzwerk
    def _build_net(self, name, position=None):
        info = sysinfo.net_info(name)
        color = COLORS["net"]
        title = info["type"] if info["type"] != _("Virtuell") else name
        page = DevicePage(title, name, color)
        g = Graph(color, series=2, fixed_max=None, min_scale=12500)
        lbl = page.add_graph(g, _("Durchsatz (Empfangen ─, Senden ┅)"), util.bits(12500))
        g.scale_changed = lambda v: lbl.set_text(util.bits(v))
        page.add_dyn("sent", _("Senden"), columns=2)
        page.add_dyn("recv", _("Empfangen"), columns=2)
        page.add_dyn("total_sent", _("Gesendet (gesamt)"), columns=2)
        page.add_dyn("total_recv", _("Empfangen (gesamt)"), columns=2)
        for key, cap in (("adapter", _("Adaptername")), ("ssid", _("SSID")), ("type", _("Verbindungstyp")),
                         ("ipv4", "IPv4-Adresse"), ("ipv6", "IPv6-Adresse"), ("speed", _("Geschwindigkeit")),
                         ("mac", _("MAC-Adresse")), ("driver", _("Treiber")), ("state", _("Status"))):
            page.add_static(key, cap)
        if position is None:
            # Netzwerkadapter immer vor den GPUs einsortieren
            position = len(self.order) - sum(k.startswith("gpu:") for k in self.devices)
        dev = self._add(f"net:{name}", title, page, color, position)
        dev.graph = g
        dev.name = name
        dev.totals = [0, 0]
        self._net_static(dev, info)

    def _net_static(self, dev, info=None):
        info = info or sysinfo.net_info(dev.name)
        dev.info = info
        p = dev.page
        p.set("adapter", info["name"])
        p.set("ssid", info["ssid"] or "–")
        p.set("type", info["type"])
        p.set("ipv4", info["ipv4"])
        p.set("ipv6", info["ipv6"].replace(", ", "\n"))
        sp = info["speed"]
        p.set("speed", _('{0} Gbit/s').format(util.num(sp / 1000, 1)) if sp >= 1000 and sp < 65535 else
              (_('{0} Mbit/s').format(sp) if 0 < sp < 65535 else "–"))
        p.set("mac", info["mac"])
        p.set("driver", info["driver"] or "–")
        p.set("state", _("Verbunden") if info["up"] and info["ipv4"] != "–" else _("Nicht verbunden"))

    def _feed_net(self, dev, d, dt):
        dev.graph.push(d["recv"], d["sent"])
        dev.row.graph.push(d["recv"] + d["sent"])
        dev.totals[0] += d["sent"] * dt
        dev.totals[1] += d["recv"] * dt
        if dev.info["up"] and dev.info["ipv4"] != "–" or d["sent"] or d["recv"]:
            dev.row.set_lines(dev.name, _("S: {0}  E: {1}").format(util.bits(d['sent']), util.bits(d['recv'])))
        else:
            dev.row.set_lines(dev.name, _("Nicht verbunden"))
        p = dev.page
        p.set("sent", util.bits(d["sent"]))
        p.set("recv", util.bits(d["recv"]))
        p.set("total_sent", util.size(dev.totals[0]))
        p.set("total_recv", util.size(dev.totals[1]))

    # -------------------------------------------------------------------- GPU
    def _build_gpu(self, index, g):
        color = COLORS["gpu"]
        title = _('GPU {0}').format(index)
        page = DevicePage(title, g["name"], color)
        graph = Graph(color)
        intel_estimate = g["driver"] not in ("amdgpu", "radeon", "nvidia")
        caption = _("Auslastung (geschätzt über Taktrate)") if intel_estimate else _("Auslastung")
        page.add_graph(graph, caption)
        for key, cap in (("usage", _("Auslastung")), ("freq", _("Takt")), ("temp", _("Temperatur")),
                         ("vram", _("Dedizierter GPU-Speicher"))):
            page.add_dyn(key, cap, columns=2)
        page.add_static("driver", _("Treiber"), g["driver"])
        page.add_static("slot", _("PCI-Steckplatz"), g["slot"])
        page.add_static("card", _("Gerät"), f"/dev/dri/{g['card']}")
        if intel_estimate:
            page.add_static("note", _("Hinweis"),
                            _("Echte Auslastung nur mit Root (intel_gpu_top); angezeigt wird die "
                            "aktuelle Taktrate relativ zum Maximaltakt."))
        dev = self._add(f"gpu:{g['card']}", title, page, color)
        dev.graph = graph
        dev.card = g["card"]
        dev.gname = g["name"]

    def _feed_gpu(self, dev, d):
        usage = d["usage"]
        dev.graph.push(usage or 0)
        dev.row.graph.push(usage or 0)
        short = dev.gname.replace(_("Intel "), "").replace(_("Advanced Micro Devices"), _("AMD"))
        dev.row.set_lines(short, util.pct(usage) if usage is not None else "–")
        p = dev.page
        p.set("usage", util.pct(usage) + (" (gesch.)" if d["estimated"] else "")
              if usage is not None else "–")
        if d["freq"] is not None:
            p.set("freq", f"{d['freq']} / {d['max_freq']} MHz")
        else:
            p.set("freq", "–")
        p.set("temp", f"{util.num(d['temp'], 0)} °C" if d["temp"] is not None else "–")
        if d["vram_total"]:
            p.set("vram", f"{util.size(d['vram_used'])}/{util.size(d['vram_total'])}")
        else:
            p.set("vram", _("gemeinsam mit RAM") if d["estimated"] else "–")

    # ---------------------------------------------------------------- Update
    def feed(self, s):
        """Wird bei jedem Snapshot aufgerufen (auch wenn nicht sichtbar)."""
        self._feed_cpu(s)
        self._feed_mem(s)
        for name, d in s.disks.items():
            dev = self.devices.get(f"disk:{name}")
            if dev:
                self._feed_disk(dev, d)
        # Netzwerkadapter dynamisch hinzufügen/entfernen
        current = {k[4:] for k in self.devices if k.startswith("net:")}
        for name in set(s.net) - current:
            self._build_net(name)
        for name in current - set(s.net):
            self._remove(f"net:{name}")
        refresh_static = time.monotonic() - self._net_static_t > 10
        if refresh_static:
            self._net_static_t = time.monotonic()
        for name, d in s.net.items():
            dev = self.devices.get(f"net:{name}")
            if dev:
                if refresh_static:
                    self._net_static(dev)
                self._feed_net(dev, d, s.dt)
        for card, d in s.gpus.items():
            dev = self.devices.get(f"gpu:{card}")
            if dev:
                self._feed_gpu(dev, d)

    def _remove(self, key):
        dev = self.devices.pop(key)
        if self.listbox.get_selected_row() is dev.row:
            self.listbox.select_row(self.devices["cpu"].row)
        self.listbox.remove(dev.row)
        self.stack.remove(dev.page.widget)
        self.order.remove(key)
