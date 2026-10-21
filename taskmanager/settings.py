"""Persistente Einstellungen als JSON."""

import json
import os

CONFIG_DIR = os.path.join(os.path.expanduser("~/.config"), "linux-taskmanager")
DATA_DIR = os.path.join(os.path.expanduser("~/.local/share"), "linux-taskmanager")
_PATH = os.path.join(CONFIG_DIR, "settings.json")

DEFAULTS = {
    "width": 980,
    "height": 680,
    "maximized": False,
    "page": "overview",
    "theme": "Neon",
    "language": "auto",
    "mini_pos": None,
    "interval": 1.0,
    "paused": False,
    "always_on_top": False,
    "group_by_type": True,
    "details_hidden_columns": ["PPID", "Virtuell", "Pfad", "Gestartet"],
    "users_show_all": False,
    "services_user": False,
    "fr_enabled": True,
    "fr_retention_h": 24,
    "fr_daemon_interval": 2.0,
}


class Settings(dict):
    def __init__(self):
        super().__init__(DEFAULTS)
        try:
            with open(_PATH) as f:
                self.update(json.load(f))
        except (OSError, ValueError):
            pass

    def save(self):
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            tmp = _PATH + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self, f, indent=2)
            os.replace(tmp, _PATH)
        except OSError:
            pass
