"""Statische bzw. selten ändernde Hardware-Informationen."""

from .i18n import _

import glob
import os
import re
import shutil
import socket
import subprocess

import psutil

from .util import read_file


def _run(cmd):
    try:
        env = dict(os.environ, LC_ALL="C")
        return subprocess.run(cmd, capture_output=True, text=True, timeout=3, env=env).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


# --------------------------------------------------------------------- CPU

def cpu_info():
    info = {
        "model": "",
        "base_mhz": None,
        "sockets": 1,
        "cores": psutil.cpu_count(logical=False) or 1,
        "logical": psutil.cpu_count(logical=True) or 1,
        "virtualization": _("Deaktiviert"),
        "l1": "–", "l2": "–", "l3": "–",
    }
    out = _run(["lscpu"])
    kv = {}
    for line in out.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            kv[k.strip()] = v.strip()
    info["model"] = kv.get("Model name", "") or _cpuinfo_model()
    try:
        info["sockets"] = int(kv.get("Socket(s)", 1))
    except ValueError:
        pass
    virt = kv.get("Virtualization")
    if virt:
        info["virtualization"] = _('Aktiviert ({0})').format(virt)

    def cache(name):
        v = kv.get(name)
        if not v:
            return "–"
        v = re.sub(r"\s*\(.*\)", "", v)
        return v.replace(_("KiB"), _("KB")).replace(_("MiB"), _("MB")).replace(_("GiB"), _("GB"))

    l1d, l1i = kv.get("L1d cache"), kv.get("L1i cache")
    if l1d and l1i:
        try:
            total = _parse_kib(l1d) + _parse_kib(l1i)
            info["l1"] = _('{0} KB').format(int(total))
        except ValueError:
            info["l1"] = cache(_("L1d cache"))
    info["l2"] = cache(_("L2 cache"))
    info["l3"] = cache(_("L3 cache"))

    base = read_file("/sys/devices/system/cpu/cpu0/cpufreq/base_frequency")
    if base:
        info["base_mhz"] = int(base) / 1000
    else:
        m = re.search(r"@\s*([\d.]+)\s*GHz", info["model"])
        if m:
            info["base_mhz"] = float(m.group(1)) * 1000
        else:
            mx = read_file("/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq")
            if mx:
                info["base_mhz"] = int(mx) / 1000
    info["model"] = re.sub(r"\s+", " ", info["model"])
    return info


def _parse_kib(s):
    s = re.sub(r"\s*\(.*\)", "", s).strip()
    val, unit = s.split()[:2]
    val = float(val)
    return val * {"KiB": 1, "MiB": 1024, "GiB": 1048576}.get(unit, 1)


def _cpuinfo_model():
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith(_("model name")):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return _("Prozessor")


# --------------------------------------------------------------- Datenträger

def physical_disks():
    """Namen physischer Datenträger aus /sys/block."""
    disks = []
    for path in sorted(glob.glob("/sys/block/*")):
        name = os.path.basename(path)
        if name.startswith(("loop", "ram", "zram", "sr", "fd", "dm-", "md")):
            continue
        try:
            if int(read_file(os.path.join(path, "size"), "0")) == 0:
                continue
        except ValueError:
            continue
        disks.append(name)
    return disks


def disk_info(name):
    base = f"/sys/block/{name}"
    sectors = int(read_file(f"{base}/size", "0") or 0)
    rotational = read_file(f"{base}/queue/rotational", "0") == "1"
    model = (read_file(f"{base}/device/model") or "").strip()
    vendor = (read_file(f"{base}/device/vendor") or "").strip()
    if vendor and vendor.upper() not in (_("ATA"), "") and not model.startswith(vendor):
        model = f"{vendor} {model}".strip()
    if name.startswith("nvme"):
        typ = _("SSD (NVMe)")
    elif read_file(f"{base}/removable") == "1":
        typ = _("Wechseldatenträger")
    else:
        typ = _("HDD") if rotational else _("SSD")

    parts = [os.path.basename(p) for p in glob.glob(f"{base}/{name}*")]
    devs = {name, *parts}
    formatted = 0
    system = False
    for p in psutil.disk_partitions(all=False):
        dev = os.path.basename(os.path.realpath(p.device))
        if dev in devs or _dm_parent(dev) & devs:
            try:
                formatted += psutil.disk_usage(p.mountpoint).total
            except OSError:
                pass
            if p.mountpoint in ("/", "/boot", "/boot/efi"):
                system = True
    swap = False
    try:
        with open("/proc/swaps") as f:
            for line in f.readlines()[1:]:
                dev = os.path.basename(os.path.realpath(line.split()[0]))
                if dev in devs or _dm_parent(dev) & devs:
                    swap = True
                elif line.split()[1] == "file" and system:
                    swap = True
    except OSError:
        pass
    return {
        "name": name,
        "model": model or name,
        "type": typ,
        "capacity": sectors * 512,
        "formatted": formatted,
        "system": system,
        "swap": swap,
    }


