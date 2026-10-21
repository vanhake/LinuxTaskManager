import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("PangoCairo", "1.0")

# Schutz: Benchmark-Arbeitsprozesse (multiprocessing „spawn“) importieren dieses
# Modul erneut als „__mp_main__“ – dann darf kein Fenster starten.
if __name__ == "__main__":
    # Sprache festlegen, bevor die übrigen Module (mit ihren Texten) geladen werden
    from . import i18n
    from .settings import Settings
    i18n.setup(Settings().get("language", "auto"))

    if "--recorder" in sys.argv:
        # Kopfloser Flight-Recorder-Dienst ohne Fenster
        from .recorder import run_daemon
        sys.exit(run_daemon())

    from .app import main
    sys.exit(main())
