"""CPU-Benchmark und Belastungstest.

Jeder Test läuft eine feste Zeit in eigenen Prozessen (multiprocessing,
Startmethode „spawn“ – sicher neben GTK-Threads). Gezählt werden
Durchläufe pro Sekunde; daraus ergibt sich ein Punktwert relativ zur
Referenz (Intel Core i5-4300M, ein Kern = 1000 Punkte je Test).

Single-Core: ein Prozess. Multi-Core: ein Prozess je logischem Prozessor,
alle gleichzeitig; die Durchläufe werden addiert.
"""

import hashlib
import json
import math
import multiprocessing as mp
import os
import random
import threading
import time
import zlib

from .settings import DATA_DIR

HISTORY_PATH = os.path.join(DATA_DIR, "benchmarks.json")

# (Schlüssel, Name, Beschreibung, Referenz-Durchläufe/s auf einem Kern des i5-4300M)
TESTS = [
    ("int", "Ganzzahl", "Primzahlsieb bis 15.000 (Python-Interpreter, Sprünge, Ganzzahlen)", 400.0),
    ("float", "Gleitkomma", "Mandelbrot-Menge 48×48 (Gleitkomma, Schleifen)", 105.0),
    ("hash", "Kryptografie", "SHA-256 über 1 MB (nativer Code, ALU)", 375.0),
    ("zip", "Kompression", "zlib Stufe 6 über 256 KB Text (Verzweigungen, Cache)", 66.0),
    ("sort", "Sortieren", "100.000 Ganzzahlen sortieren (Speicher, Vergleiche)", 44.0),
]
REFERENCE = {}  # wird unten aus TESTS befüllt

MODES = [("Schnell", 1.5), ("Standard", 3.0), ("Gründlich", 6.0)]

# ---------------------------------------------------------------- Arbeit
_stop = None
_data = {}


def _init(stop_event):
    global _stop
    _stop = stop_event
    try:
        os.nice(5)  # Oberfläche bleibt bedienbar
    except OSError:
        pass


def _setup():
    if _data:
        return
    rnd = random.Random(42)
    _data["buf"] = bytes(rnd.getrandbits(8) for _ in range(1 << 20))
    words = ["prozess", "speicher", "kern", "linux", "mint", "takt", "daten", "netz", "task", "manager"]
    _data["text"] = " ".join(rnd.choice(words) + str(rnd.randint(0, 999)) for _ in range(40000)).encode()[:262144]
    _data["ints"] = [rnd.randint(0, 1 << 30) for _ in range(100000)]


def _w_int():
    n = 15000
    sieve = bytearray([1]) * (n + 1)
    sieve[0] = sieve[1] = 0
    i = 2
    while i * i <= n:
        if sieve[i]:
            j = i * i
            while j <= n:
                sieve[j] = 0
                j += i
        i += 1
    c = 0
    for v in sieve:
        c += v
    return c


def _w_float():
    size, it_max = 48, 64
    total = 0
    for py in range(size):
        ci = py / size * 2.4 - 1.2
        for px in range(size):
            cr = px / size * 3.2 - 2.2
            zr = zi = 0.0
            k = 0
            while k < it_max and zr * zr + zi * zi < 4.0:
                zr, zi = zr * zr - zi * zi + cr, 2.0 * zr * zi + ci
                k += 1
            total += k
    return total


def _w_hash():
    return hashlib.sha256(_data["buf"]).digest()


def _w_zip():
    return len(zlib.compress(_data["text"], 6))


def _w_sort():
    return sorted(_data["ints"])[0]


WORK = {"int": _w_int, "float": _w_float, "hash": _w_hash, "zip": _w_zip, "sort": _w_sort}


def run_test(key, duration, start_at=0.0):
    """Führt einen Test für `duration` Sekunden aus → (Durchläufe, Sekunden)."""
    _setup()
    fn = WORK[key]
    fn()  # Aufwärmen
    # alle Prozesse gleichzeitig starten lassen
    while time.time() < start_at:
        time.sleep(0.001)
    count = 0
    t0 = time.perf_counter()
    end = t0 + duration
    while True:
        fn()
        count += 1
        now = time.perf_counter()
        if now >= end or (_stop is not None and _stop.is_set()):
            break
    return count, now - t0


