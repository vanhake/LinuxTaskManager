"""Inkrementelles Abgleichen eines TreeStore/ListStore mit einem Soll-Zustand.

Zeilen werden über einen Schlüssel identifiziert. Unveränderte Zeilen werden
nicht angefasst, dadurch bleiben Auswahl, Scrollposition und der
Aufklappzustand erhalten und die Sortierung muss nicht neu laufen.
"""

from collections import defaultdict

from gi.repository import Gtk


class TreeSync:
    def __init__(self, store):
        self.store = store
        self.is_tree = isinstance(store, Gtk.TreeStore)
        self.cols = list(range(store.get_n_columns()))
        self.iters = {}
        self.parent = {}
        self.values = {}
        self.children = defaultdict(set)

    def sync(self, rows):
        """rows: Liste von (key, parent_key|None, values); Eltern vor Kindern."""
        desired = {k: p for k, p, _x in rows}
        for k in list(self.iters):
            if k in self.iters and (k not in desired or desired[k] != self.parent[k]):
                self._remove(k)
        store = self.store
        for k, p, vals in rows:
            it = self.iters.get(k)
            if it is None:
                # insert_with_values* stürzt in PyGObject 3.42 bei None-Objekten ab,
                # daher die Python-Overrides insert(..., row)
                if self.is_tree:
                    parent_it = self.iters.get(p) if p is not None else None
                    it = store.insert(parent_it, -1, vals)
                else:
                    it = store.insert(-1, vals)
                self.iters[k] = it
                self.parent[k] = p
                self.values[k] = vals
                self.children[p].add(k)
            elif self.values[k] != vals:
                old = self.values[k]
                changed = [i for i, (a, b) in enumerate(zip(old, vals)) if a != b]
                store.set(it, changed, [vals[i] for i in changed])
                self.values[k] = vals

    def _remove(self, key):
        it = self.iters.get(key)
        if it is None:
            return
        self.store.remove(it)
        stack = [key]
        while stack:
            k = stack.pop()
            self.iters.pop(k, None)
            self.values.pop(k, None)
            p = self.parent.pop(k, None)
            self.children[p].discard(k)
            stack.extend(self.children.pop(k, ()))

    def clear(self):
        self.store.clear()
        self.iters.clear()
        self.parent.clear()
        self.values.clear()
        self.children.clear()
