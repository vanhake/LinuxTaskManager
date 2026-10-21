"""Prozessaktionen, gemeinsames Kontextmenü, Dialoge."""

import os
import shlex
import signal
import urllib.parse

import psutil
from gi.repository import Gio, GLib, Gtk

from . import util

PRIORITIES = [
    ("Echtzeit", -20),
    ("Hoch", -10),
    ("Höher als normal", -5),
    ("Normal", 0),
    ("Niedriger als normal", 5),
    ("Niedrig", 19),
]


def priority_name(nice):
    if nice is None:
        return "–"
    for name, value in PRIORITIES:
        if nice <= value:
            return f"{name} ({nice})"
    return f"Niedrig ({nice})"


# ------------------------------------------------------------- Hilfsdialoge

def message(parent, text, secondary=None, kind=Gtk.MessageType.ERROR):
    d = Gtk.MessageDialog(transient_for=parent, modal=True, message_type=kind,
                          buttons=Gtk.ButtonsType.OK, text=text)
    if secondary:
        d.format_secondary_text(secondary)
    d.run()
    d.destroy()


def confirm(parent, text, secondary=None, ok_label="OK"):
    d = Gtk.MessageDialog(transient_for=parent, modal=True, message_type=Gtk.MessageType.WARNING,
                          buttons=Gtk.ButtonsType.NONE, text=text)
    if secondary:
        d.format_secondary_text(secondary)
    d.add_button("Abbrechen", Gtk.ResponseType.CANCEL)
    d.add_button(ok_label, Gtk.ResponseType.OK)
    d.set_default_response(Gtk.ResponseType.CANCEL)
    r = d.run()
    d.destroy()
    return r == Gtk.ResponseType.OK


def run_async(argv, parent=None, on_done=None, error_text="Aktion fehlgeschlagen"):
    """Befehl asynchron ausführen (z. B. pkexec), Fehler anzeigen."""
    try:
        proc = Gio.Subprocess.new(argv, Gio.SubprocessFlags.STDERR_PIPE | Gio.SubprocessFlags.STDOUT_SILENCE)
    except GLib.Error as e:
        message(parent, error_text, e.message)
        return

    def done(p, res):
        try:
            ok, _, err = p.communicate_utf8_finish(res)
        except GLib.Error as e:
            err, ok = e.message, False
        status = p.get_exit_status() if p.get_if_exited() else -1
        if status != 0 and status not in (126,):  # 126 = Passwortabfrage abgebrochen
            message(parent, error_text, (err or "").strip() or f"Exit-Code {status}")
        if on_done:
            on_done(status == 0)

    proc.communicate_utf8_async(None, None, done)


# ------------------------------------------------------------ Prozessaktionen

def send_signal(parent, pid, sig, name=None):
    try:
        os.kill(pid, sig)
        return True
    except ProcessLookupError:
        return True
    except PermissionError:
        signame = signal.Signals(sig).name.replace("SIG", "")
        what = name or f"PID {pid}"
        if confirm(parent, f"„{what}“ gehört einem anderen Benutzer.",
                   "Für diese Aktion sind Administratorrechte erforderlich. Mit pkexec fortfahren?",
                   "Als Administrator ausführen"):
            run_async(["pkexec", "kill", "-s", signame, str(pid)], parent,
                      error_text="Signal konnte nicht gesendet werden")
        return False


def end_task(parent, pid, name=None):
    send_signal(parent, pid, signal.SIGTERM, name)


def kill_task(parent, pid, name=None):
    if confirm(parent, f"Möchten Sie „{name or pid}“ sofort beenden?",
               "Nicht gespeicherte Daten gehen verloren. Der Prozess erhält keine Gelegenheit, "
               "sich sauber zu beenden (SIGKILL).", "Beenden erzwingen"):
        send_signal(parent, pid, signal.SIGKILL, name)


def end_tree(parent, pid, name=None):
    try:
        root = psutil.Process(pid)
        procs = root.children(recursive=True) + [root]
    except psutil.Error:
        return
    if not confirm(parent, f"Möchten Sie den Prozessbaum von „{name or pid}“ beenden?",
                   f"Es werden {len(procs)} Prozess(e) beendet. Nicht gespeicherte Daten gehen verloren.",
                   "Prozessbaum beenden"):
        return
    denied = []
    for p in procs:
        try:
            p.terminate()
        except psutil.NoSuchProcess:
            pass
        except psutil.AccessDenied:
            denied.append(str(p.pid))
    if denied and confirm(parent, f"{len(denied)} Prozess(e) gehören anderen Benutzern.",
                          "Mit Administratorrechten beenden?", "Als Administrator ausführen"):
        run_async(["pkexec", "kill", "-s", "TERM", *denied], parent)


