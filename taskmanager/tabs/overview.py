"""Startseite „Übersicht“: Dashboard mit allen wichtigen Werten auf einen Blick."""

from ..i18n import _

import time

import psutil
from gi.repository import Gtk, Pango

from .. import icons, sysinfo, util
from ..widgets import Graph, RingGauge, UsageBar, card, set_text, styled_label
from . import Tab

STATUS_DE = {_("Charging"): _("Wird geladen"), _("Discharging"): _("Entlädt"), _("Full"): _("Voll"),
             _("Not charging"): _("Netzbetrieb"), _("Unknown"): _("Unbekannt")}


def kv_grid(rows):
    """Raster aus Schlüssel/Wert-Paaren; gibt (grid, {key: value_label}) zurück."""
    grid = Gtk.Grid(column_spacing=12, row_spacing=5)
    labels = {}
    for i, (key, caption) in enumerate(rows):
        grid.attach(styled_label(caption, "tm-dim"), 0, i, 1, 1)
        v = styled_label("–", "tm-num", ellipsize=Pango.EllipsizeMode.END)
        v.set_hexpand(True)
        grid.attach(v, 1, i, 1, 1)
        labels[key] = v
    return grid, labels


class OverviewTab(Tab):
    title = _("Übersicht")
    icon = "view-grid-symbolic"

    def __init__(self, app):
        super().__init__(app)
        self.cpu_info = sysinfo.cpu_info()
        self.os = sysinfo.os_info()
        self.gpus = app.sampler.gpus
        self._conn_t = 0
        self._conn_text = "–"

        grid = Gtk.Grid(column_spacing=14, row_spacing=14, column_homogeneous=True, margin=18)

        # ---------------- Zeile 1: Ringe
        self.cpu_ring = RingGauge("cpu")
        g, self.cpu_kv = kv_grid([("speed", _("Takt")), ("temp", _("Temperatur")), ("load", _("Last 1/5/15")),
                                  ("procs", _("Prozesse"))])
        cores = Gtk.Grid(column_spacing=8, row_spacing=4)
        self.core_bars = []
        n = self.cpu_info["logical"]
        cols = 2 if n <= 8 else 4
        for i in range(n):
            bar = UsageBar("cpu", height=6)
            bar.set_tooltip_text(_('Logischer Prozessor {0}').format(i))
            cores.attach(bar, i % cols, i // cols, 1, 1)
            self.core_bars.append(bar)
        grid.attach(self._ring_card(_("Prozessor"), self.cpu_ring, g, extra=cores), 0, 0, 1, 1)

        self.mem_ring = RingGauge("mem")
        g, self.mem_kv = kv_grid([("used", _("Belegt")), ("avail", _("Verfügbar")), ("cache", _("Cache")),
                                  ("swap", _("Swap"))])
        self.swap_bar = UsageBar("mem", height=6)
        grid.attach(self._ring_card(_("Arbeitsspeicher"), self.mem_ring, g, extra=self.swap_bar), 1, 0, 1, 1)

        self.gpu_ring = RingGauge("gpu")
        g, self.gpu_kv = kv_grid([("name", _("Modell")), ("freq", _("Takt")), ("temp", _("Temperatur")),
                                  ("vram", _("Speicher"))])
        grid.attach(self._ring_card(_("Grafik"), self.gpu_ring, g), 2, 0, 1, 1)

        self.pow_ring = RingGauge("power", levels="low")
        g, self.pow_kv = kv_grid([("status", _("Status")), ("watts", _("Leistungsaufnahme")), ("time", _("Restzeit")),
                                  ("health", _("Akkuzustand"))])
        grid.attach(self._ring_card(_("Energie"), self.pow_ring, g), 3, 0, 1, 1)

        # ---------------- Zeile 2: Netzwerk + Datenträger-E/A
        self.net_graph = Graph("net", series=2, fixed_max=None, min_scale=12500, colors=["net", "cpu"])
        self.net_graph.set_size_request(200, 120)
        self.net_down = styled_label(_("0 Kbit/s"), "tm-big")
        self.net_up = styled_label(_("0 Kbit/s"), "tm-big")
        self.net_info = styled_label("", "tm-dim", ellipsize=Pango.EllipsizeMode.END)
        self.net_scale = styled_label("", "tm-dim", xalign=1)
        self.net_graph.scale_changed = lambda v: self.net_scale.set_text(f"max {util.bits(v)}")
        grid.attach(self._io_card(_("Netzwerk"), self.net_graph,
                                  (_("▼ Empfangen"), self.net_down, "net"), (_("▲ Senden"), self.net_up, "cpu"),
                                  self.net_info, self.net_scale), 0, 1, 2, 1)

        self.disk_graph = Graph("disk", series=2, fixed_max=None, min_scale=1048576, colors=["disk", "mem"])
        self.disk_graph.set_size_request(200, 120)
        self.disk_read = styled_label("0 B/s", "tm-big")
        self.disk_write = styled_label("0 B/s", "tm-big")
        self.disk_info = styled_label("", "tm-dim", ellipsize=Pango.EllipsizeMode.END)
        self.disk_scale = styled_label("", "tm-dim", xalign=1)
        self.disk_graph.scale_changed = lambda v: self.disk_scale.set_text(f"max {util.rate(v)}")
        grid.attach(self._io_card(_("Datenträger-Aktivität"), self.disk_graph,
                                  (_("▼ Lesen"), self.disk_read, "disk"), (_("▲ Schreiben"), self.disk_write, "mem"),
                                  self.disk_info, self.disk_scale), 2, 1, 2, 1)

        # ---------------- Zeile 3: Festplattenbelegung + Top-Prozesse
        self.mount_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.mount_rows = {}
        storage = card(_("Festplattenbelegung"), self.mount_box)
        btns = Gtk.Box(spacing=8, halign=Gtk.Align.END)
        free_btn = Gtk.Button(label=_("🧹  Speicherplatz freigeben"))
        free_btn.get_style_context().add_class("tm-primary")
        free_btn.connect("clicked", lambda *_xx: self.app.open_cleanup())
        btn = Gtk.Button(label=_("Speicherplatz analysieren  →"))
        btn.connect("clicked", lambda *_xx: self.app.show_page("storage"))
        btns.pack_start(free_btn, False, False, 0)
        btns.pack_start(btn, False, False, 0)
        storage.pack_end(btns, False, False, 0)
        grid.attach(storage, 0, 2, 2, 1)

        top = card(_("Top-Prozesse"))
        switch = Gtk.Box(spacing=0)
        switch.get_style_context().add_class("linked")
        self.top_cpu = Gtk.RadioButton.new_with_label(None, _("CPU"))
        self.top_mem = Gtk.RadioButton.new_with_label_from_widget(self.top_cpu, _("Arbeitsspeicher"))
        self.top_io = Gtk.RadioButton.new_with_label_from_widget(self.top_cpu, _("Datenträger"))
        for rb in (self.top_cpu, self.top_mem, self.top_io):
            rb.set_mode(False)
            rb.connect("toggled", lambda b: b.get_active() and self._refresh_top())
            switch.pack_start(rb, False, False, 0)
        head = Gtk.Box()
        head.pack_end(switch, False, False, 0)
        title = top.title_label
        top.remove(title)
        head.pack_start(title, False, False, 0)
        top.pack_start(head, False, False, 0)
        self.top_rows = []
        lst = Gtk.Grid(column_spacing=10, row_spacing=7)
        for i in range(7):
            icon = Gtk.Image()
            name = styled_label("", ellipsize=Pango.EllipsizeMode.END, width_chars=18, max_width_chars=22)
            bar = UsageBar("cpu", height=8, levels=False)
            val = styled_label("", "tm-num", xalign=1, width_chars=11)
            lst.attach(icon, 0, i, 1, 1)
            lst.attach(name, 1, i, 1, 1)
            lst.attach(bar, 2, i, 1, 1)
            lst.attach(val, 3, i, 1, 1)
            self.top_rows.append((icon, name, bar, val))
        top.pack_start(lst, False, False, 0)
        grid.attach(top, 2, 2, 2, 1)

        # ---------------- Zeile 4: System
        sysbox = Gtk.Box(spacing=40)
        g1, self.sys_kv1 = kv_grid([("host", _("Rechnername")), ("os", _("Betriebssystem")),
                                    ("kernel", _("Kernel")), ("desktop", _("Desktop"))])
        g2, self.sys_kv2 = kv_grid([("cpu", _("Prozessor")), ("cores", _("Kerne/Threads")),
                                    ("uptime", _("Betriebszeit")), ("boot", _("Gestartet"))])
        g3, self.sys_kv3 = kv_grid([("threads", _("Threads")), ("handles", _("Handles")),
                                    ("conns", _("Netzwerkverbindungen")), ("users", _("Angemeldet"))])
        for g in (g1, g2, g3):
            g.set_hexpand(True)
            sysbox.pack_start(g, True, True, 0)
        grid.attach(card(_("System"), sysbox), 0, 3, 4, 1)

        self.sys_kv1["host"].set_text(self.os["host"])
        self.sys_kv1["os"].set_text(self.os["os"])
        self.sys_kv1["kernel"].set_text(f"{self.os['kernel']} ({self.os['arch']})")
        self.sys_kv1["desktop"].set_text(self.os["desktop"])
        self.sys_kv2["cpu"].set_text(self.cpu_info["model"])
        self.sys_kv2["cpu"].set_tooltip_text(self.cpu_info["model"])
        self.sys_kv2["cores"].set_text(_('{0} Kerne / {1} Threads').format(self.cpu_info['cores'], self.cpu_info['logical']))
        self.sys_kv2["boot"].set_text(util.datetime(psutil.boot_time())[:-3])
        if self.gpus:
            self.gpu_kv["name"].set_text(self.gpus[0]["name"].replace(_("Intel "), ""))
            self.gpu_kv["name"].set_tooltip_text(self.gpus[0]["name"])

        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.add(grid)
        sw.get_style_context().add_class("tm-page")
        self.widget = sw
        self._last_snap = None

    # ------------------------------------------------------------ Bausteine
    @staticmethod
    def _ring_card(title, ring, info, extra=None):
        c = card(title)
        ring.set_halign(Gtk.Align.CENTER)
        c.pack_start(ring, False, False, 0)
        c.pack_start(info, False, False, 0)
        if extra is not None:
            c.pack_start(extra, False, False, 0)
        return c

    @staticmethod
    def _io_card(title, graph, first, second, info, scale):
        c = card(title)
        vals = Gtk.Box(spacing=28)
        for caption, label, key in (first, second):
            b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            b.pack_start(styled_label(caption, "tm-dim"), False, False, 0)
            b.pack_start(label, False, False, 0)
            vals.pack_start(b, False, False, 0)
        vals.pack_end(scale, False, False, 0)
        c.pack_start(vals, False, False, 0)
        c.pack_start(graph, True, True, 0)
        c.pack_start(info, False, False, 0)
        return c

    def _mount_row(self, m):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        head = Gtk.Box(spacing=8)
        icon = Gtk.Image.new_from_icon_name(
            "drive-harddisk-system-symbolic" if m["mount"] == "/" else "drive-harddisk-symbolic",
            Gtk.IconSize.MENU)
        head.pack_start(icon, False, False, 0)
        name = styled_label("", "tm-mid")
        head.pack_start(name, False, False, 0)
        sub = styled_label("", "tm-dim")
        head.pack_start(sub, False, False, 0)
        pct = styled_label("", "tm-mid", xalign=1)
        head.pack_end(pct, False, False, 0)
        bar = UsageBar("disk", height=12)
        info = styled_label("", _("tm-dim tm-num"))
        box.pack_start(head, False, False, 0)
        box.pack_start(bar, False, False, 0)
        box.pack_start(info, False, False, 0)
        box.show_all()
        return {"box": box, "name": name, "sub": sub, "pct": pct, "bar": bar, "info": info}

    # ----------------------------------------------------------------- Update
    def update(self, s):
        self._last_snap = s
        # CPU
        self.cpu_ring.set_value(s.cpu, sub=util.ghz(s.cpu_freq))
        set_text(self.cpu_kv["speed"], util.ghz(s.cpu_freq))
        set_text(self.cpu_kv["temp"], f"{util.num(s.cpu_temp, 0)} °C" if s.cpu_temp is not None else "–")
        set_text(self.cpu_kv["load"], " / ".join(util.num(x, 2) for x in s.loadavg))
        set_text(self.cpu_kv["procs"], _('{0} · {1} Threads').format(len(s.procs), util.num(s.threads, 0)))
        for bar, v in zip(self.core_bars, s.cpu_per_core):
            bar.set_fraction(v / 100)
        # RAM
        vm, sw = s.vm, s.swap
        used = vm.total - vm.available
        self.mem_ring.set_value(vm.percent, sub=f"{util.size(used)}")
        set_text(self.mem_kv["used"], f"{util.size(used)} / {util.size(vm.total)}")
        set_text(self.mem_kv["avail"], util.size(vm.available))
        set_text(self.mem_kv["cache"], util.size(getattr(vm, "cached", 0) + getattr(vm, "buffers", 0)))
        set_text(self.mem_kv["swap"], f"{util.size(sw.used)} / {util.size(sw.total)}" if sw.total else "keiner")
        self.swap_bar.set_fraction(sw.percent / 100 if sw.total else 0)
        self.swap_bar.set_tooltip_text(f"Swap: {util.pct(sw.percent)}")
        # GPU
        if self.gpus and s.gpus:
            d = s.gpus.get(self.gpus[0]["card"], {})
            u = d.get("usage")
            self.gpu_ring.set_value(u or 0, text=util.pct(u) if u is not None else "–",
                                    sub=_("geschätzt") if d.get("estimated") else "")
            set_text(self.gpu_kv["freq"], f"{d['freq']} / {d['max_freq']} MHz" if d.get("freq") is not None else "–")
            set_text(self.gpu_kv["temp"], f"{util.num(d['temp'], 0)} °C" if d.get("temp") is not None else "–")
            set_text(self.gpu_kv["vram"], f"{util.size(d['vram_used'])} / {util.size(d['vram_total'])}"
                     if d.get("vram_total") else (_("gemeinsam mit RAM") if d.get("estimated") else "–"))
        else:
            self.gpu_ring.set_value(0, text="–", sub=_("keine Daten"))
        # Energie
        b = s.battery
        if b:
            self.pow_ring.set_value(b["percent"], sub=_("Akku"))
            st = STATUS_DE.get(b["status"], b["status"])
            if b["ac"] and b["status"] == _("Discharging"):
                st = _("Entlädt")
            set_text(self.pow_kv["status"], st)
            set_text(self.pow_kv["watts"], f"{util.num(b['watts'], 1)} W" if b["watts"] else
                     (_("0 W (Netzteil)") if b["ac"] else "–"))
            if b["secs"]:
                h, m = divmod(int(b["secs"]) // 60, 60)
                set_text(self.pow_kv["time"], _('{0} h {1:02d} min').format(h, m))
            else:
                set_text(self.pow_kv["time"], "–")
            set_text(self.pow_kv["health"], util.pct(b["health"]) if b["health"] else "–")
        else:
            self.pow_ring.set_value(100, text=_("AC"), sub=_("Netzbetrieb"))
            for k in self.pow_kv:
                set_text(self.pow_kv[k], "–")
            set_text(self.pow_kv["status"], _("Kein Akku"))
        # Netzwerk (Summe aller Adapter)
        down = sum(d["recv"] for d in s.net.values())
        up = sum(d["sent"] for d in s.net.values())
        self.net_graph.push(down, up)
        set_text(self.net_down, util.bits(down))
        set_text(self.net_up, util.bits(up))
        active = [n for n, d in s.net.items() if d["recv"] or d["sent"]]
        set_text(self.net_info, _("Aktiv: ") + (", ".join(active) if active else _("keine Übertragung")))
        # Datenträger
        rd = sum(d["read"] for d in s.disks.values())
        wr = sum(d["write"] for d in s.disks.values())
        self.disk_graph.push(rd, wr)
        set_text(self.disk_read, util.rate(rd))
        set_text(self.disk_write, util.rate(wr))
        set_text(self.disk_info, "  ·  ".join(_('{0}: {1} aktiv').format(n, util.pct(d['active'])) for n, d in s.disks.items()))
        # Belegung
        self._update_mounts(s.mounts)
        # Top-Prozesse
        self._refresh_top()
        # System
        set_text(self.sys_kv2["uptime"], util.uptime_text(s.uptime))
        set_text(self.sys_kv3["threads"], util.num(s.threads, 0))
        set_text(self.sys_kv3["handles"], util.num(s.handles, 0))
        if time.monotonic() - self._conn_t > 5:
            self._conn_t = time.monotonic()
            try:
                conns = psutil.net_connections("inet")
                est = sum(1 for c in conns if c.status == _("ESTABLISHED"))
                self._conn_text = _('{0} ({1} verbunden)').format(len(conns), est)
            except (psutil.Error, OSError):
                self._conn_text = "–"
            users = sorted({u.name for u in psutil.users()})
            set_text(self.sys_kv3["users"], ", ".join(users) or "–")
        set_text(self.sys_kv3["conns"], self._conn_text)

    def _update_mounts(self, mounts):
        keys = [m["mount"] for m in mounts]
        for k in list(self.mount_rows):
            if k not in keys:
                self.mount_box.remove(self.mount_rows.pop(k)["box"])
        for m in mounts:
            row = self.mount_rows.get(m["mount"])
            if row is None:
                row = self.mount_rows[m["mount"]] = self._mount_row(m)
                self.mount_box.pack_start(row["box"], False, False, 0)
            label = _("System (/)") if m["mount"] == "/" else m["mount"]
            set_text(row["name"], label)
            set_text(row["sub"], f"{m['device']} · {m['fstype']}")
            set_text(row["pct"], util.pct(m["percent"]))
            row["bar"].set_fraction(m["percent"] / 100)
            set_text(row["info"], _('{0} belegt  ·  {1} frei  ·  {2} gesamt').format(util.size(m['used']), util.size(m['free']), util.size(m['total'])))

    def _refresh_top(self):
        s = self._last_snap
        if s is None:
            return
        procs = [p for p in s.procs.values() if not (p.pid == 2 or p.ppid == 2)]
        if self.top_cpu.get_active():
            key, fmt, color = (lambda p: p.cpu), (lambda v: util.pct(v, 1)), "cpu"
            scale = 100.0
        elif self.top_mem.get_active():
            key, fmt, color = (lambda p: p.mem), util.size, "mem"
            scale = None
        else:
            key, fmt, color = (lambda p: (p.read_rate or 0) + (p.write_rate or 0)), util.rate, "disk"
            scale = None
        top = sorted(procs, key=key, reverse=True)[:len(self.top_rows)]
        mx = scale or max([key(p) for p in top] + [1])
        for (icon, name, bar, val), p in zip(self.top_rows, top + [None] * len(self.top_rows)):
            if p is None:
                set_text(name, "")
                set_text(val, "")
                bar.set_fraction(0)
                continue
            pix = icons.for_process(p.name, p.exe)
            if icon.get_pixbuf() is not pix:
                icon.set_from_pixbuf(pix)
            set_text(name, p.name)
            name.set_tooltip_text(_('PID {0} · {1}\n{2}').format(p.pid, p.user, p.cmdline or p.name))
            bar.color = color
            bar.set_fraction(key(p) / mx if mx else 0)
            bar.queue_draw()
            set_text(val, fmt(key(p)))
