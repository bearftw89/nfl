"""SuperContest Survivor parsers.

Survivor rules (2026-27 rules PDF): pick one team per week to WIN straight up (no spread);
a loss or a tie eliminates the entry; each team can be used once per entry; an entry that
doesn't pick by the deadline is eliminated.
"""
import re
from collections import Counter
from .teams import TEAMS, to_abbr

_NAMES = sorted(TEAMS, key=len, reverse=True)
_TEAM_ALT = "|".join(re.escape(n) for n in _NAMES)

# "1 PATRIOTS 5:20 PM 2 SEAHAWKS"  (home team on the right unless a neutral site is noted)
# "3 49ERS at Melbourne, Australia 5:35 PM 4 RAMS"
_CARD = re.compile(
    rf"^[ \t]*(?P<n1>\d{{1,3}})[ \t]+(?P<t1>{_TEAM_ALT})[ \t]+(?:(?:at|@)[ \t]+(?P<site>[^\n]*?)[ \t]+)?"
    rf"(?P<time>\d{{1,2}}:\d{{2}}[ \t]*[AP]M)[ \t]+(?P<n2>\d{{1,3}})[ \t]+(?P<t2>{_TEAM_ALT})[ \t]*$", re.M | re.I)


def parse_card(text):
    """Games in sheet order: {id, away:{num,abbr}, home:{num,abbr}, neutral, site, time_pt}."""
    games = []
    for m in _CARD.finditer(text):
        a, h = to_abbr(m["t1"]), to_abbr(m["t2"])
        if not a or not h:
            continue
        site = (m["site"] or "").strip()
        games.append({"id": len(games) + 1, "time_pt": re.sub(r"\s+", " ", m["time"].upper()),
                      "away": {"num": int(m["n1"]), "abbr": a}, "home": {"num": int(m["n2"]), "abbr": h},
                      "neutral": bool(site), "site": site or None})
    return games


# Selections come in 2-4 side-by-side columns: "507MAFIA - 1 JAGUARS BIG LIB - 1 CHARGERS ..."
_ENTRY = re.compile(rf"\s*(?P<name>.+?)\s+-\s+(?P<n>\d{{1,2}})\s+(?P<team>{_TEAM_ALT})(?=\s|$)", re.I)
_COUNT = re.compile(rf"(?<!\S)(?P<team>{_TEAM_ALT})\s*(?P<n>\d{{1,4}})(?=\s|$)", re.I)


def parse_selections(text):
    """Returns (entries [{id, pick}], count_table {abbr: n}). The count table is Westgate's own tally."""
    entries, seen, table = [], set(), Counter()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.upper().startswith(("PLAYER NAME", "TEAM COUNT")) or "SURVIVOR SELECTIONS" in line.upper() and " - " not in line:
            continue
        line = re.sub(r"^\d{4} SURVIVOR SELECTIONS WEEK \d+\s*", "", line, flags=re.I)
        rest, pos = line, 0
        for m in _ENTRY.finditer(line):
            name = m["name"].strip()
            # a count-table pair ("49ERS 51") can sit in front of the next name; peel it off
            cm = re.match(rf"^((?:(?:{_TEAM_ALT})\s*\d{{1,4}}\s+)+)(.+)$", name, re.I)
            if cm:
                for c in _COUNT.finditer(cm.group(1)):
                    table[to_abbr(c["team"])] += int(c["n"])
                name = cm.group(2).strip()
            name = re.sub(r"^(TEAM COUNT\s+)", "", name, flags=re.I)
            eid = f"{name.upper()}-{int(m['n'])}"
            if eid not in seen:
                seen.add(eid)
                entries.append({"id": eid, "pick": to_abbr(m["team"])})
            pos = m.end()
        for c in _COUNT.finditer(line[pos:]):        # leftover text after the last entry = count table
            table[to_abbr(c["team"])] += int(c["n"])
    return entries, dict(table)


def parse_used(pdf):
    """Westgate's 'teams previously used' grid -> {entry id: [team codes]}. Reads marks by column position."""
    code_fix = {"AZ": "ARI", "PHL": "PHI", "WAS": "WSH", "LAR": "LAR"}
    out = {}
    for page in pdf.pages:
        words = page.extract_words(keep_blank_chars=False, use_text_flow=False)
        head = [w for w in words if w["text"] == "CONTESTANT"]
        if not head:
            continue
        top = head[0]["top"]
        cols = [(w["x0"] + w["x1"]) / 2 for w in words if abs(w["top"] - top) < 3 and w["text"] != "CONTESTANT"]
        codes = [code_fix.get(w["text"], w["text"]) for w in words if abs(w["top"] - top) < 3 and w["text"] != "CONTESTANT"]
        name_right = min(cols) - 12
        rows = {}
        for w in words:
            if w["top"] <= top + 3:
                continue
            key = round(w["top"])
            rows.setdefault(key, []).append(w)
        for _, ws in sorted(rows.items()):
            name = " ".join(w["text"] for w in sorted(ws, key=lambda w: w["x0"]) if w["x1"] < name_right)
            m = re.match(r"^(.+?)\s+-\s+(\d{1,2})$", name.strip())
            if not m:
                continue
            used = []
            for w in ws:
                if w["x0"] >= name_right and w["text"] == "1":
                    c = (w["x0"] + w["x1"]) / 2
                    used.append(codes[min(range(len(cols)), key=lambda i: abs(cols[i] - c))])
            out[f"{m.group(1).upper()}-{int(m.group(2))}"] = used
    return out


def survivor_state(weeks, picks_by_week, results_by_week):
    """Walk the season. results_by_week[w][team] = 'W'/'L'/'T' for final games (missing = not final).

    Returns {entry: {"alive": bool, "out_week": w|None, "reason": str|None, "used": [(w, team)]}}.
    An entry must pick every week once that week's selections are posted; no pick = eliminated.
    """
    everyone = {e for w in weeks for e in picks_by_week.get(w, {})}
    st = {e: {"alive": True, "out_week": None, "reason": None, "used": []} for e in everyone}
    for w in weeks:
        picks = picks_by_week.get(w)
        if picks is None:
            break
        res = results_by_week.get(w, {})
        for e, s in st.items():
            if not s["alive"]:
                continue
            t = picks.get(e)
            if not t:
                s.update(alive=False, out_week=w, reason="no pick"); continue
            if any(u == t for _, u in s["used"]):
                s.update(alive=False, out_week=w, reason=f"{t} already used")
            s["used"].append((w, t))
            r = res.get(t)
            if r in ("L", "T"):
                s.update(alive=False, out_week=w, reason=f"{t} {'tied' if r == 'T' else 'lost'}")
    return st
