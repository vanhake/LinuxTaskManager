"""Seite „Systemrekorder“: aufgezeichnete Systemdaten zurückspulen und abspielen."""

from ..i18n import _

import os
import subprocess
import sys
import time

import cairo
from gi.repository import GdkPixbuf, GLib, Gdk, Gtk, Pango

from .. import actions, icons, theme, util
from ..recorder import RETENTIONS, Reader
from ..widgets import draw_text, heat_cell_func, nice_ceiling, rounded_rect, set_text, styled_label
from . import Tab, scrolled

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
AUTOSTART = os.path.join(GLib.get_user_config_dir(), "autostart", "linux-taskmanager-recorder.desktop")

RANGES = [(_("5 min"), 300), (_("15 min"), 900), ("1 h", 3600), ("6 h", 21600), ("24 h", 86400), (_("Alles"), None)]
SPEEDS = [("1×", 1), ("10×", 10), ("60×", 60), ("300×", 300)]
TICKS = [10, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200, 86400]
WEEKDAYS = [_("Mo"), _("Di"), _("Mi"), _("Do"), _("Fr"), _("Sa"), _("So")]

# (Schlüssel, Titel, Farbe, feste Skala, Formatierer)
LANES = [
    ("cpu", _("CPU"), "cpu", 100.0, lambda v: util.pct(v)),
    ("mem", _("Arbeitsspeicher"), "mem", 100.0, lambda v: util.pct(v)),
    ("disk", _("Datenträger"), "disk", None, util.rate),
    ("net", _("Netzwerk"), "net", None, util.bits),
    ("gpu", _("GPU"), "gpu", 100.0, lambda v: util.pct(v)),
    ("temp", _("Temperatur"), "power", 100.0, lambda v: f"{util.num(v, 0)} °C"),
]
LEVEL_COLOR = {"crit": "crit", "warn": "warn", "info": "accent"}


def fmt_time(ts, seconds=True):
    lt = time.localtime(ts)
    fmt = util.date_fmt("day") + " %H:%M" + (":%S" if seconds else "")
    return f"{WEEKDAYS[lt.tm_wday]} {time.strftime(fmt, lt)}"