def stress_worker(_):
    """Dauerlast bis zum Stopp-Signal (Mischung aller Tests)."""
    _setup()
    fns = list(WORK.values())
    i = 0
    while not _stop.is_set():
        fns[i % len(fns)]()
        i += 1
    return i


def _noop(_):
    _setup()
    return os.getpid()


# ---------------------------------------------------------------- Ablauf

def score(ops_per_s, key):
    return ops_per_s / REFERENCE[key] * 1000.0


def geomean(values):
    values = [v for v in values if v > 0]
    if not values:
        return 0.0
    return math.exp(sum(math.log(v) for v in values) / len(values))


class BenchmarkRun(threading.Thread):
    """Führt den Benchmark im Hintergrund aus und meldet über Callbacks.

    Callbacks werden aus diesem Thread aufgerufen – der Aufrufer muss sie
    per GLib.idle_add in den GTK-Hauptthread bringen.
    """

    def __init__(self, duration, on_progress, on_score, on_done, threads=None):
        super().__init__(daemon=True, name="benchmark")
        self.duration = duration
        self.on_progress = on_progress
        self.on_score = on_score
        self.on_done = on_done
        self.threads = threads or os.cpu_count() or 1
        self.ctx = mp.get_context("spawn")
        self.stop_event = self.ctx.Event()

    def cancel(self):
        self.stop_event.set()

    def run(self):
        result = {"single": {}, "multi": {}, "threads": self.threads, "duration": self.duration}
        steps = len(TESTS) * 2
        step = 0
        try:
            for mode, n in (("single", 1), ("multi", self.threads)):
                self.on_progress(f"Starte {n} Prozess(e)…", step / steps, mode, None)
                with self.ctx.Pool(n, initializer=_init, initargs=(self.stop_event,)) as pool:
                    pool.map(_noop, range(n))  # Prozesse hochfahren, Testdaten anlegen
                    for key, name, desc, ref in TESTS:
                        if self.stop_event.is_set():
                            raise InterruptedError
                        label = ("Single-Core" if mode == "single" else f"Multi-Core ({n} Threads)")
                        self.on_progress(f"{label}: {name}", step / steps, mode, key)
                        start_at = time.time() + 0.15
                        res = pool.starmap(run_test, [(key, self.duration, start_at)] * n)
                        ops = sum(c / e for c, e in res if e > 0)
                        sc = score(ops, key)
                        result[mode][key] = sc
                        self.on_score(mode, key, sc)
                        step += 1
                if self.stop_event.is_set():
                    raise InterruptedError
            result["single_total"] = geomean(result["single"].values())
            result["multi_total"] = geomean(result["multi"].values())
            self.on_progress("Fertig", 1.0, None, None)
            self.on_done(result, None)
        except InterruptedError:
            self.on_done(None, "abgebrochen")
        except Exception as e:  # z. B. Prozessstart fehlgeschlagen
            self.on_done(None, str(e))


class StressRun(threading.Thread):
    def __init__(self, on_done, threads=None):
        super().__init__(daemon=True, name="stress")
        self.threads = threads or os.cpu_count() or 1
        self.ctx = mp.get_context("spawn")
        self.stop_event = self.ctx.Event()
        self.on_done = on_done

    def cancel(self):
        self.stop_event.set()

    def run(self):
        try:
            with self.ctx.Pool(self.threads, initializer=_init, initargs=(self.stop_event,)) as pool:
                pool.map(stress_worker, range(self.threads))
            self.on_done(None)
        except Exception as e:
            self.on_done(str(e))


# ---------------------------------------------------------------- Verlauf

def load_history():
    try:
        with open(HISTORY_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def save_history(entries):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = HISTORY_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(entries, f, indent=1)
    os.replace(tmp, HISTORY_PATH)


for _k, _n, _d, _r in TESTS:
    REFERENCE[_k] = _r
