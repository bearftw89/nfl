"""Pull Westgate SuperContest PDFs and NFL scores into docs/data/<season>/.

Run:  python -m scraper.scrape            (all weeks found)
      python -m scraper.scrape --week 3   (one week)

Output per week (docs/data/2026/week-N/):
  card.json       games + lines from the weekly card
  picks.json      every entry's 5 picks
  standings.json  official standings AFTER week N (when Westgate posts it)
  results.json    scores from ESPN (fallback for the live page)
And docs/data/2026/manifest.json listing what exists.
"""
import argparse, io, json, re, sys, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, unquote

import pdfplumber
import requests
from bs4 import BeautifulSoup

from .parse import parse_card, parse_selections, parse_standings

SEASON = 2026
BASE = "https://www.westgateresorts.com/hotels/nevada/las-vegas/westgate-las-vegas-resort-casino/casino/"
PAGES = {
    "card": BASE + f"{SEASON}-supercontest-card/",
    "picks": BASE + f"{SEASON}-supercontest-selections/",
    "standings": BASE + f"{SEASON}-supercontest-standings",
}
ESPN = ("https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
        "?seasontype=2&week={week}&dates={season}")

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "data" / str(SEASON)
RAW = ROOT / "raw" / str(SEASON)          # extracted PDF text, for debugging parsers

HEADERS = {"User-Agent": "Mozilla/5.0 (personal contest tracker)"}
WEEK_RE = re.compile(r"(?:WEEK|WK)[\s_]*#?[\s_]*(\d{1,2})", re.I)

# Minimum sizes before we trust a parse enough to overwrite existing data
MIN = {"card": 8, "picks": 50, "standings": 50}


LOG = []          # shown on the site's Data tab (status.json)


def log(*a):
    msg = " ".join(str(x) for x in a)
    print(msg, flush=True)
    LOG.append(msg)


class Blocked(Exception):
    """The site refused us (4xx). Retrying won't help, so callers stop asking."""


ESPN_BLOCKED = False     # set after ESPN refuses once; skip further ESPN calls this run


def get(url, **kw):
    for attempt in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30, **kw)
            if 400 <= r.status_code < 500:
                raise Blocked(f"{r.status_code} from {url.split('?')[0]}")
            r.raise_for_status()
            return r
        except Blocked:
            raise
        except requests.RequestException as e:
            if attempt == 2:
                raise
            log(f"  retry {url}: {e}")
            time.sleep(3 * (attempt + 1))


def espn_get(url):
    """ESPN refuses GitHub's servers (403). Ask once per run, then leave scores to the browser."""
    global ESPN_BLOCKED
    if ESPN_BLOCKED:
        raise Blocked("ESPN skipped (refused earlier this run)")
    try:
        return get(url)
    except Blocked as e:
        ESPN_BLOCKED = True
        log(f"  ESPN refused this server ({e}); live scores come from the browser instead")
        raise


def list_pdfs(kind):
    """Return {week: absolute_pdf_url} from a Westgate listing page."""
    html = get(PAGES[kind]).text
    soup = BeautifulSoup(html, "html.parser")
    found = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/supercontest/download/" not in href or ".pdf" not in href.lower():
            continue
        fname = unquote(href.split("/download/", 1)[1].split("?", 1)[0])
        if "GOLD" in fname.upper() or "COLLEGE" in fname.upper() or "SURVIVOR" in fname.upper():
            continue
        m = WEEK_RE.search(fname)
        if m:
            found[int(m.group(1))] = urljoin(PAGES[kind], href).replace(" ", "%20")
    return found


def pdf_text(url):
    data = get(url).content
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)


def write_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    new = json.dumps(obj, indent=1, ensure_ascii=False)
    if path.exists() and path.read_text() == new:
        return False
    path.write_text(new)
    return True


PARSERS = {"card": parse_card, "picks": parse_selections, "standings": parse_standings}


