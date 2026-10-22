"""Speicherplatz freigeben: Bereinigungs-Kategorien und selten genutzte Programme.

Nur Logik, keine Oberfläche. Benutzer-Aktionen laufen direkt in Python,
Aktionen mit Root-Rechten werden als festes Skript gesammelt und vom Aufrufer
über pkexec (Passwortabfrage) ausgeführt. Paketnamen werden vor der Verwendung
in Befehlen streng geprüft.
"""

import os
import re
import shutil
import stat
import subprocess
import time

from gi.repository import Gio, GLib

from . import i18n
from .i18n import _

TMP_DAYS = 7          # Dateien in /tmp, /var/tmp: älter als … Tage
TMP_DIRS = ("/tmp", "/var/tmp")
JOURNAL_KEEP = "14d"  # Systemprotokolle der letzten 14 Tage behalten
PKG_RE = re.compile(r"^[a-z0-9][a-z0-9+.\-]*(:[a-z0-9]+)?$")
FLATPAK_RE = re.compile(r"^[A-Za-z0-9_\-]+(\.[A-Za-z0-9_\-]+)+$")
TMP_SKIP = (".X", ".ICE", ".font-unix", ".XIM", ".Test", "systemd-private", "snap", "tracker", "ssh-",
            "pulse-", "dbus-", "gdm", "lightdm", "mintUpdate")
INTERPRETERS = {"python", "python3", "python2", "sh", "bash", "dash", "perl", "ruby", "java", "node", "env",
                "gjs", "mono", "wine", "pkexec", "sudo", "nice", "ionice"}
# Pakete, die zum Grundsystem gehören und nicht zum Deinstallieren angeboten werden
PROTECT_RE = re.compile(r"^(mint|cinnamon|nemo|xapp|lightdm|slick-greeter|xorg|xserver|update-manager|ubuntu-|"
                        r"linux-|systemd|network-manager|pulseaudio|pipewire|wireplumber|gnome-terminal|"
                        r"gnome-keyring|gnome-session|software-properties|synaptic|apt|dpkg|python3|gir1\.2|"
                        r"policykit|pkexec|polkit|gvfs|dbus|udisks|upower|bluez|blueman|cups|"
                        r"timeshift|linux-taskmanager)")
# Wenn eine Deinstallation diese Pakete mitentfernen würde, wird sie blockiert
CRITICAL_RE = re.compile(r"^(mint-meta-|mintsystem|mintupdate|cinnamon$|cinnamon-core|cinnamon-session|nemo$|"
                         r"lightdm|xserver-xorg-core|network-manager$|systemd$|apt$|dpkg$|sudo$|policykit-1|"
                         r"pkexec|linux-image-generic|linux-generic)")


def home(*parts):
    return os.path.join(os.path.expanduser("~"), *parts)


# ------------------------------------------------------------------ Größen

def tree_size(path, newest=False):
    """Belegter Platz (wie du) eines Ordners; mit newest=True zusätzlich jüngste Änderung."""
    total = 0
    latest = 0.0
    try:
        st = os.lstat(path)
    except OSError:
        return (0, 0.0) if newest else 0
    total += st.st_blocks * 512
    latest = st.st_mtime
    if stat.S_ISDIR(st.st_mode):
        stack = [path]
        while stack:
            d = stack.pop()
            try:
                with os.scandir(d) as it:
                    for e in it:
                        try:
                            s = e.stat(follow_symlinks=False)
                        except OSError:
                            continue
                        total += s.st_blocks * 512
                        latest = max(latest, s.st_mtime)
                        if stat.S_ISDIR(s.st_mode):
                            stack.append(e.path)
            except OSError:
                continue
    return (total, latest) if newest else total


def _remove(path):
    """Datei/Ordner löschen, Symlinks nie folgen. Gibt freigegebene Bytes zurück."""
    try:
        st = os.lstat(path)
    except OSError:
        return 0
    if stat.S_ISDIR(st.st_mode):
        before = tree_size(path)
        shutil.rmtree(path, ignore_errors=True)
        after = tree_size(path) if os.path.lexists(path) else 0
        return max(0, before - after)
    try:
        os.unlink(path)
        return st.st_blocks * 512
    except OSError:
        return 0


