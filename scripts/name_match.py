"""Shared name-normalization helper for matching players across data
sources that don't share a common ID (ESPN <-> nflverse). Sleeper has an
explicit espn_id field so it doesn't need this."""

import re

_SUFFIXES = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b")
_PUNCT = re.compile(r"[.'\-]")
_WS = re.compile(r"\s+")


def normalize_name(name):
    if not name:
        return ""
    s = name.lower()
    s = _PUNCT.sub(" ", s)
    s = _SUFFIXES.sub(" ", s)
    s = _WS.sub(" ", s).strip()
    return s


def player_key(name, position):
    return f"{normalize_name(name)}|{position}"
