# Anforderungsliste – Linux Taskmanager (Windows-Taskmanager-Nachbau für Linux Mint)

Ziel: Ein grafisches Tool, das unter Linux Mint (Cinnamon, X11) dieselben Informationen
und Funktionen bereitstellt wie der Windows-Taskmanager (Windows 10/11), in deutscher Sprache.

Legende: **M** = Muss, **S** = Soll, **K** = Kann · ✅ umgesetzt · ⚠️ eingeschränkt umgesetzt · ❌ unter Linux nicht möglich / bewusst weggelassen

## 1. Allgemein / Rahmenbedingungen

| ID | Anforderung | Prio | Status |
|----|-------------|------|--------|
| A1 | Läuft auf Linux Mint 21.x ohne Installation zusätzlicher Pakete (Python 3, GTK 3, psutil, Wnck sind vorinstalliert) | M | ✅ |
| A2 | Deutsche Oberfläche, deutsches Zahlenformat (Komma als Dezimaltrenner) | M | ✅ |
| A3 | Registerkarten wie in Windows: Prozesse, Leistung, App-Verlauf, Autostart, Benutzer, Details, Dienste | M | ✅ |
| A4 | Aktualisierungsgeschwindigkeit wählbar: Hoch (0,5 s), Normal (1 s), Niedrig (4 s), Angehalten; „Jetzt aktualisieren“ (F5) | M | ✅ |
| A5 | Datensammlung in einem Hintergrund-Thread, Oberfläche bleibt flüssig | M | ✅ |
| A6 | Läuft als normaler Benutzer; Aktionen, die Root-Rechte brauchen, werden per `pkexec` (Passwortabfrage) ausgeführt | M | ✅ |
| A7 | Nur eine Instanz; erneuter Start holt das vorhandene Fenster nach vorn | S | ✅ |
| A8 | Menü: Datei (Neuen Task ausführen, Beenden), Optionen (Immer im Vordergrund), Ansicht (Aktualisierung, Gruppieren nach Typ) | S | ✅ |
| A9 | Einstellungen (Fenstergröße, Tab, Geschwindigkeit, Spalten) werden gespeichert | S | ✅ |
| A10 | Starter im Anwendungsmenü; optional Tastenkürzel Strg+Umschalt+Esc | S | ✅ (install.sh) |
| A11 | Statuszeile mit Prozessanzahl, CPU- und Speicherauslastung | K | ✅ |
| A12 | Tastatur: Entf = Task beenden, Strg+F = Suche, F5 = Aktualisieren, Strg+N = Neuer Task | S | ✅ |

## 2. Registerkarte „Prozesse“

| ID | Anforderung | Prio | Status |
|----|-------------|------|--------|
| P1 | Gruppierung „Apps“ (Prozesse mit sichtbarem Fenster), „Hintergrundprozesse“ (eigene Prozesse), „Systemprozesse“ (andere Benutzer/Root) | M | ✅ |
| P2 | Apps aufklappbar: Kindprozesse einer App werden darunter angezeigt, Werte der App summiert | M | ✅ |
| P3 | Spalten: Name (mit Symbol), PID, Status, CPU, Arbeitsspeicher, Datenträger, Benutzer | M | ✅ |
| P4 | Spaltenköpfe zeigen Gesamtauslastung (z. B. „23 % CPU“) | S | ✅ |
| P5 | Farbliche Hervorhebung hoher Werte (Heatmap wie Windows) | S | ✅ |
| P6 | Sortierung per Klick auf Spaltenkopf; Gruppen bleiben in fester Reihenfolge | M | ✅ |
| P7 | Suchfeld zum Filtern | S | ✅ |
| P8 | „Task beenden“ (SIGTERM) per Button, Entf-Taste und Kontextmenü | M | ✅ |
| P9 | Kontextmenü: Task beenden, Beenden erzwingen (SIGKILL), Prozessbaum beenden, Priorität festlegen, Dateispeicherort öffnen, Online suchen, Eigenschaften, Zu Details wechseln | M | ✅ |
| P10 | Gruppierung abschaltbar (flache Liste) | K | ✅ |
| P11 | Netzwerk pro Prozess | K | ❌ nur mit Root/Kernel-Tracing möglich (z. B. nethogs) |
| P12 | GPU und Energieverbrauch pro Prozess | K | ❌ unter Linux für Intel/AMD nicht ohne Root verfügbar |
| P13 | Datenträger-Rate fremder Prozesse | K | ⚠️ Kernel gibt E/A-Zähler nur für eigene Prozesse frei |