def scrape_kind(kind, only_week=None):
    try:
        pdfs = list_pdfs(kind)
    except Exception as e:
        log(f"! could not read {kind} listing: {e}")
        return False
    log(f"{kind}: weeks listed {sorted(pdfs)}")
    latest = max(pdfs) if pdfs else None
    for week, url in sorted(pdfs.items()):
        if only_week and week != only_week:
            continue
        dest = OUT / f"week-{week}" / f"{kind}.json"
        # Past weeks are stable: skip once we have them. Always refresh the latest.
        if dest.exists() and week != latest and not only_week:
            continue
        try:
            text = pdf_text(url)
        except Exception as e:
            log(f"! {kind} week {week}: download failed: {e}")
            continue
        (RAW / f"week-{week}").mkdir(parents=True, exist_ok=True)
        (RAW / f"week-{week}" / f"{kind}.txt").write_text(text)
        rows = PARSERS[kind](text)
        if len(rows) < MIN[kind]:
            log(f"! {kind} week {week}: only {len(rows)} rows parsed; keeping old data. "
                f"Check raw/{SEASON}/week-{week}/{kind}.txt")
            continue
        payload = {"week": week, "source": url, "count": len(rows),
                   "fetched": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        payload["games" if kind == "card" else "entries" if kind == "picks" else "rows"] = rows
        # Only rewrite when content changed (ignore the fetched timestamp)
        if dest.exists():
            old = json.loads(dest.read_text())
            key = [k for k in ("games", "entries", "rows") if k in payload][0]
            if old.get(key) == rows:
                continue
        write_json(dest, payload)
        log(f"  wrote {dest.relative_to(ROOT)} ({len(rows)} rows)")
    return True


def scrape_results(week):
    """ESPN scoreboard -> results.json. Skips weeks already fully final."""
    dest = OUT / f"week-{week}" / "results.json"
    if dest.exists():
        old = json.loads(dest.read_text())
        if old.get("games") and all(g["state"] == "post" and "POSTPONED" not in (g.get("status") or "")
                                    for g in old["games"]):
            return
    try:
        data = espn_get(ESPN.format(week=week, season=SEASON)).json()
    except Blocked:
        return                            # already noted once this run; the browser handles scores
    except Exception as e:
        log(f"! ESPN week {week}: {e}")
        return
    games = []
    for ev in data.get("events", []):
        comp = ev["competitions"][0]
        st = comp.get("status", ev.get("status", {}))["type"]
        g = {"espn_id": ev["id"], "kickoff": ev.get("date"), "state": st.get("state"),
             "detail": st.get("shortDetail"), "status": st.get("name")}
        for c in comp["competitors"]:
            side = c["homeAway"]
            g[side] = c["team"]["abbreviation"]
            g[side + "_score"] = int(c["score"]) if str(c.get("score", "")).isdigit() else None
        games.append(g)
    if write_json(dest, {"week": week, "games": games}):
        log(f"  wrote results week {week} ({sum(g['state']=='post' for g in games)}/{len(games)} final)")


def write_status():
    """Last run's notable lines, for the site's Data tab (no digging through Actions logs)."""
    keep = [l.strip() for l in LOG if l.startswith("!") or l.strip().startswith(("college", "ESPN", "gold", "survivor")) or "wrote" in l or "  ESPN" in l]
    write_json(ROOT / "docs" / "data" / "status.json",
               {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "lines": keep[-80:]})


def build_manifest():
    weeks = {}
    for d in sorted(OUT.glob("week-*"), key=lambda p: int(p.name.split("-")[1])):
        w = int(d.name.split("-")[1])
        weeks[w] = {k: (d / f"{k}.json").exists() for k in ("card", "picks", "standings", "results", "overrides")}
    write_json(OUT / "manifest.json", {"season": SEASON, "weeks": weeks})
    top = ROOT / "docs" / "data" / "seasons.json"
    write_json(top, {"current": SEASON, "seasons": [SEASON]})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", type=int)
    args = ap.parse_args()
    ok = True
    for kind in ("card", "picks", "standings"):
        ok &= scrape_kind(kind, args.week)
    for d in OUT.glob("week-*"):
        if (d / "card.json").exists():
            w = int(d.name.split("-")[1])
            if not args.week or w == args.week:
                scrape_results(w)
    build_manifest()
    write_status()
    if not args.week:                     # college contest (its own pages and folder)
        try:
            from . import college_scrape
            ok &= college_scrape.run()
        except Exception as e:
            log(f"! college update failed: {e}")
            ok = False
        try:                              # SuperContest Gold and Survivor
            from . import extra_scrape
            ok &= extra_scrape.run()
        except Exception as e:
            log(f"! gold/survivor update failed: {e}")
            ok = False
        try:                              # Circa Sports (Survivor now, Millio later)
            from . import circa_scrape
            ok &= circa_scrape.run()
        except Exception as e:
            log(f"! circa update failed: {e}")
            ok = False
    write_status()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
