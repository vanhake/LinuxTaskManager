"""Eigene Widgets im Neon-Stil: Graph, Ringanzeige, Balken, Treemap, Heatmap-Zellen.

Farben werden als Schlüssel des aktiven Farbschemas angegeben ("cpu", "mem", ...)
und bei jedem Zeichnen neu aufgelöst – ein Themenwechsel wirkt sofort.
"""

from .i18n import _

import math
from collections import deque

import cairo
from gi.repository import Gdk, GLib, Gtk, Pango, PangoCairo

from . import theme, util

HISTORY = 60

# Abwärtskompatibel: frühere Tupel-Farben → Schlüssel
COLORS = {k: k for k in ("cpu", "mem", "disk", "net", "gpu", "power")}


def nice_ceiling(value):
    """Nächste „runde“ Skalenobergrenze (1, 2, 5 × 10^n)."""
    if value <= 0:
        return 1.0
    exp = math.floor(math.log10(value))
    base = 10 ** exp
    for m in (1, 2, 5, 10):
        if value <= m * base:
            return m * base
    return 10 * base


def rounded_rect(cr, x, y, w, h, r):
    r = max(0, min(r, w / 2, h / 2))
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def draw_text(cr, widget, text, x, y, size=10, bold=False, color=(1, 1, 1, 1), align=0.0,
              valign=0.0, family=None, max_width=None):
    layout = PangoCairo.create_layout(cr)
    desc = widget.get_pango_context().get_font_description().copy()
    if family:
        desc.set_family(family)
    desc.set_absolute_size(size * Pango.SCALE)
    desc.set_weight(Pango.Weight.BOLD if bold else Pango.Weight.NORMAL)
    layout.set_font_description(desc)
    layout.set_text(text, -1)
    if max_width:
        layout.set_width(int(max_width * Pango.SCALE))
        layout.set_ellipsize(Pango.EllipsizeMode.END)
    w, h = layout.get_pixel_size()
    cr.set_source_rgba(*color)
    cr.move_to(x - w * align, y - h * valign)
    PangoCairo.show_layout(cr, layout)
    return w, h


class Graph(Gtk.DrawingArea):
    """Verlaufsgraph mit Glow, Verlaufsfüllung und bis zu zwei Serien.

    fixed_max=None → automatische Skalierung; scale_changed(max) wird dann
    bei Änderung der Skala aufgerufen.
    """

    def __init__(self, color, series=1, fixed_max=100.0, mini=False, min_scale=1.0, colors=None):
        super().__init__()
        self.color = color
        self.colors = colors  # optional eigene Farbe je Serie
        self.fixed_max = fixed_max
        self.mini = mini
        self.min_scale = min_scale
        self.data = [deque([0.0] * HISTORY, maxlen=HISTORY) for _x in range(series)]
        self.scale = fixed_max or min_scale
        self.scale_changed = None
        self.tick = 0
        self.set_size_request(70, 40) if mini else self.set_size_request(200, 110)
        self.connect("draw", self._draw)

    def push(self, *values):
        for d, v in zip(self.data, values):
            d.append(float(v or 0.0))
        self.tick += 1
        if self.fixed_max is None:
            peak = max(max(d) for d in self.data)
            new = nice_ceiling(max(peak, self.min_scale))
            if new != self.scale:
                self.scale = new
                if self.scale_changed:
                    self.scale_changed(new)
        if self.get_mapped():
            self.queue_draw()

    def _draw(self, widget, cr):
        w = widget.get_allocated_width()
        h = widget.get_allocated_height()
        radius = 6 if self.mini else 10
        n = HISTORY - 1
        scale = self.scale or 1.0
        br, bgc, bb = theme.rgb("surface2")
        r, g, b = theme.rgb(self.color)
        dark = theme.is_dark()

        rounded_rect(cr, 0.5, 0.5, w - 1, h - 1, radius)
        cr.set_source_rgb(br, bgc, bb)
        cr.fill_preserve()
        cr.save()
        cr.clip()

        if not self.mini:
            cr.set_source_rgba(r, g, b, 0.10 if dark else 0.14)
            cr.set_line_width(1)
            for i in range(1, 5):
                y = round(h * i / 5) + 0.5
                cr.move_to(0, y)
                cr.line_to(w, y)
            cols = 12
            step = w / cols
            offset = (self.tick % 4) * step / 4
            x = w - offset
            while x > 0:
                cr.move_to(round(x) + 0.5, 0)
                cr.line_to(round(x) + 0.5, h)
                x -= step
            cr.stroke()

        pad = 2
        for idx, series in enumerate(self.data):
            cr_, cg, cb = theme.rgb(self.colors[idx]) if self.colors else (r, g, b)
            pts = [(w * i / n, h - pad - min(1.0, v / scale) * (h - 2 * pad)) for i, v in enumerate(series)]

            def path():
                cr.move_to(*pts[0])
                for i in range(1, len(pts)):
                    x0, y0 = pts[i - 1]
                    x1, y1 = pts[i]
                    mx = (x0 + x1) / 2
                    cr.curve_to(mx, y0, mx, y1, x1, y1)

            if idx == 0 or self.colors:
                path()
                cr.line_to(w, h)
                cr.line_to(0, h)
                cr.close_path()
                grad = cairo.LinearGradient(0, 0, 0, h)
                grad.add_color_stop_rgba(0, cr_, cg, cb, 0.38 if dark else 0.30)
                grad.add_color_stop_rgba(1, cr_, cg, cb, 0.02)
                cr.set_source(grad)
                cr.fill()
            dash = [] if (idx == 0 or self.colors) else [5, 4]
            cr.set_dash(dash)
            if dark:  # Glow
                path()
                cr.set_source_rgba(cr_, cg, cb, 0.22)
                cr.set_line_width(5 if not self.mini else 3.5)
                cr.stroke()
            path()
            cr.set_source_rgba(cr_, cg, cb, 1.0)
            cr.set_line_width(1.8 if not self.mini else 1.4)
            cr.stroke()
            cr.set_dash([])
        cr.restore()

        rounded_rect(cr, 0.5, 0.5, w - 1, h - 1, radius)
        cr.set_source_rgba(r, g, b, 0.55 if dark else 0.7)
        cr.set_line_width(1)
        cr.stroke()


