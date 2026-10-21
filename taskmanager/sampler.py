"""Hintergrund-Thread, der periodisch System- und Prozessdaten misst.

Der Thread erzeugt reine Datenobjekte (Snapshot) und übergibt sie per
GLib.idle_add an den GTK-Hauptthread. Er fasst selbst nie GTK an.
"""

import glob
import os
import shutil
import subprocess
import threading
import time

import psutil
from gi.repository import GLib

from . import sysinfo
from .util import read_file

# Unveränderliche Angaben werden je Prozess nur einmal gelesen
STATIC_ATTRS = ["name", "username", "create_time", "cmdline", "exe"]
DYNAMIC_ATTRS = ["ppid", "status", "cpu_times", "memory_info", "num_threads", "nice", "io_counters"]
FDS_EVERY = 3  # Handles (offene Dateien) nur jede 3. Messung zählen – teuer


class Proc:
    __slots__ = (
        "pid", "ppid", "name", "user", "status", "cpu", "cpu_time", "mem", "rss", "vms",
        "threads", "nice", "create_time", "cmdline", "exe", "read_rate", "write_rate",
        "fds", "cpu_delta", "read_delta", "write_delta",
    )


class Snapshot:
    pass


class _Prev:
    __slots__ = ("ctime", "cpu", "rb", "wb")

    def __init__(self, ctime, cpu, rb, wb):
        self.ctime, self.cpu, self.rb, self.wb = ctime, cpu, rb, wb


def _meminfo():
    result = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1)
                parts = v.split()
                result[k] = int(parts[0]) * (1024 if len(parts) > 1 else 1)
    except (OSError, ValueError):
        pass
    return result


def _cpu_freq_mhz():
    # /proc/cpuinfo ist deutlich schneller als scaling_cur_freq je Kern
    vals = []
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("cpu MHz"):
                    vals.append(float(line.split(":", 1)[1]))
    except (OSError, ValueError):
        pass
    if vals:
        return sum(vals) / len(vals)
    f = psutil.cpu_freq()
    return f.current if f else None


SKIP_FS = {"squashfs", "tmpfs", "devtmpfs", "overlay", "iso9660", "udf", "ramfs", "efivarfs"}


def _mounts():
    """Belegung aller echten Dateisysteme (ohne Snaps, tmpfs, Bind-Mounts)."""
    result = []
    seen = set()
    for p in psutil.disk_partitions(all=False):
        if p.fstype in SKIP_FS or p.mountpoint.startswith(("/snap", "/var/snap", "/run/")):
            continue
        if p.device in seen:
            continue
        try:
            u = psutil.disk_usage(p.mountpoint)
        except OSError:
            continue
        if u.total <= 0:
            continue
        seen.add(p.device)
        result.append({"mount": p.mountpoint, "device": p.device, "fstype": p.fstype,
                       "total": u.total, "used": u.used, "free": u.free, "percent": u.percent})
    result.sort(key=lambda m: (m["mount"] != "/", m["mount"]))
    return result


def _battery():
    """Akkustand und aktuelle Leistungsaufnahme (Watt) aus /sys."""
    for bat in sorted(glob.glob("/sys/class/power_supply/BAT*")):
        cap = read_file(os.path.join(bat, "capacity"))
        if cap is None:
            continue
        status = read_file(os.path.join(bat, "status"), "")
        watts = None
        pn = read_file(os.path.join(bat, "power_now"))
        if pn and pn.lstrip("-").isdigit():
            watts = abs(int(pn)) / 1e6
        else:
            cn, vn = read_file(os.path.join(bat, "current_now")), read_file(os.path.join(bat, "voltage_now"))
            if cn and vn and cn.lstrip("-").isdigit() and vn.isdigit():
                watts = abs(int(cn)) * int(vn) / 1e12
        ac = None
        for a in glob.glob("/sys/class/power_supply/A[CD]*/online"):
            ac = read_file(a) == "1"
        secs = None
        try:
            b = psutil.sensors_battery()
            if b and b.secsleft not in (psutil.POWER_TIME_UNLIMITED, psutil.POWER_TIME_UNKNOWN):
                secs = b.secsleft
        except Exception:
            pass
        health = None
        full, design = read_file(os.path.join(bat, "energy_full")), read_file(os.path.join(bat, "energy_full_design"))
        if full and design and full.isdigit() and design.isdigit() and int(design):
            health = int(full) / int(design) * 100
        return {"percent": int(cap), "status": status, "watts": watts, "ac": ac,
                "secs": secs, "health": health, "name": os.path.basename(bat)}
    return None