def _clear_contents(directory, keep=()):
    freed = 0
    try:
        entries = list(os.scandir(directory))
    except OSError:
        return 0
    for e in entries:
        if e.name not in keep:
            freed += _remove(e.path)
    return freed


def _run(cmd, timeout=60):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              env=dict(os.environ, LC_ALL="C")).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _parse_size(text):
    """„1.2G“, „584.1M“, „12,3 MB“ → Bytes."""
    # Trennzeichen zwischen Zahl und Einheit beliebig (Leerzeichen, geschütztes Leerzeichen, „?“)
    m = re.search(r"([\d.,]+)[^\dA-Za-z]{0,3}([KMGT]i?B?|B|bytes)?", text or "")
    if not m:
        return None
    value = float(m.group(1).replace(",", "."))
    unit = (m.group(2) or "B")[0].upper()
    return int(value * {"B": 1, "K": 1024, "M": 1024 ** 2, "G": 1024 ** 3, "T": 1024 ** 4}.get(unit, 1))


# ------------------------------------------------------------------ Kategorien

class Category:
    def __init__(self, key, title, description, root, default, icon):
        self.key, self.title, self.description = key, title, description
        self.root, self.default, self.icon = root, default, icon
        self.size = None        # Bytes (None = unbekannt)
        self.details = []       # Zeilen für die Detailansicht
        self.available = True
        self.note = ""

    def scan(self):
        pass

    def clean(self):
        """Benutzer-Aktion ausführen → freigegebene Bytes."""
        return 0

    def root_commands(self):
        """Befehle für das gemeinsame Root-Skript."""
        return []


class Trash(Category):
    def __init__(self):
        super().__init__("trash", _("Papierkorb"), _("Gelöschte Dateien endgültig entfernen"), False, False,
                         "user-trash-symbolic")

    def scan(self):
        base = home(".local", "share", "Trash")
        self.size = sum(tree_size(os.path.join(base, d)) for d in ("files", "info", "expunged"))
        try:
            n = len(os.listdir(os.path.join(base, "files")))
        except OSError:
            n = 0
        self.details = [_("{0} Einträge im Papierkorb").format(n)]
        self.note = _("Endgültig – kann nicht rückgängig gemacht werden.")

    def clean(self):
        base = home(".local", "share", "Trash")
        return sum(_clear_contents(os.path.join(base, d)) for d in ("files", "info", "expunged"))


class Thumbnails(Category):
    def __init__(self):
        super().__init__("thumbs", _("Miniaturansichten"), _("Vorschaubilder des Dateimanagers – werden bei Bedarf neu erstellt"),
                         False, True, "image-x-generic-symbolic")

    def scan(self):
        self.size = tree_size(home(".cache", "thumbnails")) if os.path.isdir(home(".cache", "thumbnails")) else 0

    def clean(self):
        return _clear_contents(home(".cache", "thumbnails"))


class UserCache(Category):
    def __init__(self):
        super().__init__("cache", _("Programm-Cache"), _("Zwischenspeicher in ~/.cache (Browser, Programme) – wird neu aufgebaut"),
                         False, False, "folder-symbolic")

    def scan(self):
        base = home(".cache")
        parts = []
        try:
            for e in os.scandir(base):
                if e.name == "thumbnails":
                    continue
                parts.append((tree_size(e.path), e.name))
        except OSError:
            pass
        parts.sort(reverse=True)
        self.size = sum(p[0] for p in parts)
        self.parts = parts  # [(Bytes, Ordnername)], größte zuerst
        self.selected = None
        from . import util
        self.details = [f"{n}: {util.size(s)}" for s, n in parts[:8]]
        self.note = _("Vorher Browser und andere Programme schließen.")

    def clean(self):
        # nur die in der Oberfläche ausgewählten Unterordner (Standard: alle)
        selected = getattr(self, "selected", None)
        if selected is None:
            return _clear_contents(home(".cache"), keep=("thumbnails",))
        return sum(_remove(home(".cache", n)) for n in selected if n != "thumbnails" and "/" not in n)


