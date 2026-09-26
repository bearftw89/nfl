"""SuperContest College parsers.

College differs from the NFL contest in three ways:
  * game sheets have ~40-60 games, with neutral-site notes ("@London, ENG") between
    the first team and the kickoff time, and day headers that carry the date;
  * selections use Westgate's abbreviations ("N CAROLINA", "MISS ST", "N` WESTERN"),
    and team names contain spaces, so a pick line can't be split on whitespace;
  * those abbreviations differ from the game sheet's full names ("NORTH CAROLINA",
    "MISSISSIPPI STATE", "NORTHWESTERN").

Selections are split using the TEAM COUNT table at the bottom of each sheet, which
lists every abbreviation used that week, and each abbreviation is then matched to one
team on that week's card. Teams are keyed by their game-sheet name.
"""
import re
from collections import Counter

MONTHS = {m: i for i, m in enumerate(
    "JANUARY FEBRUARY MARCH APRIL MAY JUNE JULY AUGUST SEPTEMBER OCTOBER NOVEMBER DECEMBER".split(), 1)}

_CARD = re.compile(
    r"^[ \t]*(?P<n1>\d{1,3})[ \t]+(?P<t1>[A-Z0-9][A-Z0-9 .'&\-]*?)(?P<h1>\*?)[ \t]+(?:@(?P<site>[^\n]*?)[ \t]+)?"
    r"(?P<time>\d{1,2}:\d{2}[ \t]*[AP]M)[ \t]+"
    r"(?P<n2>\d{1,3})[ \t]+(?P<t2>[A-Z0-9][A-Z0-9 .'&\-]*?)(?P<h2>\*?)[ \t]+"
    r"(?P<line>[+-]?(?:\d+(?:\.\d+)?|\.\d+)|PK|P)(?![\w.])", re.M)
_DAY = re.compile(r"COLLEGE FOOTBALL\s*-\s*[A-Z]+,\s*([A-Z]+)\s+(\d{1,2}),\s*(\d{4})")


# The game sheet isn't consistent week to week ("MIAMI-FLORIDA" vs "MIAMI-FL"); one name per team.
CANON = {
    "CAL": "CALIFORNIA", "MIAMI-FLORIDA": "MIAMI-FL", "MIAMI-OHIO": "MIAMI-OH",
    "SOUTHERN MISSISSIPPI": "SOUTHERN MISS", "MID TENNESSEE ST": "MIDDLE TENNESSEE",
    "MIDDLE TENNESSEE ST": "MIDDLE TENNESSEE", "MIDDLE TENNESSEE STATE": "MIDDLE TENNESSEE",
    "NORTH CAROLINA ST": "NC STATE", "NORTH CAROLINA STATE": "NC STATE",
    "UMASS": "MASSACHUSETTS", "UL-MONROE": "UL MONROE",
}


def canon(name):
    n = re.sub(r"\s+", " ", name.strip().rstrip("*")).upper()
    n = CANON.get(n, n)
    if n.endswith(" ST"):
        n = CANON.get(n[:-3] + " STATE", n[:-3] + " STATE")     # "ARIZONA ST" -> "ARIZONA STATE"
    return n


def _clean(name):
    return canon(name)


def parse_card(text):
    """Games in sheet order. Each side: {num, name, home, line}; plus date (YYYY-MM-DD) and site."""
    text = text.upper()
    # date of each game = most recent day header above it
    heads = [(m.start(), f"{m.group(3)}-{MONTHS[m.group(1)]:02d}-{int(m.group(2)):02d}")
             for m in _DAY.finditer(text) if m.group(1) in MONTHS]
    games = []
    for m in _CARD.finditer(text):
        dog = 0.0 if m["line"] in ("PK", "P") else abs(float(m["line"]))
        date = None
        for pos, d in heads:
            if pos < m.start():
                date = d
        games.append({
            "id": len(games) + 1, "time_pt": re.sub(r"\s+", " ", m["time"]), "date": date,
            "site": (m["site"] or "").strip().title() or None,
            "fav": {"num": int(m["n1"]), "name": _clean(m["t1"]), "home": bool(m["h1"]), "line": -dog if dog else 0.0},
            "dog": {"num": int(m["n2"]), "name": _clean(m["t2"]), "home": bool(m["h2"]), "line": dog},
        })
    return games


