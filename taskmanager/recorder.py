"""Flight Recorder: zeichnet Systemzustand und Top-Prozesse in SQLite auf.

- Systemwerte bei jeder Messung, Top-Prozesse (gemittelt) alle 5 Sekunden
- erkennt Ereignisse (CPU-Spitzen, Speicher knapp, Hitze, Netzteil …)
- nur ein Prozess schreibt (Dateisperre); andere lesen nur. So können die
  Oberfläche und der Hintergrunddienst (--recorder) gleichzeitig laufen.
- Schreiben in eigenem Thread, gebündelt; Lesen über eigene Verbindung.
"""

import fcntl
import os
import queue
import sqlite3
import threading
import time

from .settings import DATA_DIR

DB_PATH = os.path.join(DATA_DIR, "flight.db")
LOCK_PATH = os.path.join(DATA_DIR, "recorder.lock")
PROC_EVERY = 5.0  # Sekunden zwischen Prozess-Schnappschüssen
TOP_N = 10

SCHEMA = """
CREATE TABLE IF NOT EXISTS samples (
    ts REAL PRIMARY KEY, cpu REAL, mem REAL, swap REAL, disk_r REAL, disk_w REAL, disk_act REAL,
    net_rx REAL, net_tx REAL, gpu REAL, temp REAL, bat REAL, watts REAL, procs INTEGER,
    load1 REAL, freq REAL, mem_used REAL
);
CREATE TABLE IF NOT EXISTS procs (
    ts REAL, pid INTEGER, name TEXT, user TEXT, cpu REAL, mem REAL, io REAL, cmd TEXT
);
CREATE INDEX IF NOT EXISTS procs_ts ON procs(ts);
CREATE TABLE IF NOT EXISTS events (
    ts REAL, level TEXT, kind TEXT, text TEXT
);
CREATE INDEX IF NOT EXISTS events_ts ON events(ts);
"""

SAMPLE_COLS = ["ts", "cpu", "mem", "swap", "disk_r", "disk_w", "disk_act", "net_rx", "net_tx",
               "gpu", "temp", "bat", "watts", "procs", "load1", "freq", "mem_used"]

RETENTIONS = [("1 Stunde", 1), ("6 Stunden", 6), ("24 Stunden", 24), ("3 Tage", 72), ("7 Tage", 168)]