class TempFiles(Category):
    def __init__(self):
        super().__init__("tmp", _("Temporäre Dateien"),
                         _("Eigene Dateien in /tmp und /var/tmp, älter als {0} Tage").format(TMP_DAYS),
                         False, True, "edit-clear-symbolic")
        self._paths = []

    def _candidates(self):
        uid = os.getuid()
        cutoff = time.time() - TMP_DAYS * 86400
        for base in TMP_DIRS:
            try:
                entries = list(os.scandir(base))
            except OSError:
                continue
            for e in entries:
                if e.name.startswith(TMP_SKIP):
                    continue
                try:
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                if st.st_uid != uid or stat.S_ISSOCK(st.st_mode) or stat.S_ISFIFO(st.st_mode):
                    continue
                size, newest = tree_size(e.path, newest=True)
                if newest < cutoff:  # auch nichts darin wurde kürzlich geändert
                    yield e.path, size

    def scan(self):
        found = list(self._candidates())
        self._paths = [p for p, _s in found]
        self.size = sum(s for _p, s in found)
        self.details = [os.path.basename(p) for p in self._paths[:8]]
        if len(self._paths) > 8:
            self.details.append(_("… und {0} weitere").format(len(self._paths) - 8))

    def clean(self):
        # zur Sicherheit erneut prüfen (Alter, Besitzer)
        return sum(_remove(p) for p, _s in self._candidates())


class AptCache(Category):
    def __init__(self):
        super().__init__("apt", _("Paket-Cache (APT)"), _("Heruntergeladene Installationsdateien bereits installierter Pakete"),
                         True, True, "package-x-generic-symbolic")

    def scan(self):
        self.available = bool(shutil.which("apt-get"))
        self.size = tree_size("/var/cache/apt/archives") if self.available else 0

    def root_commands(self):
        return ["apt-get clean"]


class Autoremove(Category):
    def __init__(self):
        super().__init__("autoremove", _("Nicht mehr benötigte Pakete"),
                         _("Automatisch installierte Abhängigkeiten und alte Kernel, die nichts mehr braucht"),
                         True, True, "system-software-install-symbolic")
        self.packages = []

    def scan(self):
        self.available = bool(shutil.which("apt-get"))
        if not self.available:
            self.size = 0
            return
        out = _run(["apt-get", "-s", "autoremove"])
        self.packages = re.findall(r"^Remv (\S+)", out, re.M)
        self.size = package_sizes(self.packages)
        self.details = self.packages[:12] + ([_("… und {0} weitere").format(len(self.packages) - 12)]
                                             if len(self.packages) > 12 else [])

    def root_commands(self):
        if not self.packages:
            return []
        return ["DEBIAN_FRONTEND=noninteractive apt-get -y autoremove --purge"]


class Journal(Category):
    def __init__(self):
        super().__init__("journal", _("Systemprotokolle"),
                         _("Protokolle (journald) älter als 14 Tage löschen"), True, False, "text-x-generic-symbolic")

    def scan(self):
        self.available = bool(shutil.which("journalctl"))
        out = _run(["journalctl", "--disk-usage"]) if self.available else ""
        total = _parse_size(out.split("take up")[-1]) if "take up" in out else None
        self.size = None
        self.details = [_("Belegt insgesamt: {0}").format(_fmt(total))] if total else []
        self.note = _("Wie viel frei wird, hängt vom Alter der Protokolle ab.")

    def root_commands(self):
        return [f"journalctl --vacuum-time={JOURNAL_KEEP}"]


class FlatpakUnused(Category):
    def __init__(self):
        super().__init__("flatpak", _("Ungenutzte Flatpak-Laufzeiten"),
                         _("Laufzeiten und Erweiterungen, die keine App mehr verwendet"), True, False,
                         "application-x-addon-symbolic")

    def scan(self):
        self.available = bool(shutil.which("flatpak"))
        self.size = None
        self.note = _("Größe wird erst beim Entfernen ermittelt.")

    def root_commands(self):
        return ["flatpak uninstall --system --unused -y --noninteractive"]

    def clean(self):
        # Benutzer-Installation (ohne Passwort)
        if self.available:
            _run(["flatpak", "uninstall", "--user", "--unused", "-y", "--noninteractive"], timeout=600)
        return 0