def ago(ts):
    d = int(time.time() - ts)
    if d < 5:
        return "jetzt"
    if d < 60:
        return _('vor {0} s').format(d)
    if d < 3600:
        return _('vor {0} min').format(d // 60)
    if d < 86400:
        return _('vor {0} h {1:02d} min').format(d // 3600, d % 3600 // 60)
    return _('vor {0} T {1} h').format(d // 86400, d % 86400 // 3600)


class Timeline(Gtk.DrawingArea):
    """Mehrspurige Zeitleiste mit Ereignismarken und ziehbarem Abspielkopf."""

    TOP = 22
    AXIS = 24
    GAP = 6

    def __init__(self):
        super().__init__()
        self.t0, self.t1 = time.time() - 900, time.time()
        self.data = {}
        self.n = 1
        self.events = []
        self.playhead = time.time()
        self.hover_x = None
        self.on_seek = None
        self.on_zoom = None
        self._drag = False
        self.set_size_request(400, 360)
        self.set_has_tooltip(True)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
                        | Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.SCROLL_MASK
                        | Gdk.EventMask.SMOOTH_SCROLL_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self.connect("draw", self._draw)
        self.connect("button-press-event", self._press)
        self.connect("button-release-event", self._release)
        self.connect("motion-notify-event", self._motion)
        self.connect("leave-notify-event", self._leave)
        self.connect("scroll-event", self._scroll)
        self.connect("query-tooltip", self._tooltip)

    def lanes(self):
        return [l for l in LANES if l[0] != "gpu" or any(v for v in self.data.get("gpu", []) if v)]

    # ------------------------------------------------------------ Geometrie
    def x_of(self, ts):
        w = self.get_allocated_width()
        return (ts - self.t0) / max(1e-6, self.t1 - self.t0) * w

    def ts_of(self, x):
        w = max(1, self.get_allocated_width())
        return self.t0 + (self.t1 - self.t0) * max(0.0, min(1.0, x / w))

    def _lane_rects(self):
        h = self.get_allocated_height()
        lanes = self.lanes()
        avail = h - self.TOP - self.AXIS - self.GAP * (len(lanes) - 1)
        lh = avail / max(1, len(lanes))
        return [(lane, self.TOP + i * (lh + self.GAP), lh) for i, lane in enumerate(lanes)]

    # ---------------------------------------------------------------- Zeichnen
    def _draw(self, widget, cr):
        w = widget.get_allocated_width()
        h = widget.get_allocated_height()
        dark = theme.is_dark()
        tc, dc = theme.rgb("text"), theme.rgb("dim")
        n = self.n
        bw = w / n

        for (key, title, color, fixed, fmt), y, lh in self._lane_rects():
            r, g, b = theme.rgb(color)
            rounded_rect(cr, 0, y, w, lh, 8)
            cr.set_source_rgb(*theme.rgb("surface2"))
            cr.fill()
            vals = list(self.data.get(key) or [None] * n)
            # kurze Lücken (< 4 s, z. B. zwischen zwei Messungen) mit dem letzten Wert füllen
            hold = max(1, int(4.0 / max(1e-6, (self.t1 - self.t0) / n)))
            last, gap = None, 0
            for i, v in enumerate(vals):
                if v is None:
                    gap += 1
                    if last is not None and gap <= hold:
                        vals[i] = last
                else:
                    last, gap = v, 0
            peak = max([v for v in vals if v is not None] or [0])
            scale = fixed or nice_ceiling(max(peak, 1.0 if key != "net" else 12500))
            cr.save()
            rounded_rect(cr, 0, y, w, lh, 8)
            cr.clip()
            grad = cairo.LinearGradient(0, y, 0, y + lh)
            grad.add_color_stop_rgba(0, r, g, b, 0.55 if dark else 0.45)
            grad.add_color_stop_rgba(1, r, g, b, 0.08)
            cr.set_source(grad)
            for i, v in enumerate(vals):
                if v is None:
                    continue
                bh = min(1.0, v / scale) * (lh - 4)
                cr.rectangle(i * bw, y + lh - bh, bw + 0.6, bh)
            cr.fill()
            # Kontur mit Glow
            for width, alpha in (((4, 0.18), (1.4, 1.0)) if dark else ((1.4, 1.0),)):
                started = False
                for i, v in enumerate(vals):
                    if v is None:
                        started = False
                        continue
                    yy = y + lh - min(1.0, v / scale) * (lh - 4)
                    x = i * bw + bw / 2
                    if started:
                        cr.line_to(x, yy)
                    else:
                        cr.move_to(x, yy)
                        started = True
                cr.set_source_rgba(r, g, b, alpha)
                cr.set_line_width(width)
                cr.stroke()
            cr.restore()
            draw_text(cr, widget, title.upper(), 10, y + 5, size=9, bold=True, color=(r, g, b, 0.95))
            draw_text(cr, widget, _('Spitze {0}').format(fmt(peak)) if peak else _("keine Daten"), w - 10, y + 5,
                      size=9, color=(*dc, 1), align=1.0)

        lanes_bottom = h - self.AXIS
        # Zeitachse
        span = self.t1 - self.t0
        step = next((t for t in TICKS if span / t <= 9), TICKS[-1])
        first = (int(self.t0 // step) + 1) * step
        if step < 86400:
            # auf lokale Zeit ausrichten
            off = time.localtime(first).tm_gmtoff
            first = ((int(self.t0 + off) // step) + 1) * step - off
        fmt = "%H:%M:%S" if step < 60 else ("%H:%M" if span <= 86400 else util.date_fmt("day") + " %H:%M")
        cr.set_line_width(1)
        t = first
        while t < self.t1:
            x = round(self.x_of(t)) + 0.5
            cr.set_source_rgba(*dc, 0.18)
            cr.move_to(x, self.TOP)
            cr.line_to(x, lanes_bottom)
            cr.stroke()
            draw_text(cr, widget, time.strftime(fmt, time.localtime(t)), x, lanes_bottom + 5, size=9,
                      color=(*dc, 1), align=0.5)
            t += step

        # Ereignisse
        for ts, level, kind, text in self.events:
            if not (self.t0 <= ts <= self.t1):
                continue
            x = self.x_of(ts)
            r, g, b = theme.rgb(LEVEL_COLOR.get(level, "accent"))
            cr.set_source_rgba(r, g, b, 0.35)
            cr.set_dash([2, 3])
            cr.move_to(round(x) + 0.5, self.TOP)
            cr.line_to(round(x) + 0.5, lanes_bottom)
            cr.stroke()
            cr.set_dash([])
            cr.set_source_rgba(r, g, b, 1)
            cr.move_to(x, 6)
            cr.line_to(x + 5, 12)
            cr.line_to(x, 18)
            cr.line_to(x - 5, 12)
            cr.close_path()
            cr.fill()

        # Hover
        if self.hover_x is not None and not self._drag:
            cr.set_source_rgba(*tc, 0.35)
            cr.set_dash([3, 3])
            cr.move_to(round(self.hover_x) + 0.5, self.TOP)
            cr.line_to(round(self.hover_x) + 0.5, lanes_bottom)
            cr.stroke()
            cr.set_dash([])

        # Abspielkopf
        if self.t0 <= self.playhead <= self.t1 + 1:
            x = min(w - 1, self.x_of(self.playhead))
            r, g, b = theme.rgb("accent")
            if dark:
                cr.set_source_rgba(r, g, b, 0.25)
                cr.set_line_width(6)
                cr.move_to(x, self.TOP - 2)
                cr.line_to(x, lanes_bottom)
                cr.stroke()
            cr.set_source_rgba(r, g, b, 1)
            cr.set_line_width(2)
            cr.move_to(x, self.TOP - 2)
            cr.line_to(x, lanes_bottom)
            cr.stroke()
            label = time.strftime("%H:%M:%S", time.localtime(self.playhead))
            lw = 64
            bx = max(0, min(w - lw, x - lw / 2))
            rounded_rect(cr, bx, 0, lw, 18, 9)
            cr.set_source_rgba(r, g, b, 1)
            cr.fill()
            bg = theme.rgb("bg")
            draw_text(cr, widget, label, bx + lw / 2, 9, size=9.5, bold=True, color=(*bg, 1),
                      align=0.5, valign=0.5)

    # ------------------------------------------------------------ Interaktion
    def _press(self, widget, event):
        if event.button == 1:
            self._drag = True
            if self.on_seek:
                self.on_seek(self.ts_of(event.x))
        return True

    def _release(self, widget, event):
        self._drag = False
        self.queue_draw()
        return True

    def _motion(self, widget, event):
        self.hover_x = event.x
        if self._drag and self.on_seek:
            self.on_seek(self.ts_of(event.x))
        else:
            self.queue_draw()
        return False

    def _leave(self, widget, event):
        self.hover_x = None
        self.queue_draw()

    def _scroll(self, widget, event):
        ok, dx, dy = event.get_scroll_deltas()
        if not ok:
            dy = -1 if event.direction == Gdk.ScrollDirection.UP else (
                1 if event.direction == Gdk.ScrollDirection.DOWN else 0)
        if dy == 0 or not self.on_zoom:
            return True
        span = self.t1 - self.t0
        if event.state & Gdk.ModifierType.SHIFT_MASK:
            shift = span * 0.15 * (1 if dy > 0 else -1)
            self.on_zoom(self.t0 + shift, self.t1 + shift)
        else:
            factor = 1.25 if dy > 0 else 0.8
            pivot = self.ts_of(event.x)
            new_span = max(60.0, min(span * factor, 8 * 86400))
            frac = (pivot - self.t0) / span
            self.on_zoom(pivot - new_span * frac, pivot + new_span * (1 - frac))
        return True

    def _tooltip(self, widget, x, y, keyboard, tooltip):
        ts = self.ts_of(x)
        idx = int(x / max(1, self.get_allocated_width()) * self.n)
        lines = [fmt_time(ts)]
        for key, title, color, fixed, fmt in self.lanes():
            vals = self.data.get(key) or []
            v = vals[idx] if 0 <= idx < len(vals) else None
            lines.append(f"{title}: {fmt(v) if v is not None else '–'}")
        tol = (self.t1 - self.t0) / max(1, self.get_allocated_width()) * 6
        for ets, level, kind, text in self.events:
            if abs(ets - ts) <= tol:
                lines.append(f"● {time.strftime('%H:%M:%S', time.localtime(ets))}  {text}")
        tooltip.set_text("\n".join(lines))
        return True


class SystemRecorderTab(Tab):
    title = _("Systemrekorder")

    def __init__(self, app):
        super().__init__(app)
        self.reader = Reader()
        self.recorder = app.recorder
        self.span = 900
        self.live = True
        self.playing = None
        self.speed = 10
        self._last_reload = 0
        self._panel_pending = False

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin=18)

        # Kopfzeile
        head = Gtk.Box(spacing=12)
        head.pack_start(styled_label(_("Systemrekorder"), "tm-h1"), False, False, 0)
        self.rec_chip = styled_label("", "tm-chip")
        head.pack_start(self.rec_chip, False, False, 0)
        self.rec_switch = Gtk.Switch(active=self.app.settings.get("fr_enabled", True))
        self.rec_switch.set_valign(Gtk.Align.CENTER)
        self.rec_switch.connect("notify::active", self._on_switch)
        head.pack_end(self.rec_switch, False, False, 0)
        head.pack_end(styled_label(_("Aufzeichnen"), "tm-dim"), False, False, 0)
        self.db_label = styled_label("", "tm-dim")
        outer.pack_start(head, False, False, 0)

        # Steuerleiste
        bar = Gtk.Box(spacing=10)
        ranges = Gtk.Box()
        ranges.get_style_context().add_class("linked")
        group = None
        self.range_buttons = {}
        for label, secs in RANGES:
            rb = Gtk.RadioButton.new_with_label_from_widget(group, label)
            group = group or rb
            rb.set_mode(False)
            rb.set_active(secs == self.span)
            rb.connect("toggled", lambda b, s=secs: b.get_active() and self.set_span(s))
            ranges.pack_start(rb, False, False, 0)
            self.range_buttons[secs] = rb
        bar.pack_start(ranges, False, False, 0)

        ctl = Gtk.Box()
        ctl.get_style_context().add_class("linked")

        def icon_btn(icon, tip, cb):
            b = Gtk.Button.new_from_icon_name(icon, Gtk.IconSize.BUTTON)
            b.set_tooltip_text(tip)
            b.connect("clicked", lambda *_xx: cb())
            ctl.pack_start(b, False, False, 0)
            return b

        icon_btn("media-skip-backward-symbolic", _("Vorheriges Ereignis"), lambda: self.jump_event(False))
        icon_btn("media-seek-backward-symbolic", _("Zurück"), lambda: self.step(-1))
        self.play_btn = icon_btn("media-playback-start-symbolic", _("Abspielen / Pause"), self.toggle_play)
        icon_btn("media-seek-forward-symbolic", _("Vor"), lambda: self.step(1))
        icon_btn("media-skip-forward-symbolic", _("Nächstes Ereignis"), lambda: self.jump_event(True))
        bar.pack_start(ctl, False, False, 0)
        self.speed_combo = Gtk.ComboBoxText()
        for label, v in SPEEDS:
            self.speed_combo.append(str(v), label)
        self.speed_combo.set_active_id(str(self.speed))
        self.speed_combo.set_tooltip_text(_("Abspielgeschwindigkeit"))
        self.speed_combo.connect("changed", lambda c: setattr(self, "speed", int(c.get_active_id())))
        bar.pack_start(self.speed_combo, False, False, 0)
        self.live_btn = Gtk.Button(label=_("● LIVE"))
        self.live_btn.connect("clicked", lambda *_xx: self.go_live())
        bar.pack_start(self.live_btn, False, False, 0)

        self.time_big = styled_label("", "tm-big", xalign=1)
        self.time_ago = styled_label("", "tm-dim", xalign=1)
        tbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        tbox.pack_start(self.time_big, False, False, 0)
        tbox.pack_start(self.time_ago, False, False, 0)
        head.pack_end(tbox, False, False, 16)
        outer.pack_start(bar, False, False, 0)

        # Zeitleiste
        tl_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        tl_card.get_style_context().add_class("tm-card")
        self.timeline = Timeline()
        self.timeline.on_seek = self.seek
        self.timeline.on_zoom = self.zoom
        self.timeline.connect("size-allocate", lambda *_xx: self._schedule_reload())
        tl_card.pack_start(self.timeline, True, True, 0)
        tl_card.pack_start(styled_label(_("Klicken/Ziehen: Zeitpunkt wählen  ·  Mausrad: zoomen  ·  "
                                        "Umschalt+Mausrad: verschieben  ·  ◆ = Ereignis"), "tm-dim"),
                           False, False, 0)
        outer.pack_start(tl_card, False, False, 0)

        # Zustand + Ereignisse
        lower = Gtk.Box(spacing=14)
        state = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        state.get_style_context().add_class("tm-card")
        sh = Gtk.Box()
        self.state_title = styled_label(_("ZUSTAND"), "tm-card-title")
        sh.pack_start(self.state_title, False, False, 0)
        self.state_note = styled_label("", "tm-dim", xalign=1)
        sh.pack_end(self.state_note, False, False, 0)
        state.pack_start(sh, False, False, 0)
        tiles = Gtk.Grid(column_spacing=24, row_spacing=8, column_homogeneous=True)
        self.tiles = {}
        for i, (key, caption) in enumerate((
                ("cpu", _("CPU")), ("mem", _("Arbeitsspeicher")), ("swap", _("Swap")), ("gpu", _("GPU")),
                ("temp", _("Temperatur")), ("freq", _("Takt")), ("read", _("Lesen")), ("write", _("Schreiben")),
                ("rx", _("Empfangen")), ("tx", _("Senden")), ("bat", _("Akku / Leistung")), ("load", _("Last / Prozesse")))):
            cell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            cell.pack_start(styled_label(caption, "tm-dim"), False, False, 0)
            v = styled_label("–", "tm-mid")
            cell.pack_start(v, False, False, 0)
            tiles.attach(cell, i % 4, i // 4, 1, 1)
            self.tiles[key] = v
        state.pack_start(tiles, False, False, 0)

        self.pstore = Gtk.ListStore(GdkPixbuf.Pixbuf, str, int, str, float, float, float)
        pv = Gtk.TreeView(model=self.pstore)
        pv.set_tooltip_column(-1)
        col = Gtk.TreeViewColumn(_("Prozess (Top nach CPU, RAM, E/A)"))
        pix = Gtk.CellRendererPixbuf()
        col.pack_start(pix, False)
        col.add_attribute(pix, "pixbuf", 0)
        txt = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END)
        col.pack_start(txt, True)
        col.add_attribute(txt, "text", 1)
        col.set_expand(True)
        col.set_sort_column_id(1)
        pv.append_column(col)
        c = Gtk.TreeViewColumn(_("PID"), Gtk.CellRendererText(xalign=1), text=2)
        c.set_sort_column_id(2)
        pv.append_column(c)
        c = Gtk.TreeViewColumn(_("Benutzer"), Gtk.CellRendererText(), text=3)
        c.set_sort_column_id(3)
        pv.append_column(c)
        total = self.app.mem_total
        for title, colid, fmt, scale in ((_("CPU (Ø 5 s)"), 4, lambda v: util.pct(v, 1), lambda v: v / 100),
                                         (_("Arbeitsspeicher"), 5, util.mb, lambda v: v / (total * 0.15)),
                                         (_("Datenträger"), 6, util.rate, lambda v: v / (20 * 1048576))):
            cell = Gtk.CellRendererText(xalign=1)
            c = Gtk.TreeViewColumn(title, cell)
            c.set_cell_data_func(cell, heat_cell_func(colid, fmt, scale))
            c.set_sort_column_id(colid)
            c.set_alignment(1)
            c.set_min_width(110)
            pv.append_column(c)
        self.pstore.set_sort_column_id(4, Gtk.SortType.DESCENDING)
        psw = scrolled(pv)
        psw.set_margin_start(0)
        psw.set_margin_end(0)
        psw.set_size_request(-1, 260)
        state.pack_start(psw, True, True, 0)
        lower.pack_start(state, True, True, 0)

        ev = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        ev.get_style_context().add_class("tm-card")
        eh = Gtk.Box()
        eh.pack_start(styled_label(_("EREIGNISSE IM ZEITRAUM"), "tm-card-title"), False, False, 0)
        self.ev_count = styled_label("", "tm-dim", xalign=1)
        eh.pack_end(self.ev_count, False, False, 0)
        ev.pack_start(eh, False, False, 0)
        self.ev_list = Gtk.ListBox()
        self.ev_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.ev_list.set_activate_on_single_click(True)
        self.ev_list.connect("row-activated", lambda lb, row: self.seek(row.ts, keep_live=False))
        self.ev_list.get_style_context().add_class("tm-devlist")
        esw = Gtk.ScrolledWindow()
        esw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        esw.add(self.ev_list)
        esw.set_vexpand(True)
        ev.pack_start(esw, True, True, 0)
        ev.set_size_request(300, -1)
        lower.pack_start(ev, False, False, 0)
        outer.pack_start(lower, True, True, 0)

        # Einstellungen
        foot = Gtk.Box(spacing=10)
        foot.pack_start(styled_label(_("Aufbewahren:"), "tm-dim"), False, False, 0)
        self.ret = Gtk.ComboBoxText()
        for label, hours in RETENTIONS:
            self.ret.append(str(hours), label)
        self.ret.set_active_id(str(self.app.settings.get("fr_retention_h", 24)))
        self.ret.connect("changed", self._on_retention)
        foot.pack_start(self.ret, False, False, 0)
        self.daemon_check = Gtk.CheckButton(label=_("Im Hintergrund aufzeichnen"))
        self.daemon_check.set_tooltip_text(_("Auch ohne offenes Fenster aufzeichnen: startet einen kleinen "
                                           "Hintergrunddienst, auch automatisch beim Anmelden"))
        self.daemon_check.set_active(os.path.exists(AUTOSTART))
        self.daemon_check.connect("toggled", self._on_daemon)
        foot.pack_start(self.daemon_check, False, False, 10)
        foot.pack_start(self.db_label, False, False, 6)
        clear = Gtk.Button(label=_("Löschen"))
        clear.set_tooltip_text(_("Gesamte Aufzeichnung löschen"))
        clear.get_style_context().add_class("tm-danger")
        clear.connect("clicked", lambda *_xx: self._clear())
        foot.pack_end(clear, False, False, 0)
        export = Gtk.Button(label="CSV-Export…")
        export.set_tooltip_text(_("Sichtbaren Zeitraum als CSV-Datei exportieren"))
        export.connect("clicked", lambda *_xx: self._export())
        foot.pack_end(export, False, False, 0)
        outer.pack_start(foot, False, False, 0)

        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.add(outer)
        self.widget = sw

    # -------------------------------------------------------------- Daten
    def on_shown(self):
        self._last_reload = 0
        if self.live:
            self.go_live()
        else:
            self.reload()

    def update(self, snap):
        self._update_status()
        if self.live and time.monotonic() - self._last_reload > 2:
            now = time.time()
            self.timeline.t1 = now
            self.timeline.t0 = now - self._effective_span()
            self.timeline.playhead = now
            self.reload()
            self._update_panel()
        elif not self.live:
            set_text(self.time_ago, ago(self.timeline.playhead))

    def _effective_span(self):
        if self.span is None:
            first, _x, _x = self.reader.bounds()
            return max(300.0, time.time() - first) if first else 900.0
        return self.span

    def _schedule_reload(self):
        if not getattr(self, "_reload_pending", False):
            self._reload_pending = True
            GLib.timeout_add(80, self._do_reload)

    def _do_reload(self):
        self._reload_pending = False
        self.reload()
        return False

    def reload(self):
        self._last_reload = time.monotonic()
        tl = self.timeline
        n = max(60, tl.get_allocated_width() // 3)
        try:
            tl.data = self.reader.buckets(tl.t0, tl.t1, n)
            tl.events = self.reader.events(tl.t0, tl.t1)
        except Exception as e:  # z. B. Datenbank gesperrt
            print("Systemrekorder:", e)
            return
        tl.n = n
        tl.queue_draw()
        self._fill_events(tl.events)
        set_text(self.db_label, _('Datenbank {0}').format(util.size(Reader.db_size())))

    def _fill_events(self, events):
        sig = (len(events), events[-1][0] if events else 0)
        if getattr(self, "_ev_sig", None) == sig:
            return
        self._ev_sig = sig
        for child in self.ev_list.get_children():
            self.ev_list.remove(child)
        shown = [e for e in reversed(events)][:300]
        for ts, level, kind, text in shown:
            row = Gtk.ListBoxRow()
            row.ts = ts
            box = Gtk.Box(spacing=10, margin=6)
            dot = Gtk.Label()
            r, g, b = theme.rgb(LEVEL_COLOR.get(level, "accent"))
            dot.set_markup(f"<span foreground='#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}'>◆</span>")
            box.pack_start(dot, False, False, 0)
            vb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            vb.pack_start(styled_label(time.strftime(util.date_fmt("day") + " %H:%M:%S", time.localtime(ts)), "tm-dim"),
                          False, False, 0)
            t = styled_label(text, wrap=True, max_width_chars=40)
            t.set_line_wrap(True)
            vb.pack_start(t, False, False, 0)
            box.pack_start(vb, True, True, 0)
            row.add(box)
            row.set_tooltip_text(_("Klicken, um zu diesem Zeitpunkt zu springen"))
            self.ev_list.add(row)
        self.ev_list.show_all()
        set_text(self.ev_count, f"{len(events)}")

    # ---------------------------------------------------------- Navigation
    def set_span(self, secs):
        self.span = secs
        tl = self.timeline
        span = self._effective_span()
        if self.live:
            tl.t1 = time.time()
            tl.t0 = tl.t1 - span
        else:
            center = tl.playhead
            tl.t0, tl.t1 = center - span / 2, center + span / 2
            self._clamp()
        self.reload()

    def _clamp(self):
        tl = self.timeline
        now = time.time()
        if tl.t1 > now:
            d = tl.t1 - now
            tl.t0 -= d
            tl.t1 = now

    def zoom(self, t0, t1):
        tl = self.timeline
        tl.t0, tl.t1 = t0, t1
        self._clamp()
        self.span = tl.t1 - tl.t0
        for secs, rb in self.range_buttons.items():
            if secs == self.span:
                rb.set_active(True)
        if tl.t1 < time.time() - 2:
            self._set_live(False)
        self.reload()

    def seek(self, ts, keep_live=True):
        tl = self.timeline
        now = time.time()
        ts = min(ts, now)
        tl.playhead = ts
        if not (tl.t0 <= ts <= tl.t1):
            span = tl.t1 - tl.t0
            tl.t0, tl.t1 = ts - span / 2, ts + span / 2
            self._clamp()
            self.reload()
        self._set_live(keep_live and now - ts < 2)
        tl.queue_draw()
        if not self._panel_pending:
            self._panel_pending = True
            GLib.idle_add(self._update_panel)

    def step(self, direction):
        self.stop_play()
        span = self.timeline.t1 - self.timeline.t0
        self.seek(self.timeline.playhead + direction * max(5.0, span / 60), keep_live=False)

    def jump_event(self, forward):
        self.stop_play()
        ts = self.reader.adjacent_event(self.timeline.playhead, forward)
        if ts is None:
            set_text(self.state_note, _("Kein weiteres Ereignis"))
            return
        self.seek(ts, keep_live=False)

    def go_live(self):
        self.stop_play()
        self._set_live(True)
        now = time.time()
        tl = self.timeline
        tl.t1 = now
        tl.t0 = now - self._effective_span()
        tl.playhead = now
        self.reload()
        self._update_panel()

    def _set_live(self, live):
        self.live = live
        ctx = self.live_btn.get_style_context()
        if live:
            ctx.add_class("tm-primary")
        else:
            ctx.remove_class("tm-primary")

    def toggle_play(self):
        if self.playing:
            self.stop_play()
            return
        tl = self.timeline
        if self.live or time.time() - tl.playhead < 2:
            # von vorne im sichtbaren Bereich abspielen
            tl.playhead = tl.t0
        self._set_live(False)
        self.play_btn.set_image(Gtk.Image.new_from_icon_name("media-playback-pause-symbolic", Gtk.IconSize.BUTTON))
        self._play_t = time.monotonic()
        self.playing = GLib.timeout_add(100, self._tick)

    def stop_play(self):
        if self.playing:
            GLib.source_remove(self.playing)
            self.playing = None
            self.play_btn.set_image(Gtk.Image.new_from_icon_name("media-playback-start-symbolic", Gtk.IconSize.BUTTON))

    def _tick(self):
        now_m = time.monotonic()
        dt = now_m - self._play_t
        self._play_t = now_m
        tl = self.timeline
        ts = tl.playhead + dt * self.speed
        if ts >= time.time() - 1:
            self.playing = None
            self.play_btn.set_image(Gtk.Image.new_from_icon_name("media-playback-start-symbolic", Gtk.IconSize.BUTTON))
            self.go_live()
            return False
        if ts > tl.t1:
            span = tl.t1 - tl.t0
            tl.t0, tl.t1 = ts - span * 0.1, ts + span * 0.9
            self._clamp()
            self.reload()
        self.seek(ts, keep_live=False)
        return True

    # -------------------------------------------------------------- Anzeige
    def _update_panel(self):
        self._panel_pending = False
        ts = self.timeline.playhead
        set_text(self.time_big, fmt_time(ts))
        set_text(self.time_ago, _("LIVE") if self.live else ago(ts))
        s = self.reader.sample_at(ts)
        t = self.tiles
        if s is None:
            for v in t.values():
                set_text(v, "–")
            set_text(self.state_note, _("Keine Aufzeichnung zu diesem Zeitpunkt"))
        else:
            set_text(self.state_note, _("Messwert von ") + time.strftime("%H:%M:%S", time.localtime(s["ts"])))
            set_text(t["cpu"], util.pct(s["cpu"]))
            set_text(t["mem"], f"{util.pct(s['mem'])} · {util.size(s['mem_used'])}" if s["mem_used"]
                     else util.pct(s["mem"]))
            set_text(t["swap"], util.pct(s["swap"]))
            set_text(t["gpu"], util.pct(s["gpu"]) if s["gpu"] is not None else "–")
            set_text(t["temp"], f"{util.num(s['temp'], 0)} °C" if s["temp"] is not None else "–")
            set_text(t["freq"], util.ghz(s["freq"]))
            set_text(t["read"], util.rate(s["disk_r"]))
            set_text(t["write"], util.rate(s["disk_w"]))
            set_text(t["rx"], util.bits(s["net_rx"]))
            set_text(t["tx"], util.bits(s["net_tx"]))
            bat = util.pct(s["bat"]) if s["bat"] is not None else "–"
            if s["watts"]:
                bat += f" · {util.num(s['watts'], 1)} W"
            set_text(t["bat"], bat)
            set_text(t["load"], f"{util.num(s['load1'], 2)} · {s['procs']}")
        pts, rows = self.reader.procs_at(ts)
        self.pstore.clear()
        for pid, name, user, cpu, mem, io, cmd in rows:
            self.pstore.append([icons.for_process(name), name, pid, user or "", cpu or 0.0,
                                float(mem or 0), float(io or 0)])
        set_text(self.state_title, _('ZUSTAND UM {0}').format(time.strftime('%H:%M:%S', time.localtime(ts))))
        return False

    def _update_status(self):
        holder = self.recorder.holder()
        if not self.app.settings.get("fr_enabled", True) and self.recorder.active:
            text = _("⏸ PAUSIERT")
        elif self.recorder.active:
            text = _("● REC")
        elif holder and not self._recent_sample():
            text = _("⏸ PAUSIERT (anderes Fenster)") if holder[0] == "gui" else _("⏸ PAUSIERT (Hintergrunddienst)")
        elif holder and holder[0] == "daemon":
            text = _("● REC (Hintergrunddienst)")
        elif holder:
            text = _("● REC (anderes Fenster)")
        else:
            text = _("○ keine Aufzeichnung")
        set_text(self.rec_chip, text)
        self.rec_switch.set_sensitive(self.recorder.active)

    def _recent_sample(self):
        """Gab es in den letzten 15 s einen Messwert? (sonst pausiert der andere Prozess)"""
        _first, last, _n = self.reader.bounds()
        return last is not None and time.time() - last < 15

    # --------------------------------------------------------- Einstellungen
    def _on_switch(self, sw, pspec):
        self.app.settings["fr_enabled"] = sw.get_active()
        if self.recorder.active:
            self.recorder.event("info", "pause", _("Aufzeichnung fortgesetzt") if sw.get_active()
                                else _("Aufzeichnung pausiert"))
        self._update_status()

    def _on_retention(self, combo):
        self.app.settings["fr_retention_h"] = int(combo.get_active_id())
        self.recorder._last_purge = 0  # beim nächsten Messwert aufräumen

    def _on_daemon(self, cb):
        if cb.get_active():
            os.makedirs(os.path.dirname(AUTOSTART), exist_ok=True)
            exe = os.path.join(PROJECT_DIR, "taskmanager.sh")
            with open(AUTOSTART, "w") as f:
                f.write(_('[Desktop Entry]\nType=Application\nName=Taskmanager Systemrekorder\nComment=Zeichnet Systemdaten für den Systemrekorder im Hintergrund auf\nExec="{0}" --recorder\nIcon=media-record\nTerminal=false\nNoDisplay=false\nX-GNOME-Autostart-enabled=true\nX-GNOME-Autostart-Delay=10\n').format(exe))
            # gleich starten – übernimmt die Aufzeichnung, sobald dieses Fenster geschlossen wird
            subprocess.Popen([sys.executable, "-m", "taskmanager", "--recorder"], cwd=PROJECT_DIR,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        else:
            try:
                os.remove(AUTOSTART)
            except OSError:
                pass
            holder = self.recorder.holder()
            if holder and holder[0] == "daemon":
                try:
                    os.kill(holder[1], 15)
                except OSError:
                    pass
            for pid in _daemon_pids():
                try:
                    os.kill(pid, 15)
                except OSError:
                    pass

    def _clear(self):
        if not self.recorder.active:
            actions.message(self.app.window, _("Löschen nicht möglich"),
                            _("Die Aufzeichnung gehört gerade einem anderen Prozess (Hintergrunddienst)."))
            return
        if actions.confirm(self.app.window, _("Gesamte Aufzeichnung löschen?"),
                           _("Alle Messwerte, Prozess-Schnappschüsse und Ereignisse werden entfernt."),
                           _("Löschen")):
            self.recorder.clear()
            GLib.timeout_add(2500, lambda: self.go_live() or False)

    def _export(self):
        fc = Gtk.FileChooserNative.new(_("Zeitraum als CSV exportieren"), self.app.window,
                                       Gtk.FileChooserAction.SAVE, _("Exportieren"), None)
        fc.set_current_name(time.strftime("systemrekorder-%Y%m%d-%H%M.csv"))
        fc.set_do_overwrite_confirmation(True)
        if fc.run() == Gtk.ResponseType.ACCEPT:
            try:
                self.reader.export_csv(fc.get_filename(), self.timeline.t0, self.timeline.t1)
            except OSError as e:
                actions.message(self.app.window, _("Export fehlgeschlagen"), str(e))


def _daemon_pids():
    import psutil
    result = []
    for p in psutil.process_iter(["pid", "cmdline"]):
        cmd = p.info["cmdline"] or []
        if "--recorder" in cmd and any("taskmanager" in c for c in cmd) and p.pid != os.getpid():
            result.append(p.pid)
    return result
