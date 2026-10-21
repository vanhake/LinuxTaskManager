# Umsetzungsplan – Linux Taskmanager

## Technologieentscheidung

| Bereich | Wahl | Begründung |
|---------|------|------------|
| Sprache | Python 3.10 | auf Mint vorinstalliert, schnelle Entwicklung |
| Oberfläche | GTK 3 über PyGObject | native Optik unter Cinnamon, vorinstalliert |
| Graphen | Cairo (Gtk.DrawingArea) | keine Zusatzbibliothek nötig |
| Systemdaten | `psutil` + direkt `/proc`, `/sys` | psutil vorinstalliert; `/sys` für GPU, Datenträgertyp, Taktrate |
| Fenster → App-Zuordnung | `libwnck` (Wnck 3.0) | liefert Fenster mit PID unter X11 |
| Dienste | `systemctl` | Standard unter Mint |
| Root-Aktionen | `pkexec` | grafische Passwortabfrage, kein Start als root nötig |

## Architektur

```
taskmanager/
├── __main__.py        Einstieg: python3 -m taskmanager
├── app.py             Gtk.Application, Hauptfenster, Menü, Tabs, Statuszeile
├── sampler.py         Hintergrund-Thread: misst System + Prozesse → Snapshot
├── sysinfo.py         Statische Hardwareinfos (CPU-Modell, Caches, Datenträger, GPU, Netzwerk)
├── util.py            Formatierung (deutsche Zahlen, Bytes, Raten, Dauer)
├── settings.py        JSON-Einstellungen
├── history.py         App-Verlauf (kumulierte Werte, persistent)
├── treesync.py        Inkrementelles Aktualisieren von TreeStore/ListStore (Auswahl bleibt erhalten)
├── actions.py         Prozessaktionen (beenden, Priorität, Eigenschaften, Kontextmenü)
├── icons.py           Prozess → Symbol (über .desktop-Dateien)
├── widgets.py         Graph, Speicherbalken, Heatmap-Zellen
└── tabs/
    ├── processes.py   Prozesse
    ├── performance.py Leistung
    ├── apphistory.py  App-Verlauf
    ├── startup.py     Autostart
    ├── users.py       Benutzer
    ├── details.py     Details
    └── services.py    Dienste
```

**Datenfluss:** `Sampler` (Thread) → `Snapshot` (reine Daten) → `GLib.idle_add` → Hauptfenster verteilt an
(a) Leistungs-Historie und App-Verlauf (immer) und (b) den sichtbaren Tab (nur dieser baut seine Tabelle neu auf).
Beim Tabwechsel wird der letzte Snapshot sofort angewendet. So bleibt die Last gering.

**Inkrementelle Tabellen:** Jede Zeile hat einen Schlüssel (z. B. `p:1234`). `TreeSync` vergleicht den
Soll-Zustand mit dem vorhandenen Modell: neue Zeilen einfügen, verschwundene löschen, geänderte Werte setzen.
Dadurch bleiben Auswahl, Scrollposition und aufgeklappte Apps erhalten.

## Umsetzungsschritte

1. **Grundlagen** – `util.py`, `settings.py`; Formatierungsfunktionen mit deutschem Zahlenformat.
2. **Datensammlung** – `sampler.py`: CPU gesamt/pro Kern, Takt (sysfs), Temperatur, RAM/Swap/Commit
   (`/proc/meminfo`), Datenträger (Rate, aktive Zeit über `busy_time`, Antwortzeit), Netzwerk je Adapter,
   GPU (AMD `gpu_busy_percent`, NVIDIA `nvidia-smi`, Intel Taktrate), Prozesse (CPU % selbst berechnet aus
   CPU-Zeit-Differenzen, privater Speicher = RSS − Shared, E/A-Raten, Threads, Handles).
3. **Statische Infos** – `sysinfo.py`: `lscpu` (mit `LC_ALL=C`), `/sys/block`, `lspci`, `/proc/swaps`, Mounts.
4. **Widgets** – Verlaufsgraph mit mitlaufendem Gitter, Füllung, 2 Serien (durchgezogen/gestrichelt),
   Auto-Skalierung; Mini-Graph für Seitenleiste; Speicherzusammensetzungsbalken; Heatmap-Zellfärbung.
