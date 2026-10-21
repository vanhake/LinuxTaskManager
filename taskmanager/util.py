"""Formatierungshilfen mit deutschem Zahlenformat."""

import time

_TRANS = str.maketrans({",": ".", ".": ","})


def num(value, decimals=1):
    """Zahl mit Tausenderpunkt und Dezimalkomma."""
    return f"{value:,.{decimals}f}".translate(_TRANS)


def pct(value, decimals=0):
    return f"{num(value, decimals)} %"


_UNITS = ["Bytes", "KB", "MB", "GB", "TB", "PB"]


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
        return f"{int(n)} Bytes"
    return f"{num(n, decimals)} {_UNITS[i]}"


def mb(n):
    """Speicher immer in MB wie in der Windows-Prozessliste."""
    if n is None:
        return "–"
    return f"{num(n / 1048576, 1)} MB"


def mb_rate(n):
    if n is None:
        return "–"
    return f"{num(n / 1048576, 1)} MB/s"


def rate(n):
    if n is None:
        return "–"
    return size(n) + "/s"


def bits(n_bytes_per_s):
    """Netzwerkrate in Bit/s wie Windows (Kbit/s, Mbit/s, Gbit/s)."""
    b = n_bytes_per_s * 8
    if b >= 1e9:
        return f"{num(b / 1e9, 1)} Gbit/s"
    if b >= 1e6:
        return f"{num(b / 1e6, 1)} Mbit/s"
    return f"{num(b / 1e3, 0)} Kbit/s"


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
    return time.strftime("%d.%m.%Y %H:%M:%S", time.localtime(ts))


def ghz(mhz):
    if not mhz:
        return "–"
    return f"{num(mhz / 1000, 2)} GHz"


def read_file(path, default=None):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


STATUS_DE = {
    "running": "Wird ausgeführt",
    "sleeping": "Schlafend",
    "disk-sleep": "Wartet (E/A)",
    "stopped": "Angehalten",
    "tracing-stop": "Angehalten (Debug)",
    "zombie": "Zombie",
    "dead": "Beendet",
    "idle": "Leerlauf",
    "parked": "Geparkt",
    "waking": "Wird aktiviert",
}


def status_de(status):
    return STATUS_DE.get(status, status or "")


def status_short(status):
    """Statusspalte im Prozesse-Tab: nur Auffälliges anzeigen (wie Windows)."""
    if status in ("stopped", "tracing-stop"):
        return "Angehalten"
    if status == "zombie":
        return "Zombie"
    return ""


def uptime_text(seconds):
    seconds = int(seconds)
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    return (f"{d} T " if d else "") + f"{h} h {m:02d} min"