class RingGauge(Gtk.DrawingArea):
    """Kreisanzeige 0..100 % mit großem Wert in der Mitte."""

    def __init__(self, color, size=132, thickness=11, levels="high"):
        super().__init__()
        self.color = color
        self.levels = levels  # "high": hohe Werte warnen, "low": niedrige Werte warnen
        self.value = 0.0
        self.shown = 0.0
        self.text = "0 %"
        self.sub = ""
        self.thickness = thickness
        self.set_size_request(size, size)
        self.connect("draw", self._draw)
        self._anim = None

    def set_value(self, value, text=None, sub=""):
        self.value = max(0.0, min(100.0, value or 0.0))
        self.text = text if text is not None else util.pct(self.value)
        self.sub = sub
        if self._anim is None and self.get_mapped():
            self._anim = GLib.timeout_add(16, self._step)
        elif not self.get_mapped():
            self.shown = self.value

    def _step(self):
        diff = self.value - self.shown
        if abs(diff) < 0.3:
            self.shown = self.value
            self._anim = None
            self.queue_draw()
            return False
        self.shown += diff * 0.22
        self.queue_draw()
        return True

    def _draw(self, widget, cr):
        w = widget.get_allocated_width()
        h = widget.get_allocated_height()
        size = min(w, h)
        cx, cy = w / 2, h / 2
        rad = size / 2 - self.thickness / 2 - 3
        start = math.pi * 0.75
        sweep = math.pi * 1.5
        if self.levels == "low":
            key = "crit" if self.value < 15 else ("warn" if self.value < 30 else self.color)
        else:
            key = theme.level_color(self.value, self.color)
        r, g, b = theme.rgb(key)
        tr, tg, tb = theme.rgb("border")
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_line_width(self.thickness)
        cr.set_source_rgb(tr, tg, tb)
        cr.arc(cx, cy, rad, start, start + sweep)
        cr.stroke()
        frac = self.shown / 100.0
        if frac > 0.003:
            end = start + sweep * frac
            if theme.is_dark():
                cr.set_line_width(self.thickness + 8)
                cr.set_source_rgba(r, g, b, 0.16)
                cr.arc(cx, cy, rad, start, end)
                cr.stroke()
            cr.set_line_width(self.thickness)
            grad = cairo.LinearGradient(cx - rad, cy + rad, cx + rad, cy - rad)
            grad.add_color_stop_rgba(0, r, g, b, 0.55)
            grad.add_color_stop_rgba(1, r, g, b, 1.0)
            cr.set_source(grad)
            cr.arc(cx, cy, rad, start, end)
            cr.stroke()
        tc = theme.rgb("text")
        dc = theme.rgb("dim")
        big = max(12, size * 0.19)
        draw_text(cr, widget, self.text, cx, cy - (big * 0.15 if self.sub else 0), size=big, bold=True,
                  color=(*tc, 1), align=0.5, valign=0.5)
        if self.sub:
            draw_text(cr, widget, self.sub, cx, cy + big * 0.62, size=max(8, size * 0.085),
                      color=(*dc, 1), align=0.5, valign=0.5, max_width=rad * 1.5)


