"""Farbschemata (Neon, Synthwave, Matrix, Amber, Hell) und GTK-CSS."""

from gi.repository import Gdk, Gtk

PALETTES = {
    "Neon": {
        "dark": True,
        "bg": "#090d18", "surface": "#10172a", "surface2": "#172038", "border": "#233152",
        "text": "#e8f1ff", "dim": "#7f8db3", "accent": "#00e5ff",
        "cpu": "#00e5ff", "mem": "#ff2bd6", "disk": "#39ff88", "net": "#ffb000",
        "gpu": "#9b6bff", "power": "#ffe14d", "warn": "#ffb000", "crit": "#ff3860",
        "heat": "#ff8a00",
    },
    "Synthwave": {
        "dark": True,
        "bg": "#140826", "surface": "#1e0d38", "surface2": "#281449", "border": "#3d2266",
        "text": "#fdeaff", "dim": "#a98bc9", "accent": "#ff6ec7",
        "cpu": "#ff6ec7", "mem": "#00f0ff", "disk": "#fffb96", "net": "#ff9e40",
        "gpu": "#b967ff", "power": "#05ffa1", "warn": "#ff9e40", "crit": "#ff3b6b",
        "heat": "#ff6ec7",
    },
    "Matrix": {
        "dark": True,
        "bg": "#010804", "surface": "#04120a", "surface2": "#071c10", "border": "#0f3a20",
        "text": "#c8ffd8", "dim": "#4f9a68", "accent": "#00ff66",
        "cpu": "#00ff66", "mem": "#7dffb0", "disk": "#b6ff00", "net": "#00e0a0",
        "gpu": "#3dffcf", "power": "#e2ff5c", "warn": "#e2ff5c", "crit": "#ff4d4d",
        "heat": "#00ff66",
    },
    "Amber": {
        "dark": True,
        "bg": "#0e0902", "surface": "#170f04", "surface2": "#221706", "border": "#3d2a0c",
        "text": "#ffe2b0", "dim": "#a8824a", "accent": "#ffb000",
        "cpu": "#ffb000", "mem": "#ff7a00", "disk": "#ffd27a", "net": "#ffcc33",
        "gpu": "#ff9440", "power": "#fff1a8", "warn": "#ffcc33", "crit": "#ff4a1c",
        "heat": "#ffb000",
    },
    "Hell": {
        "dark": False,
        "bg": "#eef1f6", "surface": "#ffffff", "surface2": "#f5f7fb", "border": "#d9dee8",
        "text": "#1b2333", "dim": "#6b7488", "accent": "#0a84ff",
        "cpu": "#117dbb", "mem": "#8b12ae", "disk": "#4da60c", "net": "#a74f01",
        "gpu": "#3c5ad6", "power": "#c28a00", "warn": "#e08a00", "crit": "#d92045",
        "heat": "#ff9d00",
    },
}

DEFAULT = "Neon"
_current = dict(PALETTES[DEFAULT])
_current["name"] = DEFAULT
_provider = None
_listeners = []


def name():
    return _current["name"]


def is_dark():
    return _current["dark"]


def hex_(key):
    return _current.get(key, _current["accent"])


def rgb(key):
    """Farbe als (r, g, b) mit Werten 0..1. key kann auch ein Tupel sein."""
    if isinstance(key, tuple):
        return key
    h = hex_(key).lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def level_color(percent, base):
    """Grundfarbe, ab 80 % Warnfarbe, ab 92 % kritisch."""
    if percent >= 92:
        return "crit"
    if percent >= 80:
        return "warn"
    return base


def on_change(callback):
    _listeners.append(callback)