# ---------------- selections ----------------
_ENTRY = re.compile(r"^(?P<name>.+?)\s+-\s+(?P<n>\d{1,2})\s+(?P<rest>.+)$")
_COUNT_ROW = re.compile(r"([A-Z][A-Z0-9 .'&`\-]*?)\s+(\d{1,4})(?=\s|$)")


_INLINE_LINE = re.compile(r"(?<=[A-Z])\s[+-]\d+(?:½|\.5)?(?=\s|$)")


def _normalize(text):
    """Some picks are printed with their line ("UNLV -2½"); drop it so the name matches."""
    return _INLINE_LINE.sub("", text.upper().replace("\u00bd", "½"))


def count_table(text):
    """{abbreviation: count} from the TEAM COUNT table at the end of a selections sheet."""
    up = _normalize(text)
    i = up.rfind("TEAM COUNT")
    if i < 0:
        return {}
    out = {}
    for line in up[i:].splitlines():
        if "TEAM COUNT" in line:
            continue
        for name, n in _COUNT_ROW.findall(line.strip()):
            out[re.sub(r"\s+", " ", name.strip())] = int(n)
    return out


def _split_picks(rest, vocab):
    """Greedy longest-match split of 'N CAROLINA MISS ST ...' using the week's abbreviations."""
    words, out, i = rest.split(), [], 0
    maxw = max(len(v.split()) for v in vocab)
    while i < len(words):
        for k in range(min(maxw, len(words) - i), 0, -1):
            cand = " ".join(words[i:i + k])
            if cand in vocab:
                out.append(cand); i += k
                break
        else:
            return None
    return out


def parse_selections(text, picks_per_entry=7):
    """Returns (entries, table). entries: [{id, picks:[abbr,...]}] (abbreviations, not yet mapped)."""
    table = count_table(text)
    vocab = set(table)
    body = _normalize(text)
    cut = body.rfind("TEAM COUNT")
    if cut > 0:
        body = body[:cut]
    entries, seen = [], set()
    for raw in body.splitlines():
        # page headers can glue onto a row: "2026 SUPERCONTEST COLLEGE WEEK 3 SELECTIONS7 HORSEMEN - 2 ..."
        line = re.sub(r"^.*?SELECTIONS(?=\S)", "", raw.strip())
        m = _ENTRY.match(line)
        if not m or not vocab:
            continue
        picks = _split_picks(m["rest"], vocab)
        if not picks:
            continue
        eid = f"{m['name'].strip()}-{int(m['n'])}"
        if eid in seen:
            continue                      # rule: first submission counts
        seen.add(eid)
        entries.append({"id": eid, "picks": picks})
    return entries, table


# ---------------- abbreviation -> game-sheet name ----------------
# Westgate's selection abbreviations that plain prefix-matching can't resolve.
ALIASES = {
    "PITT": "PITTSBURGH", "MIAMI FL": ["MIAMI-FL", "MIAMI-FLORIDA"], "MIAMI OH": ["MIAMI-OH", "MIAMI-OHIO"], "N` WESTERN": "NORTHWESTERN",
    "J'VILLE ST": "JACKSONVILLE STATE", "J MADISON": "JAMES MADISON", "APP ST": "APPALACHIAN STATE",
    "UCF": "CENTRAL FLORIDA", "FLA INT'L": "FLORIDA INT'L", "FLA ATLANTIC": "FLORIDA ATLANTIC",
    "SO MISS": "SOUTHERN MISS", "MID TENN ST": "MIDDLE TENNESSEE", "BOWL GREEN": "BOWLING GREEN",
    "NC STATE": "NC STATE", "KENNESAW": "KENNESAW STATE", "NO ILLINOIS": "NORTHERN ILLINOIS",
    "LA TECH": "LOUISIANA TECH", "VA TECH": "VIRGINIA TECH", "COLO ST": "COLORADO STATE",
    "ARK ST": "ARKANSAS STATE", "GA SOUTHERN": "GEORGIA SOUTHERN", "COASTAL CAR": "COASTAL CAROLINA",
    "TEXAS A & M": "TEXAS A&M", "OLE MISS": "OLE MISS", "UL MONROE": "UL MONROE", "LA MONROE": "UL MONROE",
    "ULM": "UL MONROE", "CAL": "CALIFORNIA", "UMASS": "MASSACHUSETTS",
    "SAN JOSE ST": "SAN JOSE STATE", "MISS ST": "MISSISSIPPI STATE", "S FLORIDA": "SOUTH FLORIDA",
    "USF": "SOUTH FLORIDA", "SAM HOUSTON": "SAM HOUSTON STATE", "SAM HOUSTON ST": "SAM HOUSTON STATE",
    "NEW MEXICO ST": "NEW MEXICO STATE", "NM STATE": "NEW MEXICO STATE", "MIDDLE TENN": "MIDDLE TENNESSEE",
}
_EXPAND = {"N": ["NORTH", "NORTHERN"], "S": ["SOUTH", "SOUTHERN"], "E": ["EAST", "EASTERN"],
           "W": ["WEST", "WESTERN"], "C": ["CENTRAL"], "ST": ["STATE", "ST"], "SO": ["SOUTHERN", "SOUTH"],
           "NO": ["NORTHERN", "NORTH"], "GA": ["GEORGIA"], "FLA": ["FLORIDA"], "COLO": ["COLORADO"],
           "ARK": ["ARKANSAS"], "LA": ["LOUISIANA"], "VA": ["VIRGINIA"], "MISS": ["MISSISSIPPI", "MISS"],
           "TENN": ["TENNESSEE"], "MID": ["MIDDLE", "MID"], "INT'L": ["INT'L", "INTERNATIONAL"]}


