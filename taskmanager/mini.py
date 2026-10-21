"""Mini-Modus: kompaktes, rahmenloses Fenster, immer im Vordergrund."""

from .i18n import _

from gi.repository import Gdk, Gtk

from . import util
from .widgets import Graph, UsageBar, set_text, styled_label


class MiniWindow(Gtk.Window):
    def __init__(self, app):
        super().__init__(title=_("Taskmanager Mini"))
        self.app = app
        self.set_decorated(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        self.set_resizable(False)
        self.get_style_context().add_class("tm-root")
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual is not None and screen.is_composited():
            self.set_visual(visual)
            self.set_app_paintable(True)
            self.connect("draw", self._draw_bg)

        # Innenabstand kommt aus dem CSS (.tm-mini padding), damit der Rahmen nicht am Inhalt klebt;
        # der äußere Rand lässt Platz für die abgerundeten Ecken.
        frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        frame.get_style_context().add_class("tm-mini")
        frame.set_margin_start(4)
        frame.set_margin_end(4)
        frame.set_margin_top(4)
        frame.set_margin_bottom(4)

        head = Gtk.Box(spacing=6)
        brand = styled_label(_("TASKMANAGER"), "tm-chip")
        head.pack_start(brand, False, False, 0)
        close = Gtk.Button.new_from_icon_name("window-close-symbolic", Gtk.IconSize.MENU)
        close.set_relief(Gtk.ReliefStyle.NONE)
        close.get_style_context().add_class("tm-flat")
        close.set_valign(Gtk.Align.CENTER)
        close.set_tooltip_text(_("Mini-Modus beenden"))
        close.connect("clicked", lambda *_xx: self.app.toggle_mini(False))
        head.pack_end(close, False, False, 0)
        frame.pack_start(head, False, False, 0)

        self.rows = {}
        grid = Gtk.Grid(column_spacing=12, row_spacing=8)
        for i, (key, label, color) in enumerate((("cpu", _("CPU"), "cpu"), ("mem", _("RAM"), "mem"),
                                                 ("gpu", _("GPU"), "gpu"), ("disk", _("DISK"), "disk"))):
            grid.attach(styled_label(label, "tm-card-title"), 0, i, 1, 1)
            bar = UsageBar(color, height=9)
            bar.set_size_request(130, 9)
            grid.attach(bar, 1, i, 1, 1)
            val = styled_label("", "tm-num", xalign=1, width_chars=7)
            grid.attach(val, 2, i, 1, 1)
            self.rows[key] = (bar, val)
        frame.pack_start(grid, False, False, 0)

        self.graph = Graph("net", series=2, fixed_max=None, min_scale=12500, colors=["net", "cpu"], mini=True)
        self.graph.set_size_request(230, 46)
        self.graph.set_margin_top(2)
        frame.pack_start(self.graph, False, False, 0)
        self.net = styled_label("", "tm-num tm-dim")
        frame.pack_start(self.net, False, False, 0)

        ev = Gtk.EventBox()
        ev.add(frame)
        ev.connect("button-press-event", self._on_press)
        ev.set_tooltip_text(_("Ziehen zum Verschieben · Doppelklick: großes Fenster"))
        self.add(ev)
        pos = app.settings.get("mini_pos")
        if pos:
            self.move(*pos)
        self.connect("configure-event", self._on_configure)

    def _draw_bg(self, widget, cr):
        cr.set_source_rgba(0, 0, 0, 0)
        cr.set_operator(0)  # CLEAR
        cr.paint()
        cr.set_operator(2)  # OVER
        return False

    def _on_press(self, widget, event):
        if event.type == Gdk.EventType.DOUBLE_BUTTON_PRESS:
            self.app.toggle_mini(False)
            return True
        if event.button == 1:
            self.begin_move_drag(event.button, int(event.x_root), int(event.y_root), event.time)
        return True

    def _on_configure(self, win, event):
        self.app.settings["mini_pos"] = list(self.get_position())
        return False

    def update(self, s):
        bar, val = self.rows["cpu"]
        bar.set_fraction(s.cpu / 100)
        set_text(val, util.pct(s.cpu))
        bar, val = self.rows["mem"]
        bar.set_fraction(s.vm.percent / 100)
        set_text(val, util.pct(s.vm.percent))
        bar, val = self.rows["gpu"]
        g = next(iter(s.gpus.values()), None) if s.gpus else None
        u = g.get("usage") if g else None
        bar.set_fraction((u or 0) / 100)
        set_text(val, util.pct(u) if u is not None else "–")
        bar, val = self.rows["disk"]
        act = max((d["active"] for d in s.disks.values()), default=0)
        bar.set_fraction(act / 100)
        set_text(val, util.pct(act))
        down = sum(d["recv"] for d in s.net.values())
        up = sum(d["sent"] for d in s.net.values())
        self.graph.push(down, up)
        set_text(self.net, f"▼ {util.bits(down)}   ▲ {util.bits(up)}")