def connect():
    os.makedirs(DATA_DIR, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.executescript(SCHEMA)
    return con


class _Writer(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True, name="flight-writer")
        self.q = queue.Queue()

    def run(self):
        con = connect()
        last_commit = time.monotonic()
        pending = False
        while True:
            try:
                item = self.q.get(timeout=1.0)
            except queue.Empty:
                item = None
            if item is not None:
                kind, data = item
                if kind == "stop":
                    con.commit()
                    con.close()
                    return
                if kind == "s":
                    con.execute(f"INSERT OR REPLACE INTO samples VALUES ({','.join('?' * len(SAMPLE_COLS))})", data)
                elif kind == "p":
                    con.executemany("INSERT INTO procs VALUES (?,?,?,?,?,?,?,?)", data)
                elif kind == "e":
                    con.execute("INSERT INTO events VALUES (?,?,?,?)", data)
                elif kind == "purge":
                    for t in ("samples", "procs", "events"):
                        con.execute(f"DELETE FROM {t} WHERE ts < ?", (data,))
                elif kind == "clear":
                    for t in ("samples", "procs", "events"):
                        con.execute(f"DELETE FROM {t}")
                    con.commit()
                    con.execute("VACUUM")
                pending = True
            if pending and time.monotonic() - last_commit > 2.0:
                con.commit()
                last_commit = time.monotonic()
                pending = False


class Recorder:
    def __init__(self, settings, role="gui"):
        self.settings = settings
        self.role = role
        self.active = False  # besitzt die Schreibsperre
        self._lock_fd = None
        self._last_try = 0
        self._writer = None
        self._acc = {}  # pid -> [cpu_sum, n, mem, io_sum, name, user, cmd]
        self._acc_n = 0
        self._last_proc = 0
        self._last_purge = 0
        self._state = {}
        self.try_acquire()

    # ------------------------------------------------------------ Sperre
    def try_acquire(self):
        self._last_try = time.monotonic()
        if self.active:
            return True
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            fd = os.open(LOCK_PATH, os.O_RDWR | os.O_CREAT, 0o644)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            try:
                os.close(fd)
            except Exception:
                pass
            return False
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()} {self.role}\n".encode())
        self._lock_fd = fd
        self.active = True
        self._writer = _Writer()
        self._writer.start()
        self.event("info", "start", "Aufzeichnung gestartet" +
                   (" (Hintergrunddienst)" if self.role == "daemon" else ""))
        return True

    def holder(self):
        """Wer zeichnet gerade auf? ('gui'/'daemon', pid) oder None."""
        try:
            with open(LOCK_PATH) as f:
                pid, role = f.read().split()[:2]
            if self.active:
                return role, int(pid)
            fd = os.open(LOCK_PATH, os.O_RDWR)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(fd, fcntl.LOCK_UN)
                return None  # niemand hält die Sperre
            except OSError:
                return role, int(pid)
            finally:
                os.close(fd)
        except (OSError, ValueError):
            return None

    def close(self):
        if self.active:
            self.event("info", "stop", "Aufzeichnung beendet")
            self._writer.q.put(("stop", None))
            self._writer.join(timeout=5)
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
                os.close(self._lock_fd)
            except OSError:
                pass
            self.active = False

    @property
    def enabled(self):
        return self.settings.get("fr_enabled", True)

    # -------------------------------------------------------- Aufzeichnen
    def event(self, level, kind, text, ts=None):
        if self.active:
            self._writer.q.put(("e", (ts or time.time(), level, kind, text)))

    def clear(self):
        if self.active:
            self._writer.q.put(("clear", None))
            self.event("info", "clear", "Aufzeichnung gelöscht")

    def add(self, s):
        if not self.active:
            if time.monotonic() - self._last_try > 30:
                self.try_acquire()
            if not self.active:
                return
        if not self.enabled:
            return
        gpu = next((g.get("usage") for g in s.gpus.values() if g.get("usage") is not None), None) \
            if s.gpus else None
        b = s.battery
        disk_r = sum(d["read"] for d in s.disks.values())
        disk_w = sum(d["write"] for d in s.disks.values())
        disk_act = max((d["active"] for d in s.disks.values()), default=0)
        rx = sum(d["recv"] for d in s.net.values())
        tx = sum(d["sent"] for d in s.net.values())
        row = (s.time, s.cpu, s.vm.percent, s.swap.percent, disk_r, disk_w, disk_act, rx, tx, gpu,
               s.cpu_temp, b["percent"] if b else None, b["watts"] if b else None, len(s.procs),
               s.loadavg[0], s.cpu_freq, s.vm.total - s.vm.available)
        self._writer.q.put(("s", row))

        # Prozesse über das Fenster mitteln
        acc = self._acc
        for p in s.procs.values():
            if p.pid == 2 or p.ppid == 2:
                continue
            a = acc.get(p.pid)
            io = (p.read_rate or 0) + (p.write_rate or 0)
            if a is None:
                acc[p.pid] = [p.cpu, 1, p.mem, io, p.name, p.user, p.cmdline[:300]]
            else:
                a[0] += p.cpu
                a[1] += 1
                a[2] = p.mem
                a[3] += io
        self._acc_n += 1
        if s.time - self._last_proc >= PROC_EVERY:
            self._last_proc = s.time
            n = max(1, self._acc_n)
            items = [(pid, a[0] / n, a[2], a[3] / n, a) for pid, a in acc.items()]
            pick = {}
            for key in (1, 2, 3):
                for it in sorted(items, key=lambda x: x[key], reverse=True)[:TOP_N]:
                    pick[it[0]] = it
            rows = [(s.time, pid, a[4], a[5], cpu, mem, io, a[6]) for pid, cpu, mem, io, a in pick.values()]
            self._writer.q.put(("p", rows))
            self._detect_slow(s, items)
            self._acc = {}
            self._acc_n = 0

        self._detect(s, disk_act, b)

        if time.monotonic() - self._last_purge > 600:
            self._last_purge = time.monotonic()
            hours = self.settings.get("fr_retention_h", 24)
            self._writer.q.put(("purge", time.time() - hours * 3600))

    # ------------------------------------------------------ Ereignisse
    def _flag(self, key, condition, reset_condition, level, text_fn, ts):
        """Löst ein Ereignis einmal aus, bis reset_condition wieder erfüllt ist."""
        st = self._state
        if condition and not st.get(key):
            st[key] = True
            self.event(level, key, text_fn(), ts)
        elif reset_condition and st.get(key):
            st[key] = False

    def _streak(self, key, cond):
        st = self._state
        st[key] = st.get(key, 0) + 1 if cond else 0
        return st[key]

    def _top_cpu_name(self, s):
        top = max(s.procs.values(), key=lambda p: p.cpu, default=None)
        return f"{top.name} ({top.cpu:.0f} %)".replace(".", ",") if top else "?"

    def _detect(self, s, disk_act, b):
        ts = s.time
        hot_cpu = self._streak("cpu_n", s.cpu >= 90) >= 5
        self._flag("cpu_high", hot_cpu, s.cpu < 60, "crit",
                   lambda: f"CPU-Spitze: {s.cpu:.0f} % – größter Verbraucher: {self._top_cpu_name(s)}", ts)
        self._flag("mem_high", s.vm.percent >= 90, s.vm.percent < 80, "crit",
                   lambda: f"Arbeitsspeicher knapp: {s.vm.percent:.0f} % belegt", ts)
        if s.cpu_temp is not None:
            self._flag("temp_high", s.cpu_temp >= 85, s.cpu_temp < 75, "warn",
                       lambda: f"Hohe CPU-Temperatur: {s.cpu_temp:.0f} °C", ts)
        busy = self._streak("disk_n", disk_act >= 95) >= 5
        self._flag("disk_busy", busy, disk_act < 50, "warn",
                   lambda: f"Datenträger ausgelastet ({disk_act:.0f} % aktiv)", ts)
        # Swap-Wachstum
        sw_prev = self._state.get("swap_ref")
        now_sw = s.swap.used
        if sw_prev is None or ts - sw_prev[0] > 60:
            if sw_prev is not None and now_sw - sw_prev[1] > 256 * 1048576:
                self.event("warn", "swap", f"Starke Auslagerung: +{(now_sw - sw_prev[1]) / 1048576:.0f} MB "
                                           "Swap in einer Minute", ts)
            self._state["swap_ref"] = (ts, now_sw)
        # Netzteil
        if b and b["ac"] is not None:
            prev = self._state.get("ac")
            if prev is not None and prev != b["ac"]:
                self.event("info", "power", "Netzteil verbunden" if b["ac"] else
                           f"Netzteil getrennt – Akku {b['percent']} %", ts)
            self._state["ac"] = b["ac"]
            self._flag("bat_low", b["percent"] <= 15 and not b["ac"], b["percent"] > 20 or b["ac"], "crit",
                       lambda: f"Akku fast leer: {b['percent']} %", ts)
        # Laufwerke
        for m in s.mounts:
            self._flag(f"full:{m['mount']}", m["percent"] >= 95, m["percent"] < 93, "crit",
                       lambda m=m: f"Laufwerk {m['mount']} fast voll: {m['percent']:.0f} %", ts)

    def _detect_slow(self, s, items):
        """Prozessbezogene Ereignisse (alle 5 s): neue Dauerlast-Prozesse."""
        hogs = self._state.setdefault("hogs", set())
        current = set()
        for pid, cpu, mem, io, a in items:
            if cpu >= 50:
                current.add(pid)
                if pid not in hogs:
                    self.event("warn", "hog", f"{a[4]} (PID {pid}) erzeugt hohe Last: "
                                              f"{cpu:.0f} % CPU".replace(".", ","), s.time)
        self._state["hogs"] = current


