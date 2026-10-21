#!/bin/bash
# Installiert den Linux-Taskmanager für den aktuellen Benutzer.
#
#   ./install.sh              Starter im Anwendungsmenü + Befehl "taskmanager"
#   ./install.sh --shortcut   zusätzlich Tastenkürzel Strg+Umschalt+Esc (Cinnamon)
#   ./install.sh --uninstall  alles wieder entfernen
set -e

DIR="$(dirname "$(readlink -f "$0")")"
BIN="$HOME/.local/bin/taskmanager"
DESKTOP="$HOME/.local/share/applications/linux-taskmanager.desktop"
KB_SCHEMA="org.cinnamon.desktop.keybindings"
KB_PATH="/org/cinnamon/desktop/keybindings/custom-keybindings"

remove_shortcut() {
    command -v gsettings >/dev/null || return 0
    gsettings list-schemas | grep -qx "$KB_SCHEMA" || return 0
    local list new=""
    list=$(gsettings get "$KB_SCHEMA" custom-list)
    for id in $(echo "$list" | grep -o "'[^']*'" | tr -d "'"); do
        cmd=$(gsettings get "$KB_SCHEMA.custom-keybinding:$KB_PATH/$id/" command 2>/dev/null || true)
        if [[ "$cmd" == *"$BIN"* ]]; then
            gsettings reset-recursively "$KB_SCHEMA.custom-keybinding:$KB_PATH/$id/" || true
            echo "Tastenkürzel $id entfernt"
        else
            new+="'$id', "
        fi
    done
    gsettings set "$KB_SCHEMA" custom-list "[${new%, }]"
}

if [[ "$1" == "--uninstall" ]]; then
    rm -f "$BIN" "$DESKTOP"
    remove_shortcut
    echo "Deinstalliert. Einstellungen/Verlauf liegen weiterhin in ~/.config/linux-taskmanager und ~/.local/share/linux-taskmanager."
    exit 0
fi

chmod +x "$DIR/taskmanager.sh"
mkdir -p "$(dirname "$BIN")" "$(dirname "$DESKTOP")"
ln -sf "$DIR/taskmanager.sh" "$BIN"

cat > "$DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Name=Taskmanager
GenericName=Taskmanager
Comment=Prozesse, Leistung, Autostart, Benutzer und Dienste überwachen
Exec=$BIN
Icon=utilities-system-monitor
Terminal=false
Categories=System;Monitor;GTK;
Keywords=task;manager;prozess;process;cpu;ram;speicher;dienste;
StartupWMClass=Taskmanager
EOF
update-desktop-database "$(dirname "$DESKTOP")" 2>/dev/null || true
echo "Installiert: Befehl 'taskmanager' und Eintrag 'Taskmanager' im Anwendungsmenü."

if [[ "$1" == "--shortcut" ]]; then
    if ! gsettings list-schemas | grep -qx "$KB_SCHEMA"; then
        echo "Cinnamon-Tastenkürzel nicht verfügbar – bitte manuell in den Systemeinstellungen anlegen."
        exit 0
    fi
    remove_shortcut >/dev/null
    list=$(gsettings get "$KB_SCHEMA" custom-list)
    i=0
    while [[ "$list" == *"'custom$i'"* ]]; do i=$((i+1)); done
    id="custom$i"
    gsettings set "$KB_SCHEMA.custom-keybinding:$KB_PATH/$id/" name "Taskmanager"
    gsettings set "$KB_SCHEMA.custom-keybinding:$KB_PATH/$id/" command "$BIN"
    gsettings set "$KB_SCHEMA.custom-keybinding:$KB_PATH/$id/" binding "['<Primary><Shift>Escape']"
    items=$(echo "$list" | sed -e 's/@as //' -e 's/^\[//' -e 's/\]$//')
    if [[ -z "$items" ]]; then
        gsettings set "$KB_SCHEMA" custom-list "['$id']"
    else
        gsettings set "$KB_SCHEMA" custom-list "[$items, '$id']"
    fi
    echo "Tastenkürzel Strg+Umschalt+Esc eingerichtet ($id)."
fi