def _variants(words):
    if not words:
        yield []
        return
    for head in _EXPAND.get(words[0], [words[0]]):
        for tail in _variants(words[1:]):
            yield [head] + tail


def map_abbreviations(abbrs, card_names):
    """{abbr: card name} for every abbreviation; raises ValueError listing any that don't resolve uniquely."""
    names = set(card_names)
    out, bad = {}, []
    for a in abbrs:
        if a in names:
            out[a] = a; continue
        al = ALIASES.get(a)
        hit = sorted({canon(x) for x in (al if isinstance(al, list) else [al])} & names) if al else []
        if len(hit) == 1:
            out[a] = hit[0]; continue
        cands = {" ".join(v) for v in _variants(a.split())} & names
        if len(cands) == 1:
            out[a] = cands.pop(); continue
        # last resort: every abbreviated word is a prefix of the matching card word
        aw = a.replace("`", "").split()
        pref = [n for n in names if len(n.split()) == len(aw)
                and all(nw.startswith(w) for w, nw in zip(aw, n.split()))]
        if len(pref) == 1:
            out[a] = pref[0]
        else:
            bad.append((a, sorted(pref)))
    if bad:
        raise ValueError(f"unmatched abbreviations: {bad}")
    return out


# ---------------- results from official standings (safety net) ----------------
def derive_results(card, picks, standings_now, standings_prev=None):
    """Work out which side covered each game from Westgate's official records.

    Each entry's weekly W-L-T (this week's standings minus last week's) must equal the
    results of its picks. Propagate until nothing changes. Returns ({team: W/L/P}, n_mismatch):
    a complete, consistent answer has n_mismatch == 0. Used only as a fallback for games
    the score feed couldn't match.
    """
    opp = {}
    for g in card:
        opp[g["fav"]["abbr"]] = g["dog"]["abbr"]; opp[g["dog"]["abbr"]] = g["fav"]["abbr"]
    prev = {r["id"]: r for r in (standings_prev or [])}
    need = {}
    for e in picks:
        cur = standings_now.get(e["id"])
        if not cur:
            continue
        p = prev.get(e["id"], {"w": 0, "l": 0, "t": 0})
        need[e["id"]] = (e["picks"], cur["w"] - p["w"], cur["l"] - p["l"], cur["t"] - p["t"])
    res = {}
    flip = {"W": "L", "L": "W", "P": "P"}

    def setr(t, r):
        if t not in opp or res.get(t, r) != r:
            return False
        new = t not in res
        res[t] = r; res[opp[t]] = flip[r]
        return new
    changed = True
    while changed:
        changed = False
        for pk, wn, ln, tn in need.values():
            kw = sum(res.get(t) == "W" for t in pk); kl = sum(res.get(t) == "L" for t in pk)
            kt = sum(res.get(t) == "P" for t in pk)
            unk = [t for t in pk if t not in res]
            if not unk:
                continue
            if kw == wn and kt == tn:
                changed |= any([setr(t, "L") for t in unk])
            elif kl == ln and kt == tn:
                changed |= any([setr(t, "W") for t in unk])
            elif kw == wn and kl == ln:
                changed |= any([setr(t, "P") for t in unk])
    bad = sum(1 for pk, wn, ln, tn in need.values()
              if (sum(res.get(t) == "W" for t in pk), sum(res.get(t) == "L" for t in pk),
                  sum(res.get(t) == "P" for t in pk)) != (wn, ln, tn))
    return res, bad


