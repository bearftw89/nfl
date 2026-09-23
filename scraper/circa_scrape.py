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


def run():
    for c in OUT.values():
        c.mkdir(parents=True, exist_ok=True)
    found = discover()
    for k, v in from_fallback().items():
        found.setdefault(k, v)                          # discovery wins; fallback fills gaps
    if not found:
        S.log("! circa: no PDFs found by discovery or fallback (raw/circa/)")
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
