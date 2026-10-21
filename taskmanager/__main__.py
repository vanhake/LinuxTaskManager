import sys

# Schutz: Benchmark-Arbeitsprozesse (multiprocessing „spawn“) importieren dieses
# Modul erneut als „__mp_main__“ – dann darf kein Fenster starten.
if __name__ == "__main__":
    from .start import main
    sys.exit(main())