def _cpu_temp():
    try:
        temps = psutil.sensors_temperatures()
    except (AttributeError, OSError):
        return None
    for chip in ("coretemp", "k10temp", "zenpower", "cpu_thermal", "acpitz"):
        entries = temps.get(chip)
        if not entries:
            continue
        for e in entries:
            if e.label in ("Package id 0", "Tctl", "Tdie"):
                return e.current
        return max(e.current for e in entries)
    return None


class Sampler(threading.Thread):
    def __init__(self, callback, interval=1.0, paused=False):
        super().__init__(daemon=True, name="sampler")
        self.callback = callback
        self.interval = interval
        self.paused = paused
        self._wake = threading.Event()
        self._force = False
        self._stopped = False
        self._prev = {}
        self._static = {}
        self._fds_tick = 0
        self._static_tick = 0
        self._mounts = None
        self._mounts_tick = 0
        self._prev_t = None
        self._prev_disk = {}
        self._prev_net = {}
        self.ncpu = psutil.cpu_count() or 1
        self.disks = sysinfo.physical_disks()
        self.gpus = sysinfo.gpus()
        self._has_nvsmi = bool(shutil.which("nvidia-smi")) and any(
            g["driver"] == "nvidia" for g in self.gpus)
        self._adapter_check = 0
        self.adapters = sysinfo.net_adapters()

    # -- Steuerung aus dem Hauptthread
    def refresh_now(self):
        self._force = True
        self._wake.set()

    def set_interval(self, interval):
        self.interval = interval
        self._wake.set()

    def stop(self):
        self._stopped = True
        self._wake.set()

    def run(self):
        psutil.cpu_percent(percpu=True)
        while not self._stopped:
            if not self.paused or self._force:
                self._force = False
                try:
                    snap = self.sample()
                except Exception as e:  # Messfehler dürfen den Thread nicht beenden
                    print("Sampler-Fehler:", e)
                    snap = None
                if snap is not None:
                    GLib.idle_add(self.callback, snap)
            self._wake.wait(self.interval)
            self._wake.clear()

    # -- Messung
    def sample(self):
        now = time.monotonic()
        dt = (now - self._prev_t) if self._prev_t else None
        first = self._prev_t is None
        self._prev_t = now
        s = Snapshot()
        s.time = time.time()
        s.dt = dt or self.interval

        # CPU
        s.cpu_per_core = psutil.cpu_percent(percpu=True)
        s.cpu = sum(s.cpu_per_core) / max(1, len(s.cpu_per_core))
        s.cpu_freq = _cpu_freq_mhz()
        s.cpu_temp = _cpu_temp()
        s.uptime = time.time() - psutil.boot_time()
        try:
            s.handles = int(read_file("/proc/sys/fs/file-nr", "0").split()[0])
        except (ValueError, IndexError):
            s.handles = 0

        # Speicher
        s.vm = psutil.virtual_memory()
        s.swap = psutil.swap_memory()
        s.meminfo = _meminfo()

        # Datenträger
        s.disks = {}
        try:
            counters = psutil.disk_io_counters(perdisk=True) or {}
        except OSError:
            counters = {}
        for name in self.disks:
            c = counters.get(name)
            if c is None:
                continue
            p = self._prev_disk.get(name)
            d = {"read": 0.0, "write": 0.0, "active": 0.0, "resp": 0.0}
            if p and dt:
                d["read"] = max(0, c.read_bytes - p.read_bytes) / dt
                d["write"] = max(0, c.write_bytes - p.write_bytes) / dt
                busy = getattr(c, "busy_time", 0) - getattr(p, "busy_time", 0)
                d["active"] = min(100.0, max(0.0, busy / (dt * 1000) * 100))
                ops = (c.read_count + c.write_count) - (p.read_count + p.write_count)
                tms = (c.read_time + c.write_time) - (p.read_time + p.write_time)
                d["resp"] = tms / ops if ops > 0 else 0.0
            self._prev_disk[name] = c
            s.disks[name] = d

        # Netzwerk (Adapterliste alle 5 Messungen neu prüfen)
        self._adapter_check += 1
        if self._adapter_check >= 5:
            self._adapter_check = 0
            self.adapters = sysinfo.net_adapters()
        s.net = {}
        try:
            nc = psutil.net_io_counters(pernic=True)
        except OSError:
            nc = {}
        for name in self.adapters:
            c = nc.get(name)
            if c is None:
                continue
            p = self._prev_net.get(name)
            d = {"sent": 0.0, "recv": 0.0}
            if p and dt:
                d["sent"] = max(0, c.bytes_sent - p.bytes_sent) / dt
                d["recv"] = max(0, c.bytes_recv - p.bytes_recv) / dt
            self._prev_net[name] = c
            s.net[name] = d

        # GPU
        s.gpus = self._sample_gpus()

        # Festplattenbelegung (alle 5 Messungen), Akku, Last
        if self._mounts_tick % 5 == 0 or self._mounts is None:
            self._mounts = _mounts()
        self._mounts_tick += 1
        s.mounts = self._mounts
        s.battery = _battery()
        try:
            s.loadavg = os.getloadavg()
        except OSError:
            s.loadavg = (0, 0, 0)

        # Prozesse
        s.procs = {}
        prev = self._prev
        new_prev = {}
        threads = 0
        wall = (dt or 1.0) * self.ncpu
        # Alle 10 Messungen statische Angaben neu lesen (Name ändert sich z. B. bei exec)
        self._static_tick = (self._static_tick + 1) % 10
        static = self._static if self._static_tick else {}
        new_static = {}
        self._fds_tick = (self._fds_tick + 1) % FDS_EVERY
        count_fds = self._fds_tick == 0
        for p in psutil.process_iter():
            pid = p.pid
            st = static.get(pid)
            try:
                if st is not None and st[0] != p.create_time():
                    st = None
                if st is None:
                    si = p.as_dict(STATIC_ATTRS, ad_value=None)
                    cmd = si["cmdline"]
                    st = (si["create_time"] or 0, si["name"] or "?", si["username"] or "?",
                          " ".join(cmd) if cmd else "", si["exe"] or "", None)
                attrs = DYNAMIC_ATTRS + ["num_fds"] if (count_fds or st[5] is None) else DYNAMIC_ATTRS
                i = p.as_dict(attrs, ad_value=None)
            except psutil.Error:
                continue
            fds = i["num_fds"] if "num_fds" in i else st[5]
            new_static[pid] = st[:5] + (fds if fds is not None else -1,)
            pr = Proc()
            pr.pid = pid
            pr.ppid = i["ppid"] or 0
            pr.create_time, pr.name, pr.user, pr.cmdline, pr.exe = st[:5]
            pr.fds = None if fds is None or fds < 0 else fds
            pr.status = i["status"] or ""
            ct = i["cpu_times"]
            t = (ct.user + ct.system) if ct else 0.0
            pr.cpu_time = t
            mi = i["memory_info"]
            if mi:
                pr.rss, pr.vms = mi.rss, mi.vms
                pr.mem = max(0, mi.rss - getattr(mi, "shared", 0))
            else:
                pr.rss = pr.vms = pr.mem = 0
            pr.threads = i["num_threads"] or 0
            threads += pr.threads
            pr.nice = i["nice"] if i["nice"] is not None else 0
            io = i["io_counters"]
            rb = io.read_bytes if io else None
            wb = io.write_bytes if io else None

            old = prev.get(pid)
            if old is not None and old.ctime != pr.create_time:
                old = None
            if old is not None and dt:
                pr.cpu_delta = max(0.0, t - old.cpu)
                pr.cpu = min(100.0, pr.cpu_delta / wall * 100)
                if rb is not None and old.rb is not None:
                    pr.read_delta = max(0, rb - old.rb)
                    pr.write_delta = max(0, wb - old.wb)
                    pr.read_rate = pr.read_delta / dt
                    pr.write_rate = pr.write_delta / dt
                else:
                    pr.read_delta = pr.write_delta = 0
                    pr.read_rate = pr.write_rate = None if rb is None else 0.0
            else:
                pr.cpu = 0.0
                # Neuer Prozess: alles seit Start zählt für den App-Verlauf
                pr.cpu_delta = 0.0 if first else t
                pr.read_delta = 0 if (first or rb is None) else rb
                pr.write_delta = 0 if (first or wb is None) else wb
                pr.read_rate = None if rb is None else 0.0
                pr.write_rate = None if wb is None else 0.0
            new_prev[pid] = _Prev(pr.create_time, t, rb, wb)
            s.procs[pid] = pr
        self._prev = new_prev
        self._static = new_static
        s.threads = threads
        return s

    def _sample_gpus(self):
        result = {}
        nv = []
        if self._has_nvsmi:
            try:
                out = subprocess.run(
                    ["nvidia-smi", "--query-gpu=pci.bus_id,utilization.gpu,memory.used,"
                     "memory.total,temperature.gpu", "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=2).stdout
                nv = [list(map(str.strip, l.split(","))) for l in out.splitlines() if l]
            except (OSError, subprocess.SubprocessError):
                nv = []
        nv_index = 0
        for g in self.gpus:
            d = {"usage": None, "estimated": False, "vram_used": None, "vram_total": None,
                 "temp": None, "freq": None, "max_freq": None}
            dev = os.path.join(g["path"], "device")
            busy = read_file(os.path.join(dev, "gpu_busy_percent"))
            if busy and busy.isdigit():
                d["usage"] = float(busy)
                try:
                    d["vram_used"] = int(read_file(os.path.join(dev, "mem_info_vram_used"), "0"))
                    d["vram_total"] = int(read_file(os.path.join(dev, "mem_info_vram_total"), "0"))
                except ValueError:
                    pass
            elif g["driver"] == "nvidia" and nv_index < len(nv):
                row = nv[nv_index]
                nv_index += 1
                try:
                    d["usage"] = float(row[1])
                    d["vram_used"] = int(float(row[2])) * 1048576
                    d["vram_total"] = int(float(row[3])) * 1048576
                    d["temp"] = float(row[4])
                except (ValueError, IndexError):
                    pass
            else:
                act = read_file(os.path.join(g["path"], "gt_act_freq_mhz"))
                mx = read_file(os.path.join(g["path"], "gt_max_freq_mhz"))
                mn = read_file(os.path.join(g["path"], "gt_RPn_freq_mhz")) or \
                    read_file(os.path.join(g["path"], "gt_min_freq_mhz"))
                if act and mx and act.isdigit() and mx.isdigit() and int(mx) > 0:
                    a, m, lo = int(act), int(mx), int(mn or 0)
                    d["freq"], d["max_freq"] = a, m
                    # Leerlauftakt als 0 %, Maximaltakt als 100 %
                    d["usage"] = 0.0 if a <= 0 else min(100.0, max(0.0, (a - lo) / max(1, m - lo) * 100))
                    d["estimated"] = True
            for h in glob.glob(os.path.join(dev, "hwmon", "hwmon*", "temp1_input")):
                v = read_file(h)
                if v and v.lstrip("-").isdigit():
                    d["temp"] = int(v) / 1000
            result[g["card"]] = d
        return result
