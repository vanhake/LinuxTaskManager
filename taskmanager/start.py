"""Gemeinsamer Einstieg für „python3 -m taskmanager“, .deb-Starter und .pyz-Datei."""

import sys

USAGE = """Linux Taskmanager

Aufruf / usage:
  linux-taskmanager              Fenster öffnen / open window
  linux-taskmanager --cleanup    „Speicherplatz freigeben“ öffnen / open "Free up disk space"
  linux-taskmanager --recorder   Systemrekorder ohne Fenster / system recorder without window
  linux-taskmanager --version    Version anzeigen / show version
"""


def main():
    if "--help" in sys.argv or "-h" in sys.argv:
        print(USAGE)
        return 0

    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("PangoCairo", "1.0")

    # Fensterklasse festlegen, BEVOR Gtk geladen wird: PyGObject initialisiert GTK schon beim
    # Import und würde sonst „__main__.py“ als Klasse verwenden. Die Taskleiste ordnet das
    # Fenster über diese Klasse (StartupWMClass=Taskmanager) dem Menüeintrag und Symbol zu.
    from gi.repository import GLib
    GLib.set_prgname("taskmanager")
    from gi.repository import Gdk
    Gdk.set_program_class("Taskmanager")

    # Sprache festlegen, bevor die übrigen Module (mit ihren Texten) geladen werden
    from . import i18n
    from .settings import Settings
    i18n.setup(Settings().get("language", "auto"))

    if "--version" in sys.argv:
        from .version import VERSION
        print(f"Linux Taskmanager {VERSION}")
        return 0

    if "--recorder" in sys.argv:
        # Kopfloser Systemrekorder-Dienst ohne Fenster
        from .recorder import run_daemon
        return run_daemon()

    from .app import main as app_main
    return app_main()