class UsageBar(Gtk.DrawingArea):
    """Abgerundeter Füllstandsbalken; Farbe wechselt bei hoher Belegung."""

    def __init__(self, color, height=10, levels=True):
        super().__init__()
        self.color = color
        self.levels = levels
        self.fraction = 0.0
        self.set_size_request(60, height)
        self.set_hexpand(True)
        self.connect("draw", self._draw)

    def set_fraction(self, f):
        f = max(0.0, min(1.0, f or 0.0))
        if abs(f - self.fraction) > 0.0005:
            self.fraction = f
            self.queue_draw()

    def _draw(self, widget, cr):
        w = widget.get_allocated_width()
        h = widget.get_allocated_height()
        key = theme.level_color(self.fraction * 100, self.color) if self.levels else self.color
        r, g, b = theme.rgb(key)
        rounded_rect(cr, 0, 0, w, h, h / 2)
        cr.set_source_rgb(*theme.rgb("surface2"))
        cr.fill_preserve()
        cr.set_source_rgb(*theme.rgb("border"))
        cr.set_line_width(1)
        cr.stroke()
        fw = max(h, w * self.fraction) if self.fraction > 0 else 0
        if fw:
            rounded_rect(cr, 0, 0, fw, h, h / 2)
            grad = cairo.LinearGradient(0, 0, fw, 0)
            grad.add_color_stop_rgba(0, r, g, b, 0.55)
            grad.add_color_stop_rgba(1, r, g, b, 1.0)
            cr.set_source(grad)
            cr.fill()


class SegmentBar(Gtk.DrawingArea):
    """Balken mit mehreren Segmenten (Speicherzusammensetzung)."""

    def __init__(self, color):
        super().__init__()
        self.color = color
        self.segments = []  # (anteil 0..1, alpha, tooltip)
        self.set_size_request(200, 30)
        self.set_has_tooltip(True)
        self.connect("draw", self._draw)
        self.connect("query-tooltip", self._tooltip)

    def set_segments(self, segments):
        self.segments = segments
        self.queue_draw()

    def _ranges(self, w):
        x = 0.0
        for frac, alpha, tip in self.segments:
            sw = frac * w
            yield x, sw, alpha, tip
            x += sw

    def _draw(self, widget, cr):
        w = widget.get_allocated_width()
        h = widget.get_allocated_height()
        r, g, b = theme.rgb(self.color)
        rounded_rect(cr, 0.5, 0.5, w - 1, h - 1, 8)
        cr.set_source_rgb(*theme.rgb("surface2"))
        cr.fill_preserve()
        cr.save()
        cr.clip()
        for x, sw, alpha, _x in self._ranges(w):
            cr.set_source_rgba(r, g, b, alpha)
            cr.rectangle(x, 0, sw, h)
            cr.fill()
            cr.set_source_rgba(r, g, b, 0.9)
            cr.set_line_width(1)
            cr.move_to(round(x + sw) + 0.5, 0)
            cr.line_to(round(x + sw) + 0.5, h)
            cr.stroke()
        cr.restore()
        rounded_rect(cr, 0.5, 0.5, w - 1, h - 1, 8)
        cr.set_source_rgba(r, g, b, 0.8)
        cr.stroke()

    def _tooltip(self, widget, x, y, keyboard, tooltip):
        w = widget.get_allocated_width()
        for sx, sw, _x, tip in self._ranges(w):
            if sx <= x < sx + sw:
                tooltip.set_text(tip)
                return True
        return False


