"""Parse text extracted from Westgate SuperContest PDFs.

Each parser takes plain text (one PDF page's worth or the whole doc joined)
and returns plain dicts ready for JSON. They're line-based and ignore any
line that doesn't match, so headers/footers/page breaks fall out naturally.
"""
import re
from .teams import TEAMS, to_abbr

# ---------- Card ----------
# e.g. "3 PACKERS 10:00 AM 4 JETS* +3.5"   (left = favorite, right gets +line)
#      "1 BILLS* 5:15 PM 2 LIONS PK"
# Anchored to the start of a line, and spaces only (never newlines): otherwise the
# "2026" ending a date header glues onto the next game row and that game is lost.
# Anything between the first team and the time (e.g. "@ Melbourne, Australia") is skipped.
_CARD_RE = re.compile(
    r"^[ \t]*(?P<n1>\d{1,3})[ \t]+(?P<t1>[A-Z0-9][A-Z0-9 .']*?)(?P<h1>\*?)[ \t]+(?:@[^\n]*?[ \t]+)?"
    r"(?P<time>\d{1,2}:\d{2}[ \t]*[AP]M)[ \t]+"
    r"(?P<n2>\d{1,3})[ \t]+(?P<t2>[A-Z0-9][A-Z0-9 .']*?)(?P<h2>\*?)[ \t]+"
    r"(?P<line>[+-]?\d+(?:\.\d+)?|PK|P)\b",
    re.M,
)


def parse_card(text: str):
    games = []
    for m in _CARD_RE.finditer(text.upper()):
        a1, a2 = to_abbr(m["t1"]), to_abbr(m["t2"])
        if not a1 or not a2:
            continue
        raw = m["line"]
        dog_line = 0.0 if raw in ("PK", "P") else abs(float(raw))
        games.append({
            "id": len(games) + 1,
            "time_pt": m["time"].replace("  ", " "),
            "fav": {"num": int(m["n1"]), "abbr": a1, "home": bool(m["h1"]), "line": -dog_line},
            "dog": {"num": int(m["n2"]), "abbr": a2, "home": bool(m["h2"]), "line": dog_line},
        })
    return games


# ---------- Selections ----------
# e.g. "ACCORSI - 3 VIKINGS BROWNS TITANS CARDINALS DOLPHINS"
_ENTRY_RE = re.compile(r"^(?P<name>.+?)\s+-\s+(?P<n>\d{1,2})\s+(?P<picks>.+)$")


def parse_selections(text: str):
    entries, seen = [], set()
    for raw in text.splitlines():
        line = raw.strip().upper()
        m = _ENTRY_RE.match(line)
        if not m:
            continue
        tokens = m["picks"].split()
        picks = [to_abbr(t) for t in tokens]
        if not picks or any(p is None for p in picks):
            continue
        eid = f"{m['name'].strip()}-{int(m['n'])}"
        if eid in seen:
            continue
        seen.add(eid)
        entries.append({"id": eid, "picks": picks})
    return entries


# ---------- Standings ----------
# e.g. "14T JEFFREY L-1 4-1-0-0 4.00"
_STAND_RE = re.compile(
    r"^(?P<place>\d+T?)\s+(?P<id>.+-\d{1,2})\s+"
    r"(?P<w>\d+)-(?P<l>\d+)-(?P<t>\d+)-(?P<c>\d+)\s+(?P<pts>\d+(?:\.\d+)?)$"
)


def parse_standings(text: str):
    rows = []
    for raw in text.splitlines():
        m = _STAND_RE.match(raw.strip().upper())
        if not m:
            continue
        rows.append({
            "place": m["place"], "id": m["id"].strip(),
            "w": int(m["w"]), "l": int(m["l"]), "t": int(m["t"]), "c": int(m["c"]),
            "pts": float(m["pts"]),
        })
    return rows