def set_priority(parent, pid, nice):
    try:
        psutil.Process(pid).nice(nice)
    except psutil.NoSuchProcess:
        pass
    except psutil.AccessDenied:
        if confirm(parent, "Für das Erhöhen der Priorität oder fremde Prozesse sind "
                           "Administratorrechte erforderlich.",
                   "Mit pkexec fortfahren?", "Als Administrator ausführen"):
            run_async(["pkexec", "renice", "-n", str(nice), "-p", str(pid)], parent,
                      error_text="Priorität konnte nicht geändert werden")


def open_location(parent, pid):
    try:
        exe = psutil.Process(pid).exe()
    except psutil.Error:
        exe = ""
    if not exe:
        message(parent, "Der Speicherort ist nicht verfügbar.",
                "Der Prozess gehört einem anderen Benutzer oder ist ein Kernel-Thread.")
        return
    folder = os.path.dirname(exe)
    try:
        Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(folder).get_uri(), None)
    except GLib.Error as e:
        message(parent, "Ordner konnte nicht geöffnet werden", e.message)


def search_online(name):
    url = "https://duckduckgo.com/?q=" + urllib.parse.quote(f"{name} Linux Prozess")
    try:
        Gio.AppInfo.launch_default_for_uri(url, None)
    except GLib.Error:
        pass


def properties(parent, pid):
    try:
        p = psutil.Process(pid)
        with p.oneshot():
            def get(fn, default="–"):
                try:
                    v = fn()
                    return default if v in (None, "", []) else v
                except (psutil.AccessDenied, psutil.ZombieProcess, OSError):
                    return "Zugriff verweigert"
            ct = get(p.cpu_times, None)
            mi = get(p.memory_info, None)
            rows = [
                ("Name", get(p.name)),
                ("PID", str(pid)),
                ("Übergeordneter Prozess", f"{get(p.ppid)}"),
                ("Benutzer", get(p.username)),
                ("Status", util.status_de(get(p.status))),
                ("Pfad", get(p.exe)),
                ("Befehlszeile", " ".join(get(p.cmdline, [])) or "–"),
                ("Arbeitsverzeichnis", get(p.cwd)),
                ("Gestartet", util.datetime(get(p.create_time, 0))),
                ("CPU-Zeit", util.cpu_time(ct.user + ct.system) if hasattr(ct, "user") else "–"),
                ("Speicher (RSS)", util.size(mi.rss) if hasattr(mi, "rss") else "–"),
                ("Speicher (privat)", util.size(max(0, mi.rss - mi.shared)) if hasattr(mi, "rss") else "–"),
                ("Virtueller Speicher", util.size(mi.vms) if hasattr(mi, "vms") else "–"),
                ("Threads", str(get(p.num_threads))),
                ("Handles (offene Dateien)", str(get(p.num_fds))),
                ("Priorität", priority_name(get(p.nice, None)) if isinstance(get(p.nice, None), int) else "–"),
                ("Terminal", get(p.terminal)),
            ]
    except psutil.NoSuchProcess:
        message(parent, "Der Prozess existiert nicht mehr.")
        return

    d = Gtk.Dialog(title=f"Eigenschaften von {rows[0][1]}", transient_for=parent, modal=True)
    d.add_button("Schließen", Gtk.ResponseType.CLOSE)
    d.set_default_size(560, -1)
    grid = Gtk.Grid(column_spacing=16, row_spacing=6, margin=16)
    for i, (k, v) in enumerate(rows):
        kl = Gtk.Label(label=k + ":", xalign=0)
        kl.get_style_context().add_class("dim-label")
        vl = Gtk.Label(label=str(v), xalign=0, selectable=True, wrap=True, max_width_chars=60)
        vl.set_line_wrap_mode(2)  # WORD_CHAR
        grid.attach(kl, 0, i, 1, 1)
        grid.attach(vl, 1, i, 1, 1)
    d.get_content_area().add(grid)
    d.show_all()
    d.run()
    d.destroy()


