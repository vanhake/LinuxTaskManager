"""Sprachumschaltung Deutsch/Englisch.

Quelltexte sind deutsch; _() liefert in Englisch die Übersetzung aus
locale_en.EN (oder den Originaltext, falls keine existiert).
setup() muss vor dem Import der übrigen Module aufgerufen werden, weil
viele Texte bereits beim Import (Konstanten, Spaltentitel) ausgewertet werden.
"""

import os

LANGUAGES = [("auto", "Automatisch (System)"), ("de", "Deutsch"), ("en", "English")]

LANG = "de"
_table = None


def system_language():
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        v = os.environ.get(var)
        if v:
            return "de" if v.lower().startswith("de") else "en"
    return "en"


def setup(choice="auto"):
    global LANG, _table
    LANG = system_language() if choice not in ("de", "en") else choice
    if LANG == "en":
        from .locale_en import EN
        _table = EN
    else:
        _table = None
    return LANG


def _(text):
    if _table is None:
        return text
    return _table.get(text, text)


def C_(context, text):
    """Übersetzung mit Kontext, wenn dasselbe deutsche Wort im Englischen
    unterschiedlich heißt (z. B. „Benutzer“ = Seite „Users“ / Spalte „User“)."""
    if _table is None:
        return text
    return _table.get(f"{context}|{text}", _table.get(text, text))


def is_en():
    return LANG == "en"