5. **Tabellen-Infrastruktur** – `treesync.py`, `icons.py`, `actions.py` (gemeinsames Kontextmenü,
   Fallback auf `pkexec kill/renice` bei fehlenden Rechten, Eigenschaftsdialog).
6. **Tabs** in der Reihenfolge: Prozesse → Leistung → Details → Benutzer → App-Verlauf → Autostart → Dienste.
7. **Hauptfenster** – Menü, Tastenkürzel, Statuszeile, Einstellungen laden/speichern, Einzelinstanz.
8. **Installation** – `taskmanager.sh` (Start), `install.sh` (Starter in `~/.local/share/applications`,
   Link in `~/.local/bin`, optional Cinnamon-Tastenkürzel Strg+Umschalt+Esc).
9. **Test** – Start, alle Tabs durchklicken, Prozess beenden (Testprozess `sleep`), Priorität ändern,
   Autostart umschalten, Last messen; Fehlerfälle (fremder Prozess, verschwundener Prozess).

## Risiken und Lösungen

| Risiko | Lösung |
|--------|--------|
| Fremde Prozesse liefern keine E/A-/Handle-Daten | Anzeige „–“, kein Fehler |
| Wayland: Wnck findet keine Fenster | Fallback: keine „Apps“-Gruppe, alles unter Hintergrund/System |
| PID-Wiederverwendung | Prozess-Schlüssel intern (PID, Startzeit) |
| GTK nicht threadsicher | Thread liefert nur Daten, GTK-Zugriffe ausschließlich im Hauptthread |
| pkexec-Dialog blockiert | asynchron über `Gio.Subprocess` |

---

# Version 2 – TMOG-Stil

| Baustein | Datei | Umsetzung |
|----------|-------|-----------|
| Farbschemata | `theme.py` | Paletten als Farbschlüssel (`cpu`, `mem`, …); GTK-CSS wird aus der Palette erzeugt; Widgets lösen Farben bei jedem Zeichnen auf → Themenwechsel ohne Neustart |
| Widgets | `widgets.py` | Graph mit Glow und Bézier-Glättung, animierte Ringanzeige (`RingGauge`), Füllstandsbalken (`UsageBar`), Squarified-Treemap, Kachel-Helfer |
| Übersicht | `tabs/overview.py` | Dashboard-Raster (4 Spalten); wird wie „Leistung“ immer versorgt, damit Verläufe lückenlos sind |
| Speicherplatz | `tabs/storage.py` | Belegung aus dem Sampler (alle 5 Messungen); Ordnerscan in eigenem Thread (`os.scandir`, belegte Blöcke, bleibt auf einem Dateisystem, je Ordner die 40 größten Dateien einzeln) |
| Verbindungen | `tabs/connections.py` | `psutil.net_connections`, alle 2 s solange sichtbar |
| Energie | `sampler.py` | `/sys/class/power_supply/BAT*` (power_now bzw. current_now × voltage_now) |
| Mini-Modus | `mini.py` | rahmenloses, transparentes Fenster mit Balken und Netzgraph |
| Navigation | `app.py` | HeaderBar + Seitenleiste (ListBox) + Gtk.Stack, Menü mit Farbschema/Aktualisierung |

Gemessene Eigenlast (Übersicht sichtbar, Normal): ca. 2 % Gesamt-CPU, 69 MB RAM.

# Version 2.1 – Flight Recorder

