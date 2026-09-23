"""Updater for Circa Sports contests, hosted on circasports.com (not Westgate).

Circa posts weekly PDFs to WordPress under /wp-content/uploads/YYYY/MM/. The month is the
posting month, not the NFL week, and file names aren't perfectly uniform, so we DISCOVER
links from the two contest pages rather than guessing URLs. If discovery fails (the page
markup changed, or the run can't reach circasports.com), a committed PDF placed in
raw/circa/ is used as a fallback.

  circa-survivor -> docs/data/<season>/circa-survivor/week-N/{picks,used}.json
  circa-millio   -> docs/data/<season>/circa-millio/week-N/{picks,standings}.json   (built later)

Scores come from ESPN in the browser, same as every other contest.
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
from . import circa as C

DATA = S.ROOT / "docs" / "data" / str(S.SEASON)
RAWDIR = S.ROOT / "raw" / "circa"                      # optional committed-PDF fallback
PAGES = {"survivor": "https://www.circasports.com/circa-survivor",
         "millio": "https://www.circasports.com/circa-million"}
# file-name signatures -> (contest, kind)
SIGN = [
    (re.compile(r"SURVIVOR.*TEAM.*AVAIL", re.I), ("survivor", "used")),
    (re.compile(r"SURVIVOR.*SELECTION", re.I), ("survivor", "picks")),
    (re.compile(r"MILLION.*STANDING", re.I), ("millio", "standings")),
    (re.compile(r"MILLION.*SELECTION", re.I), ("millio", "picks")),
]
OUT = {"survivor": DATA / "circa-survivor", "millio": DATA / "circa-millio"}


def current_nfl_week():
    """How far the season has actually gotten, from the main Westgate NFL manifest (its own
    updater only ever posts a week once real data exists for it, so this is a trustworthy
    ceiling). Falls back to 18 if that manifest isn't there yet."""
    mp = DATA / "manifest.json"
    m = json.loads(mp.read_text()) if mp.exists() else None
    if not m:
        return 18
    weeks = [int(w) for w, v in m.get("weeks", {}).items() if v.get("picks") or v.get("card")]
    return max(weeks) if weeks else 1


def sane_week(week, current):
    """Circa's site links standings for whole-season 'quarters' (weeks 4, 9, 13, 18) ahead of
    time, before those weeks are played, and whatever PDF sits at that URL until then is not
    this week's real data. Reject anything more than one week ahead of where the season
    actually is."""
    return week <= current + 1


def classify(fname):
    for rx, tag in SIGN:
        if rx.search(fname):
            return tag
    return None


def week_of(fname):
    # "...Week-2-Selections", "...After-Week-1", "...Contest-Point-Spreads-Week-2"
    m = re.search(r"WEEK[\s_-]*#?(\d{1,2})", fname, re.I)
    return int(m.group(1)) if m else None


def discover():
    """{(contest, kind, week): url} from the two Circa pages."""
    found = {}
    for page in PAGES.values():
        try:
            html = S.get(page).text
        except Exception as e:
            S.log(f"! circa: could not read {page}: {e}")
            continue
        for a in BeautifulSoup(html, "html.parser").find_all("a", href=True):
            href = a["href"]
            if ".pdf" not in href.lower():
                continue
            fname = unquote(href.split("/")[-1])
            tag = classify(fname)
            wk = week_of(fname)
            if tag and wk:
                found[(tag[0], tag[1], wk)] = urljoin(page, href).replace(" ", "%20")
    return found


def from_fallback():
    """Same mapping, but from any PDFs committed under raw/circa/."""
    found = {}
    if not RAWDIR.exists():
        return found
    for p in RAWDIR.glob("*.pdf"):
        tag = classify(p.name)
        wk = week_of(p.name)
        if tag and wk:
            found[(tag[0], tag[1], wk)] = p
    return found


def load(path):
    try:
        return __import__("json").loads(Path(path).read_text())
    except Exception:
        return None


def _bytes(src):
    return src.read_bytes() if isinstance(src, Path) else S.get(src).content


def _text(data):
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return "\n".join((pg.extract_text() or "") for pg in pdf.pages)


def save_survivor_picks(week, src):
    entries, table = C.parse_survivor_selections(_text(_bytes(src)))
    got = Counter(e["pick"] for e in entries)
    if len(entries) < 100 or (table and got != Counter(table)):
        S.log(f"! circa survivor picks week {week}: {len(entries)} entries fail the count-table check; keeping old data")
        return False
    out = OUT["survivor"] / f"week-{week}"
    old = load(out / "picks.json")
    if not old or old.get("entries") != entries:
        S.write_json(out / "picks.json", {"week": week, "source": str(src), "count": len(entries), "entries": entries})
        S.log(f"  circa survivor picks week {week}: {len(entries)} entries")
    return True