# ---------------- game sheet <-> ESPN ----------------
import unicodedata

# Game-sheet names ESPN spells differently (compared after _norm()).
ESPN_NAMES = {
    "MIAMI-FL": ["MIAMI", "MIAMI FL", "MIAMI FLORIDA"], "MIAMI-OH": ["MIAMI OH", "MIAMI OHIO"],
    "CENTRAL FLORIDA": ["UCF"], "NC STATE": ["NC STATE", "NORTH CAROLINA STATE"],
    "FLORIDA INT'L": ["FLORIDA INTERNATIONAL", "FIU"], "SOUTHERN MISS": ["SOUTHERN MISS", "SOUTHERN MISSISSIPPI"],
    "MIDDLE TENNESSEE": ["MIDDLE TENNESSEE", "MTSU"], "MASSACHUSETTS": ["MASSACHUSETTS", "UMASS"],
    "SAM HOUSTON STATE": ["SAM HOUSTON", "SAM HOUSTON STATE"], "UL MONROE": ["UL MONROE", "LOUISIANA MONROE"],
    "LOUISIANA": ["LOUISIANA", "LOUISIANA LAFAYETTE"], "APPALACHIAN STATE": ["APPALACHIAN STATE", "APP STATE"],
    "PITTSBURGH": ["PITTSBURGH", "PITT"], "CALIFORNIA": ["CALIFORNIA", "CAL"], "SOUTH FLORIDA": ["SOUTH FLORIDA", "USF"],
    "UCONN": ["UCONN", "CONNECTICUT"], "OLE MISS": ["OLE MISS", "MISSISSIPPI"], "BYU": ["BYU", "BRIGHAM YOUNG"],
    "HAWAII": ["HAWAII"], "SAN JOSE STATE": ["SAN JOSE STATE"], "TEXAS A&M": ["TEXAS A&M", "TEXAS A AND M"],
    "USC": ["USC", "SOUTHERN CALIFORNIA"], "SMU": ["SMU"], "TCU": ["TCU"], "LSU": ["LSU"], "UTEP": ["UTEP"],
    "UTSA": ["UTSA"], "UAB": ["UAB"], "UNLV": ["UNLV"], "KENNESAW STATE": ["KENNESAW STATE", "KENNESAW"],
}


def _norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().upper()
    s = s.replace("'", "").replace("\u2019", "").replace(".", "").replace("(", "").replace(")", "")
    return re.sub(r"[\s\-]+", " ", s).strip()


def _team_keys(t):
    """Normalized names ESPN gives one team."""
    keys = {_norm(t.get(k, "")) for k in ("location", "shortDisplayName", "abbreviation", "name")}
    disp, nick = _norm(t.get("displayName", "")), _norm(t.get("name", ""))
    if nick and disp.endswith(" " + nick):
        keys.add(disp[: -len(nick) - 1])        # "Miami (OH) RedHawks" -> "MIAMI OH"
    return {k for k in keys if k}


def _wanted(name):
    return {_norm(x) for x in ESPN_NAMES.get(name, [])} | {_norm(name)}


def match_espn(card, events):
    """{card game id: espn event} pairing each row with the ESPN game that has both teams."""
    ev = []
    for e in events:
        comps = e["competitions"][0]["competitors"]
        ev.append((e, [(c["homeAway"], _team_keys(c["team"])) for c in comps]))
    out = {}
    for g in card:
        a, b = _wanted(g["fav"]["abbr"]), _wanted(g["dog"]["abbr"])
        both = [e for e, cs in ev if any(k & a for _, k in cs) and any(k & b for _, k in cs)]
        if len(both) == 1:
            out[g["id"]] = both[0]
            continue
        one = [e for e, cs in ev if any(k & a for _, k in cs) or any(k & b for _, k in cs)]
        if len(one) == 1:                        # one name differs, but only one game has the other team
            out[g["id"]] = one[0]
    return out
