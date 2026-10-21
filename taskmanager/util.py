"""Formatierungshilfen; Zahlen- und Datumsformat je nach Sprache (de/en)."""

import time

from . import i18n
from .i18n import _

_TRANS = str.maketrans({",": ".", ".": ","})


def num(value, decimals=1):
    """Zahl mit Tausendertrennzeichen: de 1.234,5 – en 1,234.5"""
    text = f"{value:,.{decimals}f}"
    return text if i18n.is_en() else text.translate(_TRANS)


def pct(value, decimals=0):
    return f"{num(value, decimals)}%" if i18n.is_en() else f"{num(value, decimals)} %"


def date_fmt(kind="full"):
    """strftime-Formate: full = Datum+Uhrzeit, day = Tag+Monat (kurz)."""
    if i18n.is_en():
        return {"full": "%Y-%m-%d %H:%M:%S", "day": "%m/%d", "date": "%Y-%m-%d"}[kind]
    return {"full": "%d.%m.%Y %H:%M:%S", "day": "%d.%m.", "date": "%d.%m.%Y"}[kind]


_UNITS = [_("Bytes"), _("KB"), _("MB"), _("GB"), _("TB"), _("PB")]


def size(n, decimals=1):
    """Bytes in passender Einheit (1024er-Basis wie Windows)."""
    if n is None:
        return "–"
    n = float(n)
    i = 0
    while abs(n) >= 1024 and i < len(_UNITS) - 1:
        n /= 1024
        i += 1
    if i == 0:
        return _('{0} Bytes').format(int(n))
    return f"{num(n, decimals)} {_UNITS[i]}"


def mb(n):
    """Speicher immer in MB wie in der Windows-Prozessliste."""
    if n is None:
        return "–"
    return _('{0} MB').format(num(n / 1048576, 1))


def mb_rate(n):
    if n is None:
        return "–"
    return _('{0} MB/s').format(num(n / 1048576, 1))


def rate(n):
    if n is None:
        return "–"
    return size(n) + "/s"


def bits(n_bytes_per_s):
    """Netzwerkrate in Bit/s wie Windows (Kbit/s, Mbit/s, Gbit/s)."""
    b = n_bytes_per_s * 8
    if b >= 1e9:
        return _('{0} Gbit/s').format(num(b / 1e9, 1))
    if b >= 1e6:
        return _('{0} Mbit/s').format(num(b / 1e6, 1))
    return _('{0} Kbit/s').format(num(b / 1e3, 0))


def duration(seconds):
    """Dauer als T:HH:MM:SS."""
    seconds = int(seconds)
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    return f"{d}:{h:02d}:{m:02d}:{s:02d}"


def cpu_time(seconds):
    """CPU-Zeit als H:MM:SS."""
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"


def datetime(ts):
    if not ts:
        return "–"
    return time.strftime(date_fmt("full"), time.localtime(ts))


def ghz(mhz):
    if not mhz:
        return "–"
    return _('{0} GHz').format(num(mhz / 1000, 2))


def read_file(path, default=None):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


STATUS_DE = {
    "running": _("Wird ausgeführt"),
    "sleeping": _("Schlafend"),
    "disk-sleep": _("Wartet (E/A)"),
    "stopped": _("Angehalten"),
    "tracing-stop": _("Angehalten (Debug)"),
    "zombie": _("Zombie"),
    "dead": _("Beendet"),
    "idle": _("Leerlauf"),
    "parked": _("Geparkt"),
    "waking": _("Wird aktiviert"),
}


def status_de(status):
    return STATUS_DE.get(status, status or "")


def status_short(status):
    """Statusspalte im Prozesse-Tab: nur Auffälliges anzeigen (wie Windows)."""
    if status in ("stopped", "tracing-stop"):
        return _("Angehalten")
    if status == "zombie":
        return _("Zombie")
    return ""


def uptime_text(seconds):
    seconds = int(seconds)
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    return (_("{0} T ").format(d) if d else "") + _('{0} h {1:02d} min').format(h, m)