def save_survivor_used(week, src):
    with pdfplumber.open(io.BytesIO(_bytes(src))) as pdf:
        used = C.parse_survivor_availability(pdf)
    if len(used) < 100:
        S.log(f"! circa survivor availability week {week}: only {len(used)} rows; keeping old data")
        return False
    out = OUT["survivor"] / f"week-{week}"
    old = load(out / "used.json")
    if not old or old.get("entries") != used:
        S.write_json(out / "used.json", {"week": week, "source": str(src), "count": len(used), "entries": used})
        S.log(f"  circa survivor availability through week {week}: {len(used)} entries")
    return True


def save_millio_picks(week, src):
    entries, table = C.parse_million_selections(_text(_bytes(src)))
    got = Counter(p["abbr"] for e in entries for p in e["picks"])
    if len(entries) < 50 or (table and got != Counter(table)):
        S.log(f"! circa millio picks week {week}: {len(entries)} entries fail the count-table check; keeping old data")
        return False
    out = OUT["millio"] / f"week-{week}"
    old = load(out / "picks.json")
    if not old or old.get("entries") != entries:
        S.write_json(out / "picks.json", {"week": week, "source": str(src), "count": len(entries), "entries": entries})
        S.log(f"  circa millio picks week {week}: {len(entries)} entries")
    return True


def save_millio_standings(week, src):
    rows = C.parse_million_standings(_text(_bytes(src)))
    if len(rows) < 50:
        S.log(f"! circa millio standings week {week}: only {len(rows)} rows; keeping old data")
        return False
    out = OUT["millio"] / f"week-{week}"
    old = load(out / "standings.json")
    if not old or old.get("rows") != rows:
        S.write_json(out / "standings.json", {"week": week, "source": str(src), "count": len(rows), "rows": rows})
        S.log(f"  circa millio standings week {week}: {len(rows)} rows")
    return True


SAVERS = {("survivor", "picks"): save_survivor_picks, ("survivor", "used"): save_survivor_used,
          ("millio", "picks"): save_millio_picks, ("millio", "standings"): save_millio_standings}


def build_manifest(contest):
    out = OUT[contest]
    kinds = ("picks", "used") if contest == "survivor" else ("picks", "standings")
    weeks = {}
    for d in sorted(out.glob("week-*"), key=lambda p: int(p.name.split("-")[1])):
        weeks[int(d.name.split("-")[1])] = {k: (d / f"{k}.json").exists() for k in kinds}
    extra = {"picks_per_entry": 1} if contest == "survivor" else {"picks_per_entry": 5}
    S.write_json(out / "manifest.json", {"season": S.SEASON, "league": "circa-" + contest, **extra, "weeks": weeks})


def prune_future(current):
    """Delete any previously saved week folder that fails sane_week — self-heals a bad
    week saved by an earlier, buggier run without needing manual file surgery."""
    for contest, out in OUT.items():
        for d in sorted(out.glob("week-*")):
            week = int(d.name.split("-")[1])
            if not sane_week(week, current):
                for f in d.glob("*.json"):
                    f.unlink()
                d.rmdir()
                S.log(f"  circa {contest}: removed week {week} (beyond week {current + 1}; a stale/placeholder file, not real data)")


def run():
    for c in OUT.values():
        c.mkdir(parents=True, exist_ok=True)
    current = current_nfl_week()
    prune_future(current)
    found = discover()
    for k, v in from_fallback().items():
        found.setdefault(k, v)                          # discovery wins; fallback fills gaps
    if not found:
        S.log("! circa: no PDFs found by discovery or fallback (raw/circa/)")
    skipped = [(c, k, w) for (c, k, w) in found if not sane_week(w, current)]
    for c, k, w in skipped:
        S.log(f"! circa {c} {k} week {w}: skipped (beyond week {current + 1}; likely a future-quarter placeholder link, not this week's real data)")
        del found[(c, k, w)]
    ok = True
    for (contest, kind, week), src in sorted(found.items()):
        saver = SAVERS.get((contest, kind))
        if not saver:
            continue
        latest = max((w for (cc, kk, w) in found if cc == contest and kk == kind), default=week)
        if (OUT[contest] / f"week-{week}" / f"{kind}.json").exists() and week != latest:
            continue
        try:
            ok &= saver(week, src)
        except Exception as e:
            S.log(f"! circa {contest} {kind} week {week}: {e}")
    for contest in OUT:
        build_manifest(contest)
    return ok