CSS = """
@define-color tm_bg {bg};
@define-color tm_surface {surface};
@define-color tm_surface2 {surface2};
@define-color tm_border {border};
@define-color tm_text {text};
@define-color tm_dim {dim};
@define-color tm_accent {accent};

.tm-root, .tm-root > box {{ background-color: @tm_bg; color: @tm_text; }}
.tm-root headerbar {{
    background: @tm_surface; border-bottom: 1px solid @tm_border; box-shadow: none;
    color: @tm_text; min-height: 44px;
}}
.tm-root headerbar .title {{ font-weight: 800; letter-spacing: 3px; color: @tm_accent; }}
.tm-root headerbar .subtitle {{ color: @tm_dim; font-feature-settings: "tnum"; }}

.tm-sidebar {{ background-color: @tm_surface; border-right: 1px solid @tm_border; }}
.tm-sidebar list, .tm-sidebar row {{ background: transparent; }}
.tm-sidebar row {{
    color: @tm_dim; padding: 7px 14px; margin: 1px 8px; border-radius: 10px;
    transition: all 120ms ease-in-out;
}}
.tm-sidebar row:hover {{ background-color: alpha(@tm_accent, 0.07); color: @tm_text; }}
.tm-sidebar row:selected {{
    background-color: alpha(@tm_accent, 0.16); color: @tm_accent;
    box-shadow: inset 3px 0 0 @tm_accent;
}}
.tm-sidebar .tm-brand {{ color: @tm_accent; font-weight: 900; letter-spacing: 1px; font-size: 12pt; }}
.tm-sidebar .tm-brand-sub {{ color: @tm_dim; font-size: 8pt; letter-spacing: 2px; }}

.tm-page {{ background-color: @tm_bg; }}
.tm-card {{
    background-color: @tm_surface; border: 1px solid @tm_border; border-radius: 14px;
    padding: 14px 16px;
}}
.tm-card-title {{ color: @tm_dim; font-weight: 700; letter-spacing: 2px; font-size: 8.5pt; }}
.tm-big {{ font-size: 20pt; font-weight: 800; font-feature-settings: "tnum"; }}
.tm-mid {{ font-size: 12pt; font-weight: 700; font-feature-settings: "tnum"; }}
.tm-dim, .dim-label {{ color: @tm_dim; opacity: 1; }}
.tm-num {{ font-feature-settings: "tnum"; }}
.tm-h1 {{ font-size: 18pt; font-weight: 800; letter-spacing: 1px; }}

.tm-root treeview.view {{
    background-color: @tm_surface; color: @tm_text; font-feature-settings: "tnum";
}}
.tm-root treeview.view:hover {{ background-color: alpha(@tm_accent, 0.05); }}
.tm-root treeview.view:selected, .tm-root treeview.view:selected:focus {{
    background-color: alpha(@tm_accent, 0.28); color: @tm_text;
}}
.tm-root treeview.view header button {{
    background: @tm_surface2; color: @tm_dim; border-color: @tm_border;
    border-style: none none solid none; border-width: 1px; padding: 4px 8px;
}}
.tm-root treeview.view header button:hover {{ color: @tm_accent; }}
.tm-root scrolledwindow {{ border-color: @tm_border; }}
.tm-root scrolledwindow.frame {{ border-radius: 12px; border: 1px solid @tm_border; }}
.tm-root viewport, .tm-root stack {{ background-color: transparent; }}

.tm-root entry {{
    background: @tm_surface2; color: @tm_text; border: 1px solid @tm_border; border-radius: 9px;
    box-shadow: none; min-height: 30px;
}}
.tm-root entry:focus {{ border-color: @tm_accent; }}
.tm-root button {{
    background: @tm_surface2; color: @tm_text; border: 1px solid @tm_border; border-radius: 9px;
    box-shadow: none; text-shadow: none; -gtk-icon-shadow: none;
}}
.tm-root button:hover {{ border-color: @tm_accent; color: @tm_accent; }}
.tm-root button:disabled {{ color: alpha(@tm_dim, 0.6); border-color: alpha(@tm_border, 0.6); }}
.tm-root button.tm-primary {{
    background: alpha(@tm_accent, 0.18); border-color: @tm_accent; color: @tm_accent; font-weight: 700;
}}
.tm-root button.tm-primary:disabled {{ opacity: 0.4; }}
.tm-root button.tm-danger:not(:disabled) {{ border-color: {crit}; color: {crit}; }}
/* Auswahllisten (Dropdowns) */
.tm-root combobox button.combo {{
    background: @tm_surface2; color: @tm_text; border: 1px solid @tm_border; border-radius: 9px;
    min-height: 30px; padding: 2px 10px 2px 12px; box-shadow: none;
}}
.tm-root combobox button.combo:hover {{ border-color: @tm_accent; color: @tm_text; }}
.tm-root combobox button.combo:checked {{
    background: alpha(@tm_accent, 0.14); border-color: @tm_accent; color: @tm_text; font-weight: normal;
}}
.tm-root combobox button.combo:disabled {{ color: alpha(@tm_dim, 0.6); border-color: alpha(@tm_border, 0.6); }}
.tm-root combobox arrow {{ color: @tm_accent; min-width: 16px; min-height: 16px; }}

/* Aufklappmenüs, Kontextmenüs, Dropdown-Listen (eigene Fenster – daher ohne .tm-root) */
menu, .menu, .context-menu {{
    background-color: @tm_surface; color: @tm_text; border: 1px solid @tm_accent;
    padding: 5px; font: inherit;
}}
.csd menu, menu.csd {{ border-radius: 10px; }}
window.popup {{ background-color: transparent; }}
menu menuitem {{
    padding: 7px 16px; min-height: 18px; border-radius: 7px; color: @tm_text; text-shadow: none;
}}
menu menuitem:hover {{ background-color: alpha(@tm_accent, 0.18); color: @tm_accent; }}
menu menuitem:disabled, menu menuitem:disabled label {{ color: alpha(@tm_dim, 0.7); }}
menu menuitem accelerator {{ color: @tm_dim; }}
menu menuitem:hover accelerator {{ color: alpha(@tm_accent, 0.8); }}
menu menuitem check, menu menuitem radio {{
    background: @tm_surface2; border: 1px solid @tm_border; color: @tm_accent; box-shadow: none;
}}
menu menuitem check:checked, menu menuitem radio:checked {{
    background: alpha(@tm_accent, 0.2); border-color: @tm_accent; color: @tm_accent;
}}
menu menuitem arrow {{ color: @tm_dim; }}
menu separator {{ background-color: @tm_border; min-height: 1px; margin: 4px 8px; }}
menu > arrow {{ background: @tm_surface; color: @tm_accent; border: none; }}
popover, popover.background {{
    background-color: @tm_surface; color: @tm_text; border: 1px solid @tm_accent; border-radius: 12px;
}}
popover checkbutton, popover label {{ color: @tm_text; }}
.tm-root checkbutton {{ color: @tm_text; }}
.tm-root paned > separator {{ background: @tm_border; min-width: 1px; }}
.tm-root progressbar trough {{ background: @tm_surface2; border-radius: 6px; min-height: 6px; }}
.tm-root progressbar progress {{ background: @tm_accent; border-radius: 6px; min-height: 6px; }}
.tm-root tooltip, tooltip {{ border-radius: 8px; }}

.tm-devlist {{ background-color: @tm_surface; border-right: 1px solid @tm_border; }}
.tm-devlist row {{ background: transparent; margin: 3px 8px; border-radius: 12px; padding: 2px; }}
.tm-devlist row:hover {{ background-color: alpha(@tm_accent, 0.06); }}
.tm-devlist row:selected {{ background-color: alpha(@tm_accent, 0.14); box-shadow: inset 0 0 0 1px alpha(@tm_accent, 0.6); }}
.tm-devlist row:selected label {{ color: @tm_text; }}
.tm-devlist row:selected label.dim-label {{ color: @tm_dim; }}
.tm-root button:checked {{
    background: alpha(@tm_accent, 0.22); border-color: @tm_accent; color: @tm_accent; font-weight: 700;
}}
.tm-root .linked > button {{ border-radius: 0; }}
.tm-root .linked > button:first-child {{ border-radius: 9px 0 0 9px; }}
.tm-root .linked > button:last-child {{ border-radius: 0 9px 9px 0; }}
.tm-root button.tm-rec {{
    background: alpha({crit}, 0.15); color: {crit}; border: 1px solid alpha({crit}, 0.6);
    border-radius: 20px; padding: 0 10px; font-weight: 800; font-size: 8.5pt; min-height: 22px;
}}
.tm-mini {{ background-color: alpha(@tm_bg, 0.94); border: 1px solid @tm_accent; border-radius: 12px; }}
.tm-mini label {{ color: @tm_text; font-feature-settings: "tnum"; }}
.tm-chip {{
    background: alpha(@tm_accent, 0.12); color: @tm_accent; border-radius: 20px; padding: 2px 10px;
    font-size: 8.5pt; font-weight: 700;
}}
"""


def apply(theme_name):
    global _provider
    if theme_name not in PALETTES:
        theme_name = DEFAULT
    _current.clear()
    _current.update(PALETTES[theme_name])
    _current["name"] = theme_name
    settings = Gtk.Settings.get_default()
    if settings is not None:
        settings.set_property("gtk-application-prefer-dark-theme", _current["dark"])
    css = CSS.format(**{k: v for k, v in _current.items() if isinstance(v, str)})
    screen = Gdk.Screen.get_default()
    if _provider is None:
        _provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_screen(screen, _provider,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    try:
        _provider.load_from_data(css.encode())
    except Exception as e:  # CSS-Fehler dürfen den Start nie verhindern
        print("Farbschema konnte nicht vollständig geladen werden:", e)
    for cb in list(_listeners):
        cb()
