"""App-Verlauf: kumulierte CPU-Zeit und Datenträger-E/A je Programm."""

import json
import os
import time

from .settings import DATA_DIR

_PATH = os.path.join(DATA_DIR, "app_history.json")


class AppHistory:
    def __init__(self):
        self.since = time.time()
        self.data = {}  # name -> [cpu_s, read_b, write_b, user]
        self._last_save = time.monotonic()
        self.dirty = False
        try:
            with open(_PATH) as f:
                raw = json.load(f)
            self.since = raw.get("since", self.since)
            self.data = {k: list(v) for k, v in raw.get("apps", {}).items()}
        except (OSError, ValueError):
            pass

    def add(self, snapshot):
        data = self.data
        for p in snapshot.procs.values():
            if not (p.cpu_delta or p.read_delta or p.write_delta):
                continue
            e = data.get(p.name)
            if e is None:
                e = data[p.name] = [0.0, 0, 0, p.user]
            e[0] += p.cpu_delta
            e[1] += p.read_delta or 0
            e[2] += p.write_delta or 0
            self.dirty = True
        if time.monotonic() - self._last_save > 60:
            self.save()

    def reset(self):
        self.data = {}
        self.since = time.time()
        self.dirty = True
        self.save()

    def save(self):
        self._last_save = time.monotonic()
        if not self.dirty:
            return
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            tmp = _PATH + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"since": self.since, "apps": self.data}, f)
            os.replace(tmp, _PATH)
            self.dirty = False
        except OSError:
            pass
