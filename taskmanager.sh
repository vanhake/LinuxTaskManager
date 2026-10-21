#!/bin/sh
# Startet den Linux-Taskmanager aus dem Projektordner (auch über Symlink).
DIR="$(dirname "$(readlink -f "$0")")"
cd "$DIR" || exit 1
exec python3 -m taskmanager "$@"