## 3. Registerkarte „Leistung“

| ID | Anforderung | Prio | Status |
|----|-------------|------|--------|
| L1 | Seitenleiste mit Geräten und Mini-Verlaufsgraphen: CPU, Arbeitsspeicher, je Datenträger, je Netzwerkadapter, je GPU | M | ✅ |
| L2 | Großer Verlaufsgraph (60 Messpunkte) mit Gitter, Füllung und Skala | M | ✅ |
| L3 | **CPU**: Auslastung, Geschwindigkeit, Prozesse, Threads, Handles, Betriebszeit, Basisgeschwindigkeit, Sockets, Kerne, logische Prozessoren, Virtualisierung, L1/L2/L3-Cache, Modellname | M | ✅ |
| L4 | CPU-Graph umschaltbar auf „Logische Prozessoren“ (ein Graph pro Kern) | S | ✅ |
| L5 | CPU-Temperatur (Linux-Extra) | K | ✅ |
| L6 | **Arbeitsspeicher**: In Verwendung, Verfügbar, Zugesichert, Im Cache, Auslagerung (Swap), Puffer, Gemeinsam genutzt, Speicherzusammensetzung als Balken | M | ✅ |
| L7 | RAM-Geschwindigkeit, Steckplätze, Formfaktor | K | ❌ nur per `dmidecode` mit Root |
| L8 | **Datenträger**: Aktive Zeit %, durchschnittliche Antwortzeit, Lese-/Schreibgeschwindigkeit, Kapazität, Formatiert, Systemdatenträger, Auslagerung, Typ (SSD/HDD), Modell; zwei Graphen | M | ✅ |
| L9 | **Netzwerk**: Senden/Empfangen (Kbit/s/Mbit/s), Durchsatz-Graph, Adaptername, Verbindungstyp (Ethernet/WLAN), SSID, IPv4, IPv6, Verbindungsgeschwindigkeit | M | ✅ |
| L10 | **GPU**: Name, Treiber, Auslastung (AMD: direkt, NVIDIA: nvidia-smi, Intel: geschätzt über Taktrate), VRAM falls verfügbar, Temperatur | S | ⚠️ Intel nur Taktrate-Schätzung |
| L11 | Graphen in Gerätefarben wie Windows (CPU blau, RAM lila, Datenträger grün, Netzwerk orange) | K | ✅ |

## 4. Registerkarte „App-Verlauf“

| ID | Anforderung | Prio | Status |
|----|-------------|------|--------|
| H1 | Kumulierte Ressourcennutzung je Programm: CPU-Zeit, Datenträger gelesen/geschrieben | M | ✅ |
| H2 | „Ressourcennutzung seit …“ und „Verlauf löschen“ | M | ✅ |
| H3 | Verlauf bleibt über Neustarts des Tools erhalten (gespeichert in `~/.local/share/linux-taskmanager/`) | S | ✅ |
| H4 | Erfasst wird nur, solange das Tool läuft (Windows erfasst dauerhaft per Dienst) | – | ⚠️ |

## 5. Registerkarte „Autostart“

| ID | Anforderung | Prio | Status |
|----|-------------|------|--------|
| S1 | Liste aller Autostart-Einträge aus `/etc/xdg/autostart` und `~/.config/autostart` (Benutzer überschreibt System), gefiltert auf die aktuelle Desktopumgebung | M | ✅ |
| S2 | Spalten: Name (mit Symbol), Beschreibung, Status, Verzögerung, Befehl, Quelle | M | ✅ |
| S3 | Aktivieren/Deaktivieren (wie Cinnamon: Kopie in `~/.config/autostart` mit `X-GNOME-Autostart-enabled`) | M | ✅ |
| S4 | Neuen Eintrag hinzufügen, eigenen Eintrag entfernen, Dateispeicherort öffnen | S | ✅ |
| S5 | „Startauswirkung“ | K | ❌ keine Messdaten unter Linux |

## 6. Registerkarte „Benutzer“