def _dm_parent(dev):
    """Physische Partitionen hinter einem Device-Mapper-Gerät (LVM/LUKS)."""
    slaves = glob.glob(f"/sys/block/{dev}/slaves/*")
    result = set()
    for s in slaves:
        n = os.path.basename(s)
        result.add(n)
        result |= _dm_parent(n)
    return result


# ----------------------------------------------------------------- Netzwerk

def net_adapters():
    """Anzuzeigende Netzwerkadapter: physische immer, virtuelle nur wenn aktiv."""
    stats = psutil.net_if_stats()
    result = []
    for name in sorted(stats):
        if name == "lo":
            continue
        physical = os.path.exists(f"/sys/class/net/{name}/device")
        if physical or (stats[name].isup and not name.startswith("veth")):
            result.append(name)
    return result


def net_info(name):
    wireless = os.path.exists(f"/sys/class/net/{name}/wireless") or os.path.exists(
        f"/sys/class/net/{name}/phy80211")
    physical = os.path.exists(f"/sys/class/net/{name}/device")
    if wireless:
        typ = _("WLAN")
    elif physical:
        typ = _("Ethernet")
    else:
        typ = _("Virtuell")
    ipv4, ipv6 = [], []
    for a in psutil.net_if_addrs().get(name, []):
        if a.family == socket.AF_INET:
            ipv4.append(a.address)
        elif a.family == socket.AF_INET6:
            ipv6.append(a.address.split("%")[0])
    st = psutil.net_if_stats().get(name)
    ssid = ""
    if wireless and shutil.which("iwgetid"):
        ssid = _run(["iwgetid", "-r", name]).strip()
    driver = os.path.basename(os.path.realpath(f"/sys/class/net/{name}/device/driver")) \
        if physical else ""
    return {
        "name": name,
        "type": typ,
        "ipv4": ", ".join(ipv4) or "–",
        "ipv6": ", ".join(ipv6) or "–",
        "speed": st.speed if st else 0,
        "up": bool(st and st.isup),
        "ssid": ssid,
        "driver": driver,
        "mac": read_file(f"/sys/class/net/{name}/address", "–"),
    }


# ---------------------------------------------------------------------- GPU

def gpus():
    cards = []
    for path in sorted(glob.glob("/sys/class/drm/card[0-9]*")):
        card = os.path.basename(path)
        if "-" in card:
            continue
        dev = os.path.join(path, "device")
        slot = os.path.basename(os.path.realpath(dev))
        driver = os.path.basename(os.path.realpath(os.path.join(dev, "driver")))
        name = ""
        out = _run(["lspci", "-mm", "-s", slot]) if shutil.which("lspci") else ""
        m = re.findall(r'"([^"]*)"', out)
        if len(m) >= 3:
            vendor = m[1].replace(_(" Corporation"), "").replace(_(", Inc."), "")
            name = f"{vendor} {m[2]}"
        cards.append({
            "card": card,
            "path": path,
            "slot": slot,
            "driver": driver,
            "name": name or _('Grafikkarte ({0})').format(driver),
        })
    return cards


def hostname():
    return socket.gethostname()


def os_info():
    pretty = _("Linux")
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    pretty = line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").replace("X-", "") or "–"
    session = os.environ.get("XDG_SESSION_TYPE", "")
    return {
        "os": pretty,
        "kernel": os.uname().release,
        "arch": os.uname().machine,
        "desktop": f"{desktop} ({session})" if session else desktop,
        "host": hostname(),
    }
