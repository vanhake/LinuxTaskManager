"""Seite „CPU-Benchmark“: Leistungstest, Belastungstest und Ergebnisverlauf."""

import os
import time

from gi.repository import GLib, Gtk, Pango

from .. import actions, benchmark as bm, sysinfo, theme, util
from ..widgets import Graph, UsageBar, card, set_text, styled_label
from . import Tab, scrolled


def _max_mhz():
    v = util.read_file("/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq")
    return int(v) / 1000 if v and v.isdigit() else 4000.0


class BenchmarkTab(Tab):
    title = "CPU-Benchmark"

    def __init__(self, app):
        super().__init__(app)
        self.cpu = sysinfo.cpu_info()
        self.threads = self.cpu["logical"]
        self.run = None
        self.stress = None
        self.stats = None
        self.history = bm.load_history()
        self.max_mhz = _max_mhz()

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, margin=18)

        # ------------------------------------------------------ Kopf
        head = Gtk.Box(spacing=10)
        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        titles.pack_start(styled_label("CPU-Benchmark", "tm-h1"), False, False, 0)
        sub = styled_label(f"{self.cpu['model']}  ·  {self.cpu['cores']} Kerne / {self.threads} Threads",
                           "tm-dim", ellipsize=Pango.EllipsizeMode.END)
        sub.set_tooltip_text(sub.get_text())
        titles.pack_start(sub, False, False, 0)
        head.pack_start(titles, True, True, 0)
        self.stop_btn = Gtk.Button(label="■  Stopp")
        self.stop_btn.get_style_context().add_class("tm-danger")
        self.stop_btn.connect("clicked", lambda *_: self.stop())
        self.stress_btn = Gtk.Button(label="🔥  Belastungstest")
        self.stress_btn.set_tooltip_text("Volllast auf allen Kernen bis zum Stopp – prüft Kühlung und Stabilität")
        self.stress_btn.connect("clicked", lambda *_: self.start_stress())
        self.start_btn = Gtk.Button(label="▶  Benchmark starten")
        self.start_btn.get_style_context().add_class("tm-primary")
        self.start_btn.connect("clicked", lambda *_: self.start())
        self.mode = Gtk.ComboBoxText()
        for name, secs in bm.MODES:
            self.mode.append(str(secs), f"{name} (~{int(secs * 10 + 4)} s)")
        self.mode.set_active_id("3.0")
        for w in (self.stop_btn, self.stress_btn, self.start_btn, self.mode):
            w.set_valign(Gtk.Align.CENTER)
            head.pack_end(w, False, False, 0)
        outer.pack_start(head, False, False, 0)

        # ------------------------------------------------------ Punktzahlen
        scores = Gtk.Grid(column_spacing=14, column_homogeneous=True)
        self.single = self._score_card("Single-Core", "cpu")
        self.multi = self._score_card(f"Multi-Core · {self.threads} Threads", "mem")
        scores.attach(self.single["card"], 0, 0, 1, 1)
        scores.attach(self.multi["card"], 1, 0, 1, 1)
        outer.pack_start(scores, False, False, 0)

        # ------------------------------------------------------ Live
        live = card("Live")
        self.phase = styled_label("Bereit. Schließe für vergleichbare Werte andere rechenintensive Programme.",
                                  "tm-mid", ellipsize=Pango.EllipsizeMode.END)
        live.pack_start(self.phase, False, False, 0)
        self.progress = Gtk.ProgressBar()
        live.pack_start(self.progress, False, False, 0)
        graphs = Gtk.Grid(column_spacing=14, column_homogeneous=True)
        self.g_cpu = Graph("cpu")
        self.g_temp = Graph("power", fixed_max=100.0)
        self.g_freq = Graph("gpu", fixed_max=self.max_mhz)
        self.l_cpu = styled_label("", "tm-mid", xalign=1)
        self.l_temp = styled_label("", "tm-mid", xalign=1)
        self.l_freq = styled_label("", "tm-mid", xalign=1)
        for i, (cap, g, lbl) in enumerate((("CPU-Auslastung", self.g_cpu, self.l_cpu),
                                           ("Temperatur", self.g_temp, self.l_temp),
                                           ("Takt", self.g_freq, self.l_freq))):
            b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            hb = Gtk.Box()
            hb.pack_start(styled_label(cap, "tm-dim"), False, False, 0)
            hb.pack_end(lbl, False, False, 0)
            b.pack_start(hb, False, False, 0)
            g.set_size_request(150, 100)
            b.pack_start(g, True, True, 0)
            graphs.attach(b, i, 0, 1, 1)
        live.pack_start(graphs, False, False, 0)
        stats = Gtk.Box(spacing=36)
        self.st = {}
        for key, cap in (("time", "Laufzeit"), ("tmax", "Max. Temperatur"), ("fload", "Takt unter Last (Ø / min)"),
                         ("throttle", "Drosselung"), ("power", "Stromversorgung")):
            b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            b.pack_start(styled_label(cap, "tm-dim"), False, False, 0)
            v = styled_label("–", "tm-mid")
            b.pack_start(v, False, False, 0)
            stats.pack_start(b, False, False, 0)
            self.st[key] = v
        live.pack_start(stats, False, False, 0)
        outer.pack_start(live, False, False, 0)

        # ------------------------------------------------------ Einzeltests
        tests = card("Einzeltests")
        grid = Gtk.Grid(column_spacing=14, row_spacing=10)
        grid.attach(styled_label("Single-Core", "tm-card-title"), 2, 0, 2, 1)
        grid.attach(styled_label("Multi-Core", "tm-card-title"), 4, 0, 2, 1)
        self.rows = {}
        for i, (key, name, desc, ref) in enumerate(bm.TESTS, start=1):
            nb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            nb.pack_start(styled_label(name, "tm-mid"), False, False, 0)
            nb.pack_start(styled_label(desc, "tm-dim", ellipsize=Pango.EllipsizeMode.END, max_width_chars=34),
                          False, False, 0)
            nb.set_size_request(240, -1)
            nb.set_tooltip_text(desc)
            grid.attach(nb, 0, i, 2, 1)
            sb, sv = UsageBar("cpu", height=10, levels=False), styled_label("–", "tm-num", xalign=1, width_chars=7)
            mb, mv = UsageBar("mem", height=10, levels=False), styled_label("–", "tm-num", xalign=1, width_chars=7)
            for col, w in ((2, sb), (3, sv), (4, mb), (5, mv)):
                w.set_valign(Gtk.Align.CENTER)
                grid.attach(w, col, i, 1, 1)
            self.rows[key] = {"single": (sb, sv), "multi": (mb, mv)}
        tests.pack_start(grid, False, False, 0)
        tests.pack_start(styled_label("Punkte: 1000 = ein Kern eines Intel Core i5-4300M (Referenz). "
                                      "Gesamtwert = geometrisches Mittel der Einzeltests.", "tm-dim"),
                         False, False, 0)
        outer.pack_start(tests, False, False, 0)

        # ------------------------------------------------------ Verlauf
        hist = card("Ergebnisverlauf")
        self.hstore = Gtk.ListStore(int, str, str, float, float, str, str, str, str)
        hv = self.hview = Gtk.TreeView(model=self.hstore)
        for title, col, xalign in (("Datum", 1, 0), ("Modus", 2, 0), ("Single", 3, 1), ("Multi", 4, 1),
                                   ("Skalierung", 5, 1), ("Max. Temp.", 6, 1), ("Ø Takt (Last)", 7, 1),
                                   ("Strom", 8, 0)):
            cell = Gtk.CellRendererText(xalign=xalign)
            c = Gtk.TreeViewColumn(title, cell, text=col)
            if col in (3, 4):
                c.set_cell_data_func(cell, lambda co, ce, m, it, cid: ce.set_property(
                    "text", util.num(m.get_value(it, cid), 0)), col)
            c.set_sort_column_id(col if col not in (1,) else 0)
            c.set_alignment(xalign)
            c.set_resizable(True)
            c.set_expand(col == 1)
            hv.append_column(c)
        hsw = scrolled(hv)
        hsw.set_margin_start(0)
        hsw.set_margin_end(0)
        hsw.set_size_request(-1, 200)
        hist.pack_start(hsw, True, True, 0)
        hb = Gtk.Box(spacing=8)
        self.best_label = styled_label("", "tm-dim")
        hb.pack_start(self.best_label, False, False, 0)
        del_btn = Gtk.Button(label="Ausgewähltes Ergebnis löschen")
        del_btn.connect("clicked", lambda *_: self._delete_selected())
        hb.pack_end(del_btn, False, False, 0)
        hist.pack_start(hb, False, False, 0)
        outer.pack_start(hist, False, False, 0)

        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.add(outer)
        self.widget = sw
        self._fill_history()
        self._show_last()
        self._set_running(False)

    # ------------------------------------------------------------ Bausteine
    def _score_card(self, title, color):
        c = card(title)
        row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        big = Gtk.Label(xalign=0)
        row.pack_start(big, False, False, 0)
        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        sub1 = styled_label("", "tm-mid", ellipsize=Pango.EllipsizeMode.END)
        sub2 = styled_label("", "tm-dim", ellipsize=Pango.EllipsizeMode.END)
        info.pack_start(sub1, False, False, 0)
        info.pack_start(sub2, False, False, 0)
        row.pack_start(info, True, True, 0)
        c.pack_start(row, False, False, 0)
        bar = UsageBar(color, height=12, levels=False)
        c.pack_start(bar, False, False, 0)
        d = {"card": c, "big": big, "sub1": sub1, "sub2": sub2, "bar": bar, "color": color, "value": 0, "anim": None}
        self._set_big(d, None)
        return d

    def _set_big(self, d, value):
        r, g, b = theme.rgb(d["color"])
        col = f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"
        text = "–" if value is None else util.num(value, 0)
        d["big"].set_markup(f"<span size='38000' weight='heavy' foreground='{col}'>{text}</span>"
                            f"<span size='large'>  Punkte</span>")

    def _animate(self, d, target):
        if d["anim"]:
            GLib.source_remove(d["anim"])
        start, t0 = d["value"] if d["value"] else 0, time.monotonic()

        def tick():
            f = min(1.0, (time.monotonic() - t0) / 0.9)
            f = 1 - (1 - f) ** 3
            self._set_big(d, start + (target - start) * f)
            if f >= 1:
                d["anim"] = None
                return False
            return True
        d["value"] = target
        d["anim"] = GLib.timeout_add(16, tick)

    # ------------------------------------------------------------ Steuerung
    def _set_running(self, running):
        self.start_btn.set_sensitive(not running)
        self.stress_btn.set_sensitive(not running)
        self.mode.set_sensitive(not running)
        self.stop_btn.set_sensitive(running)

    @property
    def running(self):
        return self.run is not None or self.stress is not None

    def _new_stats(self):
        self.stats = {"t0": time.monotonic(), "temps": [], "load_freqs": [], "ac": None}

    def start(self):
        if self.running:
            return
        self._new_stats()
        for key, r in self.rows.items():
            for mode in ("single", "multi"):
                bar, lbl = r[mode]
                bar.set_fraction(0)
                set_text(lbl, "…")
        for d in (self.single, self.multi):
            d["value"] = 0
            self._set_big(d, None)
            set_text(d["sub1"], "läuft…")
            set_text(d["sub2"], "")
            d["bar"].set_fraction(0)
        duration = float(self.mode.get_active_id())
        self._mode_name = next(n for n, s in bm.MODES if s == duration)
        idle = GLib.idle_add
        self.run = bm.BenchmarkRun(
            duration,
            on_progress=lambda text, frac, mode, key: idle(self._on_progress, text, frac),
            on_score=lambda mode, key, sc: idle(self._on_score, mode, key, sc),
            on_done=lambda res, err: idle(self._on_done, res, err),
            threads=self.threads)
        self._set_running(True)
        self.app.recorder.event("info", "bench", f"CPU-Benchmark gestartet ({self._mode_name})")
        self.run.start()

    def start_stress(self):
        if self.running:
            return
        if not actions.confirm(self.app.window, "Belastungstest starten?",
                               f"Alle {self.threads} Threads werden bis zum Stopp voll ausgelastet. Der Rechner "
                               "wird warm, Lüfter drehen hoch. Beobachte Temperatur und Takt; bei Problemen "
                               "„Stopp“ drücken.", "Starten"):
            return
        self._new_stats()
        self.stress = bm.StressRun(lambda err: GLib.idle_add(self._on_stress_done, err), threads=self.threads)
        self._set_running(True)
        self.progress.set_fraction(0)
        set_text(self.phase, f"🔥 Belastungstest läuft auf {self.threads} Threads – „Stopp“ zum Beenden")
        self.app.recorder.event("warn", "stress", "Belastungstest gestartet")
        self.stress.start()
        GLib.timeout_add(120, self._pulse)

    def _pulse(self):
        if self.stress is None:
            return False
        self.progress.pulse()
        return True

    def stop(self):
        if self.run:
            self.run.cancel()
            set_text(self.phase, "Wird abgebrochen…")
        if self.stress:
            self.stress.cancel()
            set_text(self.phase, "Belastungstest wird beendet…")

    def retheme(self):
        for d in (self.single, self.multi):
            self._set_big(d, d["value"] or None)

    def shutdown(self):
        for r in (self.run, self.stress):
            if r is not None:
                r.cancel()

    # ------------------------------------------------------------ Rückmeldungen
    def _on_progress(self, text, frac):
        set_text(self.phase, text)
        self.progress.set_fraction(frac)
        return False

    def _on_score(self, mode, key, sc):
        bar, lbl = self.rows[key][mode]
        scale = 1500.0 if mode == "single" else 1100.0 * self.threads
        bar.set_fraction(sc / scale)
        set_text(lbl, util.num(sc, 0))
        return False

    def _on_done(self, res, err):
        self.run = None
        self._set_running(False)
        if err:
            set_text(self.phase, f"Benchmark {err}.")
            self.progress.set_fraction(0)
            self._show_last()
            self.app.recorder.event("info", "bench", f"CPU-Benchmark {err}")
            return False
        st = self._summary()
        entry = {
            "ts": time.time(), "mode": self._mode_name, "duration": res["duration"], "threads": res["threads"],
            "single_total": res["single_total"], "multi_total": res["multi_total"],
            "single": res["single"], "multi": res["multi"], "cpu": self.cpu["model"],
            "kernel": os.uname().release, **st,
        }
        self.history.append(entry)
        try:
            bm.save_history(self.history)
        except OSError:
            pass
        self._fill_history()
        self._show_result(entry)
        set_text(self.phase, f"Fertig – Single-Core {util.num(entry['single_total'], 0)} · "
                             f"Multi-Core {util.num(entry['multi_total'], 0)} Punkte")
        self.app.recorder.event("info", "bench", f"CPU-Benchmark: Single {entry['single_total']:.0f}, "
                                                 f"Multi {entry['multi_total']:.0f} Punkte")
        return False

    def _on_stress_done(self, err):
        dur = time.monotonic() - self.stats["t0"] if self.stats else 0
        self.stress = None
        self._set_running(False)
        self.progress.set_fraction(0)
        st = self._summary()
        msg = f"Belastungstest beendet nach {util.uptime_text(dur) if dur >= 60 else f'{int(dur)} s'}"
        if st.get("max_temp"):
            msg += f" · max. {st['max_temp']:.0f} °C"
        if err:
            msg += f" (Fehler: {err})"
        set_text(self.phase, msg)
        self.app.recorder.event("info", "stress", msg)
        return False

    # ------------------------------------------------------------ Live-Daten
    def feed(self, s):
        """Bei jedem Snapshot (auch wenn nicht sichtbar)."""
        self.g_cpu.push(s.cpu)
        self.g_temp.push(s.cpu_temp or 0)
        self.g_freq.push(s.cpu_freq or 0)
        set_text(self.l_cpu, util.pct(s.cpu))
        set_text(self.l_temp, f"{util.num(s.cpu_temp, 0)} °C" if s.cpu_temp is not None else "–")
        set_text(self.l_freq, util.ghz(s.cpu_freq))
        b = s.battery
        set_text(self.st["power"], "–" if not b else ("Netzteil" if b["ac"] else f"Akku ({b['percent']} %)"))
        if not self.running or self.stats is None:
            return
        st = self.stats
        if s.cpu_temp is not None:
            st["temps"].append(s.cpu_temp)
        if s.cpu >= 80 and s.cpu_freq:
            st["load_freqs"].append((time.monotonic(), s.cpu_freq, s.cpu_temp))
        if b:
            st["ac"] = b["ac"]
        set_text(self.st["time"], f"{int(time.monotonic() - st['t0'])} s")
        self._show_stats(self._summary())

    def _summary(self):
        st = self.stats or {"temps": [], "load_freqs": [], "ac": None}
        res = {"max_temp": max(st["temps"]) if st["temps"] else None, "avg_freq": None, "min_freq": None,
               "throttle": "–", "ac": st.get("ac")}
        lf = st["load_freqs"]
        if lf:
            freqs = [f for _, f, _ in lf]
            res["avg_freq"] = sum(freqs) / len(freqs)
            res["min_freq"] = min(freqs)
            base = self.cpu["base_mhz"] or self.max_mhz
            early = [f for t, f, _ in lf if t - lf[0][0] <= 5]
            late = [f for t, f, _ in lf if lf[-1][0] - t <= 5]
            hot = res["max_temp"] is not None and res["max_temp"] >= 85
            if res["avg_freq"] < base * 0.9:
                res["throttle"] = "Takt unter Basistakt"
            elif len(lf) >= 10 and sum(late) / len(late) < sum(early) / len(early) * 0.85 and hot:
                res["throttle"] = "Thermisch gedrosselt"
            else:
                res["throttle"] = "keine erkannt"
        return res

    def _show_stats(self, st):
        set_text(self.st["tmax"], f"{util.num(st['max_temp'], 0)} °C" if st.get("max_temp") is not None else "–")
        if st.get("avg_freq"):
            set_text(self.st["fload"], f"{util.ghz(st['avg_freq'])} / {util.ghz(st['min_freq'])}")
        else:
            set_text(self.st["fload"], "–")
        set_text(self.st["throttle"], st.get("throttle") or "–")

    # ------------------------------------------------------------ Ergebnisse
    def _show_last(self):
        if self.history:
            self._show_result(self.history[-1], animate=False)

    def _show_result(self, e, animate=True):
        best_s = max((h["single_total"] for h in self.history), default=e["single_total"])
        best_m = max((h["multi_total"] for h in self.history), default=e["multi_total"])
        for d, key, best in ((self.single, "single_total", best_s), (self.multi, "multi_total", best_m)):
            v = e[key]
            if animate:
                self._animate(d, v)
            else:
                d["value"] = v
                self._set_big(d, v)
            d["bar"].set_fraction(v / max(best, 1) * 0.95)
            pct = v / max(best, 1) * 100
            set_text(d["sub2"], f"{util.num(pct, 0)} % des Bestwerts ({util.num(best, 0)})")
        set_text(self.single["sub1"], f"{e['mode']} · {util.datetime(e['ts'])[:-3]}")
        scaling = e["multi_total"] / max(1, e["single_total"])
        set_text(self.multi["sub1"], f"Skalierung ×{util.num(scaling, 2)} gegenüber einem Kern")
        set_text(self.multi["sub2"], f"{self.cpu['cores']} Kerne / {e['threads']} Threads · "
                                     f"{self.multi['sub2'].get_text()}")
        for key, r in self.rows.items():
            for mode, scale in (("single", 1500.0), ("multi", 1100.0 * e["threads"])):
                bar, lbl = r[mode]
                v = e[mode].get(key)
                bar.set_fraction((v or 0) / scale)
                set_text(lbl, util.num(v, 0) if v else "–")
        self._show_stats(e)
        set_text(self.st["time"], f"{util.num(e['duration'] * 10, 0)} s Messzeit")

    def _fill_history(self):
        self.hstore.clear()
        for i, e in enumerate(self.history):
            scaling = e["multi_total"] / max(1, e["single_total"])
            self.hstore.append([
                i, util.datetime(e["ts"])[:-3], e["mode"], e["single_total"], e["multi_total"],
                f"×{util.num(scaling, 2)}",
                f"{util.num(e['max_temp'], 0)} °C" if e.get("max_temp") is not None else "–",
                util.ghz(e["avg_freq"]) if e.get("avg_freq") else "–",
                "–" if e.get("ac") is None else ("Netzteil" if e["ac"] else "Akku"),
            ])
        self.hstore.set_sort_column_id(0, Gtk.SortType.DESCENDING)
        if self.history:
            bs = max(self.history, key=lambda h: h["single_total"])
            bmx = max(self.history, key=lambda h: h["multi_total"])
            set_text(self.best_label, f"{len(self.history)} Läufe  ·  Bestwerte: Single "
                                      f"{util.num(bs['single_total'], 0)}, Multi {util.num(bmx['multi_total'], 0)}")
        else:
            set_text(self.best_label, "Noch keine Ergebnisse – starte den ersten Benchmark.")

    def _delete_selected(self):
        model, it = self.hview.get_selection().get_selected()
        if it is None:
            return
        idx = model.get_value(it, 0)
        if not actions.confirm(self.app.window, "Ergebnis löschen?",
                               f"Lauf vom {model.get_value(it, 1)} wird aus dem Verlauf entfernt.", "Löschen"):
            return
        del self.history[idx]
        try:
            bm.save_history(self.history)
        except OSError:
            pass
        self._fill_history()
        self._show_last()