| ID | Anforderung | Prio | Status |
|----|-------------|------|--------|
| U1 | Angemeldete Benutzer mit summierter CPU-, Speicher- und Datenträgernutzung | M | ✅ |
| U2 | Aufklappbar: Prozesse des Benutzers | M | ✅ |
| U3 | Sitzungsinfo (Terminal/Anzeige, Anmeldezeit) | S | ✅ |
| U4 | Option: alle Benutzer mit Prozessen anzeigen (root, Systemkonten) | K | ✅ |

## 7. Registerkarte „Details“

| ID | Anforderung | Prio | Status |
|----|-------------|------|--------|
| D1 | Flache Liste aller Prozesse | M | ✅ |
| D2 | Spalten: Name, PID, PPID, Status, Benutzer, CPU, CPU-Zeit, Arbeitsspeicher (privat), RSS, Virtuell, Threads, Handles, Priorität, Lesen/s, Schreiben/s, Gestartet, Pfad, Befehlszeile | M | ✅ |
| D3 | Spalten ein-/ausblendbar („Spalten auswählen“) | S | ✅ |
| D4 | Kontextmenü wie Prozesse, zusätzlich Anhalten (SIGSTOP) / Fortsetzen (SIGCONT) | S | ✅ |
| D5 | Suche/Filter | S | ✅ |

## 8. Registerkarte „Dienste“

| ID | Anforderung | Prio | Status |
|----|-------------|------|--------|
| V1 | Liste der systemd-Dienste: Name, PID, Beschreibung, Status, Starttyp | M | ✅ |
| V2 | Umschalten System-/Benutzerdienste | S | ✅ |
| V3 | Starten, Beenden, Neu starten, Autostart aktivieren/deaktivieren (System per pkexec) | M | ✅ |
| V4 | Filter nach Name/Beschreibung, Filter „nur laufende“ | S | ✅ |

## 9. Nicht-funktionale Anforderungen

| ID | Anforderung | Prio |
|----|-------------|------|
| N1 | Eigene CPU-Last bei „Normal“ < ca. 3 % auf einem Dual-Core | S |
| N2 | Kein Absturz bei verschwindenden Prozessen, fehlenden Rechten oder fehlender Hardware (z. B. keine GPU-Daten) | M |
| N3 | Auswahl und Aufklappzustand bleiben bei Aktualisierung erhalten | M |
| N4 | Funktioniert mit hellen und dunklen Themes | S |
| N5 | Code modular (Datensammlung getrennt von Oberfläche) | S |

---

# Version 2 – Erweiterung im Stil von TMOG

