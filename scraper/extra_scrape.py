"""Updater for SuperContest Gold and SuperContest Survivor.

Gold     -> docs/data/<season>/gold/week-N/{card,picks,standings}.json   (same lines as the main contest)
Survivor -> docs/data/<season>/survivor/week-N/{card,picks,used}.json
Scores for both come from ESPN in the visitor's browser (ESPN refuses GitHub's servers).
"""
import io
import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin, unquote

import pdfplumber
from bs4 import BeautifulSoup

from . import scrape as S
from .parse import parse_card, parse_selections, parse_standings
from .teams import TEAMS, to_abbr
from . import survivor as SV

B = S.BASE + f"{S.SEASON}-supercontest-"
DATA = S.ROOT / "docs" / "data" / str(S.SEASON)
CONTESTS = {
    "gold": {"out": DATA / "gold", "tag": "GOLD",
             "pages": {"card": B + "gold-card", "picks": B + "gold-selections", "standings": B + "gold-standings"}},
    "survivor": {"out": DATA / "survivor", "tag": "SURVIVOR",
                 "pages": {"card": B + "survivor-card", "picks": B + "survivor-selections",
                           "used": B + "survivor-team-availability/"}},
}
_ALT = "|".join(re.escape(n) for n in sorted(TEAMS, key=len, reverse=True))


def load(path):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return None


def nfl_count_table(text):
    """Westgate's TEAM COUNT tally at the end of a 5-pick selections sheet."""
    up = text.upper()
    i = up.rfind("TEAM COUNT")
    c = Counter()
    if i >= 0:
        for m in re.finditer(rf"({_ALT})\s*(\d{{1,4}})(?=\s|$)", up[i:]):
            c[to_abbr(m.group(1))] += int(m.group(2))
    return c


def list_pdfs(url, tag):
    soup = BeautifulSoup(S.get(url).text, "html.parser")
    found = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/supercontest/download/" not in href or ".pdf" not in href.lower():
            continue
        fname = unquote(href.split("/download/", 1)[1].split("?", 1)[0]).upper()
        if tag not in fname or "RULES" in fname:
            continue
        m = S.WEEK_RE.search(fname)
        if m:
            found[int(m.group(1))] = urljoin(url, href).replace(" ", "%20")
    return found


# ---------------- savers: (contest, week, url, pdf bytes) -> ok ----------------
def _text(data):
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)


def _save(path, key, rows, url, week, label):
    old = load(path)
    if old and old.get(key) == rows:
        return
    S.write_json(path, {"week": week, "source": url, "count": len(rows), key: rows})
    S.log(f"  {label} week {week}: {len(rows)}")


def gold_card(out, week, url, data):
    games = parse_card(_text(data))
    if len(games) < 8:
        S.log(f"! gold card week {week}: only {len(games)} games; keeping old data"); return False
    _save(out / f"week-{week}" / "card.json", "games", games, url, week, "gold card"); return True


def gold_picks(out, week, url, data):
    text = _text(data)
    entries, table = parse_selections(text), nfl_count_table(text)
    got = Counter(a for e in entries for a in e["picks"])
    if not entries or (table and got != table):
        S.log(f"! gold picks week {week}: {len(entries)} entries don't match Westgate's count table; keeping old data")
        return False
    _save(out / f"week-{week}" / "picks.json", "entries", entries, url, week, "gold picks"); return True


def gold_standings(out, week, url, data):
    rows = parse_standings(_text(data))
    if len(rows) < 10:
        S.log(f"! gold standings week {week}: only {len(rows)} rows; keeping old data"); return False
    _save(out / f"week-{week}" / "standings.json", "rows", rows, url, week, "gold standings"); return True


def surv_card(out, week, url, data):
    games = SV.parse_card(_text(data))
    if len(games) < 8:
        S.log(f"! survivor card week {week}: only {len(games)} games; keeping old data"); return False
    # the survivor sheet's neutral-site note isn't on the game's line; take it from the main game sheet
    main = load(DATA / f"week-{week}" / "card.json")
    if main:
        neutral = {frozenset((g["fav"]["abbr"], g["dog"]["abbr"])) for g in main["games"]
                   if not g["fav"]["home"] and not g["dog"]["home"]}
        for g in games:
            if frozenset((g["away"]["abbr"], g["home"]["abbr"])) in neutral:
                g["neutral"] = True
    _save(out / f"week-{week}" / "card.json", "games", games, url, week, "survivor card"); return True


def surv_picks(out, week, url, data):
    entries, table = SV.parse_selections(_text(data))
    got = Counter(e["pick"] for e in entries)
    if not entries or (table and got != Counter(table)):
        S.log(f"! survivor picks week {week}: {len(entries)} entries don't match Westgate's count table; keeping old data")
        return False
    _save(out / f"week-{week}" / "picks.json", "entries", entries, url, week, "survivor picks"); return True


def surv_used(out, week, url, data):
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        used = SV.parse_used(pdf)
    if not used:
        S.log(f"! survivor used-teams week {week}: nothing read"); return False
    old = load(out / f"week-{week}" / "used.json")
    if not old or old.get("entries") != used:
        S.write_json(out / f"week-{week}" / "used.json", {"week": week, "source": url, "count": len(used), "entries": used})
        S.log(f"  survivor used-teams through week {week}: {len(used)} entries alive")
    return True


SAVERS = {"gold": {"card": gold_card, "picks": gold_picks, "standings": gold_standings},
          "survivor": {"card": surv_card, "picks": surv_picks, "used": surv_used}}


def build_manifest(name):
    out = CONTESTS[name]["out"]
    kinds = ("card", "picks", "standings", "results", "overrides") if name == "gold" else ("card", "picks", "used")
    weeks = {}
    for d in sorted(out.glob("week-*"), key=lambda p: int(p.name.split("-")[1])):
        weeks[int(d.name.split("-")[1])] = {k: (d / f"{k}.json").exists() for k in kinds}
    extra = {"picks_per_entry": 5} if name == "gold" else {"picks_per_entry": 1}
    S.write_json(out / "manifest.json", {"season": S.SEASON, "league": name, **extra, "weeks": weeks})


def run():
    ok = True
    for name, cfg in CONTESTS.items():
        cfg["out"].mkdir(parents=True, exist_ok=True)
        for kind, url in cfg["pages"].items():
            try:
                pdfs = list_pdfs(url, cfg["tag"])
            except Exception as e:
                S.log(f"! could not read {name} {kind} listing: {e}"); ok = False; continue
            S.log(f"{name} {kind}: weeks listed {sorted(pdfs)}")
            latest = max(pdfs) if pdfs else None
            for week, purl in sorted(pdfs.items()):
                if (cfg["out"] / f"week-{week}" / f"{kind}.json").exists() and week != latest:
                    continue
                try:
                    ok &= SAVERS[name][kind](cfg["out"], week, purl, S.get(purl).content)
                except Exception as e:
                    S.log(f"! {name} {kind} week {week}: {e}"); ok = False
        build_manifest(name)
    return ok