def process_menu(parent, pid, name, details=False, goto_details=None):
    """Kontextmenü für einen Prozess."""
    menu = Gtk.Menu()

    def item(label, cb):
        mi = Gtk.MenuItem.new_with_mnemonic(label)
        mi.connect("activate", lambda *_: cb())
        menu.append(mi)
        return mi

    item("_Task beenden", lambda: end_task(parent, pid, name))
    item("Beenden _erzwingen", lambda: kill_task(parent, pid, name))
    item("_Prozessbaum beenden", lambda: end_tree(parent, pid, name))
    menu.append(Gtk.SeparatorMenuItem())

    prio = Gtk.MenuItem.new_with_mnemonic("P_riorität festlegen")
    sub = Gtk.Menu()
    try:
        current = psutil.Process(pid).nice()
    except psutil.Error:
        current = None
    for label, value in PRIORITIES:
        ri = Gtk.CheckMenuItem(label=label)
        ri.set_draw_as_radio(True)
        ri.set_active(current == value)
        ri.connect("activate", lambda w, v=value: set_priority(parent, pid, v))
        sub.append(ri)
    if current is not None and current not in [v for _, v in PRIORITIES]:
        sub.append(Gtk.SeparatorMenuItem())
        info = Gtk.MenuItem(label=f"Aktuell: Nice {current}")
        info.set_sensitive(False)
        sub.append(info)
    prio.set_submenu(sub)
    menu.append(prio)

    if details:
        item("_Anhalten (SIGSTOP)", lambda: send_signal(parent, pid, signal.SIGSTOP, name))
        item("_Fortsetzen (SIGCONT)", lambda: send_signal(parent, pid, signal.SIGCONT, name))
    menu.append(Gtk.SeparatorMenuItem())
    item("_Dateispeicherort öffnen", lambda: open_location(parent, pid))
    item("_Online suchen", lambda: search_online(name))
    if goto_details:
        item("Zu _Details wechseln", lambda: goto_details(pid))
    item("E_igenschaften", lambda: properties(parent, pid))
    menu.show_all()
    return menu


# ---------------------------------------------------------- Neuer Task

def run_new_task(parent):
    d = Gtk.Dialog(title="Neuen Task erstellen", transient_for=parent, modal=True)
    d.add_button("Abbrechen", Gtk.ResponseType.CANCEL)
    d.add_button("OK", Gtk.ResponseType.OK)
    d.set_default_response(Gtk.ResponseType.OK)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin=16)
    box.add(Gtk.Label(label="Geben Sie den Namen eines Programms, Ordners oder einer Datei ein.",
                      xalign=0))
    row = Gtk.Box(spacing=8)
    row.add(Gtk.Label(label="Öffnen:"))
    entry = Gtk.Entry(activates_default=True, hexpand=True)
    row.pack_start(entry, True, True, 0)
    browse = Gtk.Button(label="Durchsuchen…")
    row.add(browse)
    box.add(row)
    admin = Gtk.CheckButton(label="Diesen Task mit Administratorrechten erstellen")
    box.add(admin)
    d.get_content_area().add(box)

    def on_browse(_):
        fc = Gtk.FileChooserNative.new("Durchsuchen", d, Gtk.FileChooserAction.OPEN, None, None)
        if fc.run() == Gtk.ResponseType.ACCEPT:
            entry.set_text(shlex.quote(fc.get_filename()))
    browse.connect("clicked", on_browse)
    d.show_all()
    if d.run() == Gtk.ResponseType.OK:
        text = entry.get_text().strip()
        if text:
            _launch(parent, text, admin.get_active())
    d.destroy()


def _launch(parent, text, admin):
    if os.path.exists(os.path.expanduser(text)) and not os.access(os.path.expanduser(text), os.X_OK) \
            or os.path.isdir(os.path.expanduser(text)) or "://" in text:
        target = text if "://" in text else Gio.File.new_for_path(os.path.expanduser(text)).get_uri()
        try:
            Gio.AppInfo.launch_default_for_uri(target, None)
        except GLib.Error as e:
            message(parent, "Öffnen fehlgeschlagen", e.message)
        return
    try:
        argv = shlex.split(text)
    except ValueError as e:
        message(parent, "Ungültige Eingabe", str(e))
        return
    if admin:
        argv = ["pkexec", "env", f"DISPLAY={os.environ.get('DISPLAY', ':0')}",
                f"XAUTHORITY={os.environ.get('XAUTHORITY', '')}"] + argv
    try:
        GLib.spawn_async(argv, flags=GLib.SpawnFlags.SEARCH_PATH)
    except GLib.Error as e:
        message(parent, f"„{text}“ konnte nicht gestartet werden.", e.message)