Wunsch: mehr wie [TMOG](https://www.omgubuntu.co.uk/2026/09/tmog-task-manager-linux-beta) (Task Manager OG von Dave Plummer):
modernes Neon-Design, Startseite mit Kurzübersicht, Festplattenbelegung.

| ID | Anforderung | Prio | Status |
|----|-------------|------|--------|
| T1 | Modernes dunkles Design mit leuchtenden Graphen (Glow, Verlaufsfüllung, geglättete Kurven) | M | ✅ |
| T2 | Farbschemata umschaltbar: Neon, Synthwave, Matrix, Amber, Hell – wirkt sofort, wird gespeichert | S | ✅ |
| T3 | Seitenleiste mit Symbolen statt Reitern, Kopfleiste mit Live-Werten (CPU, RAM, Prozesse, Betriebszeit) | S | ✅ |
| T4 | **Startseite „Übersicht“**: Ringanzeigen CPU/RAM/GPU/Energie, Auslastung je Kern, Netzwerk- und Datenträger-Graph, Festplattenbelegung, Top-Prozesse (CPU/RAM/Datenträger), Systeminfos | M | ✅ |
| T5 | **Festplattenbelegung**: alle echten Dateisysteme mit Füllstandsbalken, Warnfarbe ab 80 %, kritisch ab 92 % | M | ✅ |
| T6 | **Ordneranalyse** (Seite „Speicherplatz“): belegter Platz je Ordner als Treemap und Liste, Klick zum Hineinzoomen, Zurück, im Dateimanager öffnen, abbrechbar | M | ✅ |
| T7 | **Energie**: Akkustand, Lade-Status, Leistungsaufnahme in Watt, Restzeit, Akkuzustand | S | ✅ |
| T8 | **Netzwerkverbindungen** je Prozess (Protokoll, Adressen, Status, Filter) | S | ✅ |
| T9 | **Mini-Modus**: kleines rahmenloses Fenster, immer im Vordergrund, verschiebbar (Strg+M) | S | ✅ |
| T10 | 60-Hz-Aktualisierung wie TMOG | K | ❌ in Python zu teuer; Ringanzeigen werden aber flüssig animiert |
| T11 | CPU-Benchmark | K | ✅ (Version 2.2, siehe unten) |

## Flight Recorder (Version 2.1)

| ID | Anforderung | Prio | Status |
|----|-------------|------|--------|
| F1 | Laufende Aufzeichnung der Systemwerte (CPU, RAM, Swap, Datenträger, Netzwerk, GPU, Temperatur, Takt, Akku/Watt, Last, Prozessanzahl) bei jeder Messung | M | ✅ |
| F2 | Schnappschuss der Top-Prozesse (je 10 nach CPU, RAM, E/A; über 5 s gemittelt) | M | ✅ |
| F3 | Automatische Ereignisse: CPU-Spitze (≥ 90 % für 5 s, mit Verursacher), RAM knapp, Hitze, Datenträger ausgelastet, starke Auslagerung, Prozess mit Dauerlast, Netzteil an/ab, Akku fast leer, Laufwerk fast voll | S | ✅ |
| F4 | Zeitleiste mit Spuren je Messgröße (Spitzenwerte), Ereignismarken, Zeitachse; Klicken/Ziehen = Zeitpunkt wählen, Mausrad = Zoom, Umschalt+Mausrad = Verschieben | M | ✅ |
| F5 | Zeiträume 5 min / 15 min / 1 h / 6 h / 24 h / Alles, LIVE-Modus | M | ✅ |
| F6 | Abspielen mit 1×/10×/60×/300×, Schritt vor/zurück, Sprung zum vorigen/nächsten Ereignis | S | ✅ |
| F7 | Zustand zum gewählten Zeitpunkt: alle Werte + Prozessliste + Ereignisliste (anklickbar) | M | ✅ |
| F8 | Speicherung in SQLite (`~/.local/share/linux-taskmanager/flight.db`), Aufbewahrung 1 h – 7 Tage, Löschen, CSV-Export | S | ✅ |
| F9 | Hintergrunddienst (`--recorder`) für Aufzeichnung ohne offenes Fenster, per Autostart zuschaltbar; nur ein Prozess schreibt (Dateisperre), die Oberfläche liest dann mit | S | ✅ |
| F10 | Aufzeichnung pausierbar; REC-Anzeige in der Kopfleiste | K | ✅ |

## CPU-Benchmark (Version 2.2)

| ID | Anforderung | Prio | Status |
|----|-------------|------|--------|
| B1 | Fünf Testlasten: Ganzzahl (Primzahlsieb), Gleitkomma (Mandelbrot), Kryptografie (SHA-256), Kompression (zlib), Sortieren | M | ✅ |
| B2 | Messung Single-Core (1 Prozess) und Multi-Core (1 Prozess je Thread, gleichzeitig gestartet) | M | ✅ |
| B3 | Punktwerte relativ zur Referenz (i5-4300M, ein Kern = 1000), Gesamtwert = geometrisches Mittel, Skalierungsfaktor | M | ✅ |
| B4 | Modi Schnell / Standard / Gründlich (1,5 / 3 / 6 s je Test), abbrechbar | S | ✅ |
| B5 | Live-Anzeige CPU-Auslastung, Temperatur, Takt; Max.-Temperatur, Takt unter Last, Drosselungserkennung, Stromversorgung | S | ✅ |
| B6 | Belastungstest: Volllast auf allen Threads bis zum Stopp (Kühlung/Stabilität) | S | ✅ |
| B7 | Ergebnisverlauf (gespeichert), Vergleich mit Bestwert, Löschen einzelner Läufe | S | ✅ |
| B8 | Ereignisse im Flight Recorder (Benchmark/Belastungstest gestartet, Ergebnis) | K | ✅ |
| B9 | Oberfläche bleibt während des Tests bedienbar (Arbeitsprozesse mit Nice 5) | M | ✅ |