def _fmt(n):
    from . import util
    return util.size(n) if n is not None else "–"


def categories():
    cats = [Thumbnails(), TempFiles(), UserCache(), Trash(), AptCache(), Autoremove(), Journal()]
    if shutil.which("flatpak"):
        cats.append(FlatpakUnused())
    return cats


def step_results(output):
    """Exit-Codes der Schritte aus der Ausgabe von root_script() → {index: rc}."""
    return {int(i): int(rc) for i, rc in re.findall(r"^### (\d+)\n.*?^### rc=(\d+)$", output, re.S | re.M)}


def root_script(commands):
    """Festes Shell-Skript aus geprüften Befehlen; jeder Schritt wird protokolliert."""
    lines = ["export LC_ALL=C"]
    for i, cmd in enumerate(commands):
        lines.append(f"echo '### {i}'; {cmd} 2>&1; echo \"### rc=$?\"")
    return "\n".join(lines)


# ------------------------------------------------------------------ Pakete

def package_sizes(packages):
    """Installierte Größe (Bytes) der genannten Pakete zusammen."""
    if not packages:
        return 0
    out = _run(["dpkg-query", "-W", "-f=${Installed-Size}\n", *packages])
    return sum(int(x) * 1024 for x in out.split() if x.isdigit())


def simulate_remove(packages):
    """Welche Pakete würde „apt-get remove“ insgesamt entfernen?"""
    packages = [p for p in packages if PKG_RE.match(p)]
    if not packages:
        return []
    out = _run(["apt-get", "-s", "remove", *packages])
    return re.findall(r"^Remv (\S+)", out, re.M)


def critical_in(removed):
    """Pakete aus einer Simulation, deren Entfernung das System beschädigen würde."""
    return [p for p in removed if CRITICAL_RE.match(p.split(":")[0])]


def remove_commands(debs, flatpaks):
    cmds = []
    debs = [p for p in debs if PKG_RE.match(p)]
    flatpaks = [(a, inst) for a, inst in flatpaks if FLATPAK_RE.match(a) and inst in ("system", "user")]
    if debs:
        cmds.append("DEBIAN_FRONTEND=noninteractive apt-get -y remove " + " ".join(debs))
    for app, inst in flatpaks:
        if inst == "system":
            cmds.append(f"flatpak uninstall --system -y --noninteractive {app}")
    return cmds


def user_flatpak_remove(flatpaks):
    for app, inst in flatpaks:
        if inst == "user" and FLATPAK_RE.match(app):
            _run(["flatpak", "uninstall", "--user", "-y", "--noninteractive", app], timeout=600)


# ------------------------------------------------------------------ selten genutzte Programme

class Program:
    __slots__ = ("name", "icon", "kind", "package", "size", "last_used", "never", "protected", "reason",
                 "installation", "desktop")


def _dpkg_owners(paths):
    """Desktop-Datei → Paket (ein dpkg-Aufruf für alle)."""
    owners = {}
    for i in range(0, len(paths), 200):
        out = _run(["dpkg", "-S", *paths[i:i + 200]])
        for line in out.splitlines():
            if ": " in line:
                pkg, path = line.split(": ", 1)
                owners[path.strip()] = pkg.split(",")[0].strip()
    return owners


def _package_info(packages):
    info = {}
    if not packages:
        return info
    out = _run(["dpkg-query", "-W", "-f=${Package}\t${Installed-Size}\t${Priority}\t${Essential}\n", *packages])
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) == 4:
            info[parts[0]] = {"size": int(parts[1]) * 1024 if parts[1].isdigit() else 0,
                              "priority": parts[2], "essential": parts[3] == "yes"}
    return info


def _installed_time(pkg):
    for name in (pkg, pkg + ":amd64", pkg + ":i386", pkg + ":all"):
        try:
            return os.stat(f"/var/lib/dpkg/info/{name}.list").st_mtime
        except OSError:
            continue
    return None