| Baustein | Datei | Umsetzung |
|----------|-------|-----------|
| Aufzeichnung | `recorder.py` → `Recorder` | erhält jeden Snapshot, schreibt über eine Queue in einen eigenen Writer-Thread (Commit alle 2 s, SQLite im WAL-Modus); Prozesse werden 5 s gemittelt; Ereigniserkennung mit Hysterese (einmal auslösen, erst nach Entspannung erneut) |
| Sperre | `recorder.lock` + `flock` | genau ein Schreiber; andere Prozesse versuchen alle 30 s zu übernehmen (z. B. Dienst übernimmt, wenn das Fenster geschlossen wird) |
| Lesen | `Reader` | Zeitraum wird in Abschnitte (≈ Pixelbreite/3) gruppiert, je Abschnitt der **Spitzenwert** (`MAX`), damit kurze Spitzen sichtbar bleiben; Lücken bleiben leer |
| Oberfläche | `tabs/flight.py` | `Timeline`-Widget (Cairo), Abspiel-Timer (100 ms), Zustandskacheln, Prozess- und Ereignisliste |
| Dienst | `python3 -m taskmanager --recorder` | kopflos mit `GLib.MainLoop`, Messintervall 2 s, sauberes Beenden bei SIGTERM/SIGINT; Autostart-Datei `~/.config/autostart/linux-taskmanager-recorder.desktop` |

Datenmenge: ca. 100 Byte je Messwert + 30 Prozesszeilen je 5 s → rund 15–25 MB pro Tag bei 1-s-Messung.
Gemessene Last des Hintergrunddienstes: ca. 0,75 % Gesamt-CPU, 22 MB RAM.

# Version 2.2 – CPU-Benchmark

| Baustein | Datei | Umsetzung |
|----------|-------|-----------|
| Testlasten & Ablauf | `benchmark.py` | `multiprocessing` mit Startmethode **spawn** (sicher neben GTK-Threads); Pool-Prozesse werden vorab hochgefahren, alle Tests starten zeitgleich (`start_at`); gezählt werden Durchläufe pro Sekunde; Abbruch über gemeinsames `Event` |
| Kalibrierung | `TESTS` | Referenz-Durchläufe/s auf einem Kern des i5-4300M: Ganzzahl 400, Gleitkomma 105, SHA-256 375, zlib 66, Sortieren 44 |
| Oberfläche | `tabs/benchmark.py` | Punktekarten mit Hochzähl-Animation, Live-Graphen aus den normalen Messdaten, Einzeltest-Balken, Verlauf (`~/.local/share/linux-taskmanager/benchmarks.json`) |
| Drosselung | `_summary()` | Ø-Takt unter Last < 90 % des Basistakts → „Takt unter Basistakt“; Takt der letzten 5 s < 85 % der ersten 5 s bei ≥ 85 °C → „Thermisch gedrosselt“ |
| Schutz | `__main__.py` | spawn importiert das Hauptmodul erneut als `__mp_main__` – ohne `if __name__ == "__main__"` würde jedes Arbeitsprozess ein Fenster öffnen |

Ergebnis auf dem Entwicklungsrechner (Schnell): Single-Core 999, Multi-Core 1.940 (×1,94; 2 Kerne/4 Threads), max. 76 °C, keine Drosselung.

# Version 2.3 – Englisch

| Baustein | Umsetzung |
|----------|-----------|
| `i18n.py` | `_()` liefert den deutschen Quelltext oder die englische Übersetzung; `C_(kontext, text)` für Wörter mit mehreren Bedeutungen (z. B. „Benutzer“ = *Users*/*User*) |
| Umstellung | Ein Skript hat per Python-AST alle sichtbaren Texte in `_()` gehüllt und f-Strings in Vorlagen umgewandelt (`f"{n} Prozesse"` → `_("{0} Prozesse").format(n)`) – rund 600 Texte |
| `locale_en.py` | Wörterbuch Deutsch → Englisch; automatische Prüfung, dass Platzhalter und Tastenkürzel (`_`) übereinstimmen |
| Start | `__main__.py` setzt die Sprache **vor** dem Import der übrigen Module, weil viele Texte beim Import ausgewertet werden |
| Wechsel | Einstellung speichern, sauber beenden, `os.execv` startet das Programm im selben Prozess neu |
| Stolperfallen | `_` war vorher als Platzhaltervariable benutzt (`for x, _ in …`) und überdeckte die Übersetzungsfunktion → 97 Stellen umbenannt; `.desktop`-Namen werden über `X-GNOME-Gettext-Domain` immer in die Systemsprache übersetzt → im Englischen wird der Originalwert gelesen |