# ---------------------------------------------------------------- Treemap

def _worst(row, side):
    s = sum(row)
    if s <= 0 or side <= 0:
        return float("inf")
    return max(max(side * side * r / (s * s), (s * s) / (side * side * r)) for r in row if r > 0)


def squarify(values, x, y, w, h):
    """Squarified-Treemap-Layout. values absteigend sortiert, Summe = w*h."""
    rects = []
    values = list(values)
    while values:
        side = min(w, h)
        row = [values.pop(0)]
        while values and _worst(row + [values[0]], side) <= _worst(row, side):
            row.append(values.pop(0))
        s = sum(row)
        if w >= h:
            rw = s / h if h else 0
            yy = y
            for v in row:
                rh = v / rw if rw else 0
                rects.append((x, yy, rw, rh))
                yy += rh
            x += rw
            w -= rw
        else:
            rh = s / w if w else 0
            xx = x
            for v in row:
                rw2 = v / rh if rh else 0
                rects.append((xx, y, rw2, rh))
                xx += rw2
            y += rh
            h -= rh
    return rects


TREEMAP_KEYS = ["cpu", "mem", "disk", "net", "gpu", "power"]


class Treemap(Gtk.DrawingArea):
    """Kacheldiagramm der Ordnergrößen. activate(item) bei Klick."""

    def __init__(self):
        super().__init__()
        self.items = []  # (label, size, payload, is_dir)
        self.rects = []
        self.hover = -1
        self.activate = None
        self.format_size = str
        self.placeholder = _("Noch keine Analyse – wähle oben einen Ordner oder ein Laufwerk")
        self.set_size_request(300, 260)
        self.set_has_tooltip(True)
        self.add_events(Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.BUTTON_PRESS_MASK
                        | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self.connect("draw", self._draw)
        self.connect("motion-notify-event", self._motion)
        self.connect("leave-notify-event", self._leave)
        self.connect("button-press-event", self._press)
        self.connect("query-tooltip", self._tooltip)

    def set_items(self, items):
        self.items = [i for i in items if i[1] > 0][:60]
        self.hover = -1
        self.queue_draw()

    def _layout(self, w, h):
        total = sum(i[1] for i in self.items)
        if total <= 0:
            return []
        scale = (w * h) / total
        return squarify([i[1] * scale for i in self.items], 0, 0, w, h)

    def _draw(self, widget, cr):
        w = widget.get_allocated_width()
        h = widget.get_allocated_height()
        rounded_rect(cr, 0, 0, w, h, 12)
        cr.set_source_rgb(*theme.rgb("surface2"))
        cr.fill()
        self.rects = self._layout(w, h)
        dark = theme.is_dark()
        if not self.items:
            dc = theme.rgb("dim")
            draw_text(cr, widget, self.placeholder, w / 2, h / 2, size=12, color=(*dc, 1),
                      align=0.5, valign=0.5, max_width=w - 40)
            return
        tc = theme.rgb("text")
        for idx, ((x, y, rw, rh), item) in enumerate(zip(self.rects, self.items)):
            key = TREEMAP_KEYS[idx % len(TREEMAP_KEYS)] if item[3] else "dim"
            r, g, b = theme.rgb(key)
            gap = 2
            if rw - gap * 2 < 1 or rh - gap * 2 < 1:
                continue
            rounded_rect(cr, x + gap, y + gap, rw - gap * 2, rh - gap * 2, 7)
            base = 0.30 if dark else 0.35
            alpha = base + (0.25 if idx == self.hover else 0)
            grad = cairo.LinearGradient(x, y, x + rw, y + rh)
            grad.add_color_stop_rgba(0, r, g, b, alpha + 0.12)
            grad.add_color_stop_rgba(1, r, g, b, alpha * 0.55)
            cr.set_source(grad)
            cr.fill_preserve()
            cr.set_source_rgba(r, g, b, 0.95 if idx == self.hover else 0.6)
            cr.set_line_width(1.5 if idx == self.hover else 1)
            cr.stroke()
            if rw > 60 and rh > 34:
                draw_text(cr, widget, ("📁 " if item[3] else "") + item[0], x + 9, y + 7, size=11,
                          bold=True, color=(*tc, 1), max_width=rw - 18)
                draw_text(cr, widget, self.format_size(item[1]), x + 9, y + 24, size=9.5,
                          color=(*tc, 0.75), max_width=rw - 18)

    def _hit(self, x, y):
        for idx, (rx, ry, rw, rh) in enumerate(self.rects):
            if rx <= x < rx + rw and ry <= y < ry + rh:
                return idx
        return -1

    def _motion(self, widget, event):
        idx = self._hit(event.x, event.y)
        if idx != self.hover:
            self.hover = idx
            self.queue_draw()
            win = self.get_window()
            if win:
                cur = Gdk.Cursor.new_from_name(self.get_display(), "pointer") \
                    if idx >= 0 and self.items[idx][3] else None
                win.set_cursor(cur)

    def _leave(self, widget, event):
        self.hover = -1
        self.queue_draw()

    def _press(self, widget, event):
        idx = self._hit(event.x, event.y)
        if idx >= 0 and self.activate:
            self.activate(self.items[idx], event)
        return True

    def _tooltip(self, widget, x, y, keyboard, tooltip):
        idx = self._hit(x, y)
        if idx < 0:
            return False
        label, size, payload, is_dir = self.items[idx]
        tooltip.set_text(f"{label}\n{self.format_size(size)}" + (_("\nKlicken zum Öffnen") if is_dir else ""))
        return True


# ------------------------------------------------------------- Heatmap-Zellen

_BLACK = Gdk.RGBA(0, 0, 0, 1)


def heat_rgba(fraction):
    """Hintergrundfarbe für Zellen je nach Last (aus dem Farbschema)."""
    fraction = max(0.0, min(1.0, fraction))
    if fraction < 0.005:
        return None
    r, g, b = theme.rgb("heat")
    if theme.is_dark():
        alpha = 0.10 + 0.70 * math.sqrt(fraction)
    else:
        alpha = 0.15 + 0.72 * math.sqrt(fraction)
    return Gdk.RGBA(r, g, b, alpha)


def heat_cell_func(col_index, formatter, scale_func):
    """cell_data_func, die formatiert und einfärbt (scale_func → Anteil 0..1)."""

    def func(column, cell, model, it, data):
        value = model.get_value(it, col_index)
        cell.set_property("text", formatter(value))
        rgba = heat_rgba(scale_func(value)) if value is not None and value >= 0 else None
        if rgba is None:
            cell.set_property("cell-background-set", False)
            cell.set_property("foreground-set", False)
        else:
            cell.set_property("cell-background-rgba", rgba)
            if rgba.alpha > 0.5:
                cell.set_property("foreground-rgba", _BLACK)
            else:
                cell.set_property("foreground-set", False)
    return func


def column_header(title, value=""):
    """Zweizeiliger Spaltenkopf (Wert oben, Name unten)."""
    label = Gtk.Label(xalign=1.0)
    label.set_justify(Gtk.Justification.RIGHT)
    set_header(label, title, value)
    label.show()
    return label


def set_header(label, title, value):
    if value:
        markup = (f"<span size='large' weight='bold'>{GLib.markup_escape_text(value)}</span>\n"
                  f"{GLib.markup_escape_text(title)}")
    else:
        markup = f"\n{GLib.markup_escape_text(title)}"
    if label.get_label() != markup:
        label.set_markup(markup)


# ------------------------------------------------------------- Layout-Helfer

def card(title=None, child=None, spacing=10):
    """Abgerundete Kachel mit optionalem Titel."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)
    box.get_style_context().add_class("tm-card")
    if title:
        lbl = Gtk.Label(label=title.upper(), xalign=0)
        lbl.get_style_context().add_class("tm-card-title")
        box.pack_start(lbl, False, False, 0)
        box.title_label = lbl
    if child is not None:
        box.pack_start(child, True, True, 0)
    return box


def styled_label(text="", cls=None, xalign=0.0, **kw):
    lbl = Gtk.Label(label=text, xalign=xalign, **kw)
    if cls:
        for c in cls.split():
            lbl.get_style_context().add_class(c)
    return lbl


def set_text(label, text):
    if label.get_text() != text:
        label.set_text(text)