# ------------------------------------------------------------------- Lesen

class Reader:
    """Lesezugriff für die Oberfläche (eigene Verbindung im Hauptthread)."""

    def __init__(self):
        self.con = connect()

    def bounds(self):
        r = self.con.execute("SELECT MIN(ts), MAX(ts), COUNT(*) FROM samples").fetchone()
        return r if r and r[0] is not None else (None, None, 0)

    def buckets(self, t0, t1, n):
        """Je Zeitabschnitt die Spitzenwerte – Lücken bleiben None."""
        bw = max(1e-6, (t1 - t0) / n)
        rows = self.con.execute(
            "SELECT CAST((ts - ?) / ? AS INTEGER) AS b, MAX(cpu), MAX(mem), MAX(disk_r + disk_w), "
            "MAX(net_rx + net_tx), MAX(gpu), MAX(temp), MAX(swap) FROM samples "
            "WHERE ts >= ? AND ts < ? GROUP BY b", (t0, bw, t0, t1)).fetchall()
        keys = ["cpu", "mem", "disk", "net", "gpu", "temp", "swap"]
        data = {k: [None] * n for k in keys}
        for row in rows:
            b = row[0]
            if 0 <= b < n:
                for k, v in zip(keys, row[1:]):
                    data[k][b] = v
        return data

    def sample_at(self, ts, tolerance=10):
        r = self.con.execute(f"SELECT {','.join(SAMPLE_COLS)} FROM samples WHERE ts <= ? AND ts >= ? "
                             "ORDER BY ts DESC LIMIT 1", (ts, ts - tolerance)).fetchone()
        return dict(zip(SAMPLE_COLS, r)) if r else None

    def procs_at(self, ts, tolerance=12):
        r = self.con.execute("SELECT MAX(ts) FROM procs WHERE ts <= ? AND ts >= ?",
                             (ts + 2.5, ts - tolerance)).fetchone()
        if not r or r[0] is None:
            return None, []
        rows = self.con.execute("SELECT pid, name, user, cpu, mem, io, cmd FROM procs WHERE ts = ? "
                                "ORDER BY cpu DESC", (r[0],)).fetchall()
        return r[0], rows

    def events(self, t0, t1):
        return self.con.execute("SELECT ts, level, kind, text FROM events WHERE ts >= ? AND ts <= ? "
                                "ORDER BY ts", (t0, t1)).fetchall()

    def adjacent_event(self, ts, forward):
        if forward:
            r = self.con.execute("SELECT ts FROM events WHERE ts > ? + 0.5 AND kind NOT IN ('start','stop') "
                                 "ORDER BY ts LIMIT 1", (ts,)).fetchone()
        else:
            r = self.con.execute("SELECT ts FROM events WHERE ts < ? - 0.5 AND kind NOT IN ('start','stop') "
                                 "ORDER BY ts DESC LIMIT 1", (ts,)).fetchone()
        return r[0] if r else None

    def export_csv(self, path, t0, t1):
        import csv
        with open(path, "w", newline="") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["Zeit"] + SAMPLE_COLS[1:])
            for r in self.con.execute(f"SELECT {','.join(SAMPLE_COLS)} FROM samples WHERE ts >= ? AND ts <= ? "
                                      "ORDER BY ts", (t0, t1)):
                w.writerow([time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r[0]))] +
                           ["" if v is None else str(round(v, 3)).replace(".", ",") for v in r[1:]])

    @staticmethod
    def db_size():
        total = 0
        for suffix in ("", "-wal", "-shm"):
            try:
                total += os.path.getsize(DB_PATH + suffix)
            except OSError:
                pass
        return total


# ------------------------------------------------------- Hintergrunddienst

def run_daemon():
    """Kopflose Aufzeichnung ohne Fenster (python3 -m taskmanager --recorder)."""
    import signal

    from gi.repository import GLib

    from .sampler import Sampler
    from .settings import Settings

    settings = Settings()
    rec = Recorder(settings, role="daemon")
    if not rec.active:
        print("Flight Recorder: Es zeichnet bereits ein anderer Prozess auf – warte im Hintergrund.")
    loop = GLib.MainLoop()

    def on_snap(snap):
        rec.add(snap)
        return False

    sampler = Sampler(on_snap, settings.get("fr_daemon_interval", 2.0))

    def stop(*_):
        sampler.stop()
        rec.close()
        loop.quit()
        return False

    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, stop)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, stop)
    sampler.start()
    loop.run()
    return 0
