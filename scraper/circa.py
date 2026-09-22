"""Circa Sports contest parsers: Circa Million (ATS) and Circa Survivor.

Circa Million: 5 picks/week vs Circa's own spread. Selections carry the line inline
  ("3. PACKERS -3½"), so each pick is self-contained — no separate scored card needed.
  Scoring: cover 1, push 0.5, loss 0 (matches the posted standings).

Circa Survivor: one team/week to win straight up (shown as "PK"). Loss eliminates.
  Tie handling is set by grade_tie_is_out (see survivor_grade) — confirm against Circa's rules.
"""
import re
from collections import Counter
from .teams import TEAMS, to_abbr

_ALT = "|".join(re.escape(n) for n in sorted(TEAMS, key=len, reverse=True))
_HALF = {"½": .5, "-½": -.5}


def _num(tok):
    tok = tok.replace("+", "")
    if tok in ("½", "-½"):
        return -0.5 if tok.startswith("-") else 0.5
    if tok.endswith("½"):
        tok = tok[:-1] + ".5"
    try:
        return float(tok)
    except ValueError:
        return None


# ---------------- Circa Million ----------------
# "3. PACKERS -3½"  /  "22. JAGUARS +2½"  /  "17. EAGLES -7"  /  "18. TITANS PK"
_MPICK = re.compile(rf"\d+\.\s+(?P<team>{_ALT})\s+(?P<line>PK|[+-]?(?:\d+(?:½|\.5)?|½|\.5))", re.I)


def parse_million_selections(text):
    """[{id, picks:[{abbr, line}]}] plus the count table. One row per entry; picks carry the spread."""
    entries, seen = [], set()
    table = Counter()
    body, _, tail = text.partition("Team Count") if "Team Count" in text else text.partition("TEAM COUNT")
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.upper().startswith(("ENTRY NAME", "CIRCA SPORTS", "WEEK ")):
            continue
        picks = [{"abbr": to_abbr(m["team"]), "line": 0.0 if m["line"].upper() == "PK" else _num(m["line"])}
                 for m in _MPICK.finditer(line)]
        picks = [p for p in picks if p["abbr"]]
        if not picks:
            continue
        m = re.match(r"^(.*?)\s+\d+\.\s", line)
        name = (m.group(1) if m else line).strip()
        eid = name.upper()
        if eid in seen:
            continue
        seen.add(eid)
        entries.append({"id": eid, "picks": picks})
        for p in picks:
            table[p["abbr"]] += 1
    return entries, dict(table)


def grade_million(pick, scores):
    """cover/push/loss for one {abbr,line} pick against a straight ESPN score map."""
    g = scores.get(pick["abbr"])
    if not g or g.get("home_score") is None or g.get("state") == "pre":
        return {"res": None, "final": False}
    mine = g["home_score"] if g["home"] == pick["abbr"] else g["away_score"]
    theirs = g["away_score"] if g["home"] == pick["abbr"] else g["home_score"]
    adj = mine + pick["line"] - theirs
    return {"res": "W" if adj > 0 else "L" if adj < 0 else "P", "final": g["state"] == "post",
            "live": g["state"] == "in", "mine": mine, "theirs": theirs}


# ---------------- Circa Survivor ----------------
# multi-column: "!!DNANA-10 12. BUCS PK  FOXY ODDS-2 30. CHIEFS PK  PATRICE PG-5 12. BUCS PK"
_SV = re.compile(rf"(?P<name>\S.*?)\s+\d+\.\s+(?P<team>{_ALT})\s+PK", re.I)


# Circa occasionally prints an entry's -N suffix glued to the next pick's game number:
#   "...GOLD-PANNING-GAMBLER-108. PATRIOTS PK..."  =>  entry "-10", pick "8. PATRIOTS".
# A pick game number is 1-2 digits; an entry suffix is 1-2 digits. When we see "-DDD." (3 digits)
# or "-DDDD." we split off the trailing 1-2 digits that begin a valid " N. TEAM PK".
_GLUE = re.compile(rf"(-\d{{1,2}})(\d{{1,2}})\.\s+({_ALT})\s+PK", re.I)


def _deglue(line):
    return _GLUE.sub(lambda m: f"{m.group(1)} {m.group(2)}. {m.group(3)} PK", line)


def parse_survivor_selections(text):
    """[{id, pick}] + count table. Splits the 3-column layout by matching name+team+PK repeatedly."""
    entries, seen = [], set()
    table = Counter()
    for raw in text.splitlines():
        raw = _deglue(raw)
        line = raw.strip()
        if not line or line.upper().startswith(("ENTRY NAME", "CIRCA SURVIVOR", "WEEK ")):
            continue
        for m in _SV.finditer(line):
            ab = to_abbr(m["team"])
            if not ab:
                continue
            eid = m["name"].strip().upper()
            if eid in seen:
                continue
            seen.add(eid)
            entries.append({"id": eid, "pick": ab})
            table[ab] += 1
    return entries, dict(table)


def parse_survivor_availability(pdf):
    """Circa's availability grid -> {entry id: [teams used]} by reading X marks against column x-positions."""
    fix = {"WAS": "WSH", "LA": "LAR"}
    out = {}
    for page in pdf.pages:
        words = page.extract_words(use_text_flow=False)
        hdrs = [w for w in words if w["text"] == "ENTRY"]
        if not hdrs:
            continue
        top = hdrs[0]["top"]
        cols = [(fix.get(w["text"], w["text"]), (w["x0"] + w["x1"]) / 2)
                for w in words if abs(w["top"] - top) < 3 and w["text"] not in ("ENTRY", "NAME")]
        if not cols:
            continue
        name_right = min(c[1] for c in cols) - 14
        rows = {}
        for w in words:
            if w["top"] <= top + 3:
                continue
            rows.setdefault(round(w["top"]), []).append(w)
        for _, ws in sorted(rows.items()):
            name = " ".join(w["text"] for w in sorted(ws, key=lambda w: w["x0"]) if w["x1"] < name_right).strip()
            if not name:
                continue
            used = []
            for w in ws:
                if w["x0"] >= name_right and w["text"].upper() == "X":
                    c = (w["x0"] + w["x1"]) / 2
                    used.append(min(cols, key=lambda col: abs(col[1] - c))[0])
            out[name.upper()] = used
    return out


# ---------------- Circa Million standings ----------------
# "1T  3Whiffsand6-2  5  5-0-0-0  5.00"  (place, entry(may have spaces), #picks, W-L-T-P, points)
_MSTAND = re.compile(r"^(?P<place>\d+T?)\s+(?P<id>.+?)\s+(?P<np>\d+)\s+(?P<w>\d+)-(?P<l>\d+)-(?P<t>\d+)-(?P<p>\d+)\s+(?P<pts>\d+(?:\.\d+)?)$")


def parse_million_standings(text):
    rows = []
    for raw in text.splitlines():
        m = _MSTAND.match(raw.strip())
        if m:
            rows.append({"place": m["place"], "id": m["id"].strip().upper(),
                         "w": int(m["w"]), "l": int(m["l"]), "t": int(m["t"]), "c": int(m["p"]),
                         "pts": float(m["pts"])})
    return rows