def _target_executable(app):
    """Eigentliche Programmdatei (bei Python-/Shell-Skripten das Skript, nicht der Interpreter)."""
    try:
        ok, argv = GLib.shell_parse_argv(app.get_commandline() or "")
    except GLib.Error:
        argv = []
    argv = [a for a in argv if not a.startswith("%")]
    i = 0
    while i < len(argv):
        a = argv[i]
        base = os.path.basename(a)
        if "=" in a and not a.startswith("/") or a.startswith("-"):
            i += 1
            continue
        if base.rstrip("0123456789.") in INTERPRETERS or base in INTERPRETERS:
            i += 1
            continue
        path = a if os.path.isabs(a) else shutil.which(a)
        return os.path.realpath(path) if path else None
    return None


def _flatpak_sizes():
    sizes = {}
    out = _run(["flatpak", "list", "--app", "--columns=application,installation,size"])
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3:
            sizes[parts[0]] = (parts[1], _parse_size(parts[2]))
    return sizes


def _flatpak_last_used(app_id):
    base = home(".var", "app", app_id)
    if not os.path.isdir(base):
        return None
    latest = os.stat(base).st_mtime
    for sub in ("config", "data", "cache", ".local"):
        p = os.path.join(base, sub)
        try:
            latest = max(latest, os.stat(p).st_mtime)
            with os.scandir(p) as it:
                for e in it:
                    latest = max(latest, e.stat(follow_symlinks=False).st_mtime)
        except OSError:
            continue
    return latest


def programs():
    """Alle sichtbaren Programme mit Paket, Größe und letzter Benutzung."""
    apps = [a for a in Gio.AppInfo.get_all() if a.should_show() and isinstance(a, Gio.DesktopAppInfo)]
    deb_paths = [a.get_filename() for a in apps if a.get_filename() and a.get_filename().startswith("/usr/")]
    owners = _dpkg_owners(deb_paths)
    pinfo = _package_info(sorted(set(owners.values())))
    fsizes = _flatpak_sizes() if shutil.which("flatpak") else {}
    result = {}
    for a in apps:
        fn = a.get_filename() or ""
        p = Program()
        # Englisch: Originalname (die Systemsprache würde den deutschen Namen liefern)
        raw = a.get_string("Name") if i18n.is_en() else None
        p.name = raw or a.get_name()
        p.icon = a.get_icon()
        p.desktop = fn
        p.protected = False
        p.reason = ""
        p.never = False
        p.installation = ""
        flat = a.get_string("X-Flatpak")
        if flat and FLATPAK_RE.match(flat):
            p.kind, p.package = "flatpak", flat
            inst, size = fsizes.get(flat, ("system", None))
            p.installation, p.size = inst, size
            p.last_used = _flatpak_last_used(flat)
            p.never = p.last_used is None
        elif fn in owners:
            pkg = owners[fn]
            info = pinfo.get(pkg, {})
            p.kind, p.package, p.size = "deb", pkg, info.get("size")
            if info.get("essential") or info.get("priority") in ("required", "important") or PROTECT_RE.match(pkg):
                p.protected = True
                p.reason = _("Teil des Systems")
            exe = _target_executable(a)
            installed = _installed_time(pkg)
            atime = None
            if exe:
                try:
                    atime = os.stat(exe).st_atime
                except OSError:
                    atime = None
            if atime is not None and installed is not None and atime <= installed + 120:
                p.never, p.last_used = True, installed
            else:
                p.last_used = atime
        else:
            continue  # nicht über Paketverwaltung installiert (z. B. eigene Starter)
        key = (p.kind, p.package)
        old = result.get(key)
        # mehrere Starter je Paket: den zuletzt benutzten behalten
        if old is None or (p.last_used or 0) > (old.last_used or 0):
            result[key] = p
    return list(result.values())


def noatime_warning():
    """Hinweis, falls das Dateisystem keine Zugriffszeiten speichert."""
    try:
        with open("/proc/mounts") as f:
            for line in f:
                parts = line.split()
                if len(parts) > 3 and parts[1] in ("/", "/usr") and "noatime" in parts[3].split(","):
                    return True
    except OSError:
        pass
    return False
