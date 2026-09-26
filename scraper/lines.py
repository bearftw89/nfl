"""Shared helpers for reading point spreads and game rows off Westgate cards.

Westgate isn't consistent about how it prints a line: "+3.5", "+3½", "+.5", "+½",
"PK", "PICK", "EVEN", and sometimes a unicode minus or en dash. Every card parser
uses LINE / to_float from here so a new format only has to be handled once.
"""
import re

_SIGN = r"[+\-\u2212\u2013]"
# Longer words first so "PICK" isn't read as "P" + junk.
LINE = rf"(?:PICK|PK|EVEN|EV|P|{_SIGN}?(?:\d+(?:\.\d+|½)?|\.\d+|½))"
_PK = {"PICK", "PK", "EVEN", "EV", "P"}


def to_float(tok):
    """'+3½' -> 3.5, '-.5' -> -0.5, 'PK' -> 0.0. None if it isn't a line."""
    t = (tok or "").strip().upper().replace("\u2212", "-").replace("\u2013", "-")
    if t in _PK:
        return 0.0
    if not re.fullmatch(rf"{_SIGN}?(?:\d+(?:\.\d+|½)?|\.\d+|½)", t):
        return None
    neg = t.startswith("-")
    t = t.lstrip("+-")
    if t.endswith("½"):
        t = (t[:-1] or "0") + ".5"
    v = float(t)
    return -v if neg else v


# Last-resort row reader: any characters in the team names, and whatever single token
# ends the row is taken as the line (kept only if to_float can read it).
LENIENT = re.compile(
    r"^[ \t]*(?P<n1>\d{1,3})[ \t]+(?P<t1>[^\n]+?)(?P<h1>\*?)[ \t]+(?:@(?P<site>[^\n]*?)[ \t]+)?"
    r"(?P<time>\d{1,2}:\d{2}[ \t]*[AP]M)[ \t]+"
    r"(?P<n2>\d{1,3})[ \t]+(?P<t2>[^\n]+?)(?P<h2>\*?)[ \t]+(?P<line>\S+)[ \t]*$", re.M)

# Anything that looks like a game row: rotation number ... time.
_ROW = re.compile(r"^[ \t]*(\d{1,3})[ \t]+\S[^\n]*?\d{1,2}:\d{2}[ \t]*[AP]M[^\n]*$", re.M)


def card_matches(strict, text):
    """Strict regex matches, plus lenient ones for rows the strict regex missed, in sheet order."""
    ms = list(strict.finditer(text))
    got = {int(m["n1"]) for m in ms}
    for m in LENIENT.finditer(text):
        if int(m["n1"]) not in got and to_float(m["line"]) is not None:
            ms.append(m)
            got.add(int(m["n1"]))
    return sorted(ms, key=lambda m: m.start())


def missed_rows(text, games):
    """Raw text of game-looking rows that didn't make it into `games`."""
    nums = {g[s]["num"] for g in games for s in ("fav", "dog")}
    return [m.group(0).strip() for m in _ROW.finditer(text.upper()) if int(m.group(1)) not in nums]
