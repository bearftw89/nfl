"""Updater for Circa Sports contests, hosted on circasports.com (not Westgate).

Circa posts weekly PDFs to WordPress under /wp-content/uploads/YYYY/MM/. The month is the
posting month, not the NFL week, and file names aren't perfectly uniform, so we DISCOVER
links from the two contest pages rather than guessing URLs. If discovery fails (the page
markup changed, or the run can't reach circasports.com), a committed PDF placed in
raw/circa/ is used as a fallback.

  circa-survivor    -> docs/data/<season>/circa-survivor/week-N/{picks,used}.json
  circa-grandissimo -> docs/data/<season>/circa-grandissimo/week-N/{picks,used}.json
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
         "grandissimo": "https://www.circasports.com/grandissimo",
         "millio": "https://www.circasports.com/circa-million"}
CURRENT_SEASON_TAG = "VIII"     # Circa Million/Survivor's roman-numeral season label
# file-name signatures -> (contest, kind)
SIGN = [
    (re.compile(r"GRANDISSIMO.*TEAM.*AVAIL", re.I), ("grandissimo", "used")),
    (re.compile(r"GRANDISSIMO.*SELECTION", re.I), ("grandissimo", "picks")),
    (re.compile(r"SURVIVOR.*TEAM.*AVAIL", re.I), ("survivor", "used")),
    (re.compile(r"SURVIVOR.*SELECTION", re.I), ("survivor", "picks")),
    (re.compile(r"MILLION.*STANDING", re.I), ("millio", "standings")),
    (re.compile(r"MILLION.*SELECTION", re.I), ("millio", "picks")),
]
OUT = {"survivor": DATA / "circa-survivor", "grandissimo": DATA / "circa-grandissimo", "millio": DATA / "circa-millio"}
SURVIVOR_LIKE = ("survivor", "grandissimo")          # same file formats, same rules
MIN_ROWS = {"survivor": 100, "grandissimo": 1}       # Grandissimo is a small field (dozens of entries)


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
    """A week number more than one ahead of where the season actually is is not real data for
    the current run — either an old season's archived file slipped past is_current_season(),
    or a rare quirk elsewhere. Kept as a defense-in-depth backstop."""
    return week <= current + 1


def is_current_season(fname):
    """The Circa Million page also links every PAST season's results (VII, VI, V, IV, III, II —
    2020-2025), each with its own perfectly legitimate "After Week 4/9/13/18" in the filename.
    Without this check those get mistaken for this season's not-yet-played future weeks."""
    m = (re.search(r"MILLION[\s-]+([IVX]+)", fname, re.I) or re.search(r"SURVIVOR[\s-]+(\d{4})", fname, re.I)
         or re.search(r"GRANDISSIMO[\s-]+(\d{4})", fname, re.I))
    return not m or m.group(1).upper() == CURRENT_SEASON_TAG or m.group(1) == str(S.SEASON)


def classify(fname):
    for rx, tag in SIGN:
        if rx.search(fname):
            return tag
    return None


_CONTENT_WEEK = re.compile(r"(?:AFTER|THROUGH)\s+WEEK\s+(\d{1,2})", re.I)


def content_week(text):
    """The real week a standings/availability PDF covers, read from its own header text —
    a cheap sanity cross-check against whatever week the filename/URL implied."""
    m = _CONTENT_WEEK.search(text)
    return int(m.group(1)) if m else None


def week_of(fname):
    # "...Week-2-Selections", "...After-Week-1", "...Contest-Point-Spreads-Week-2"
    m = re.search(r"WEEK[\s_-]*#?(\d{1,2})", fname, re.I)
    return int(m.group(1)) if m else None


# Circa announces each PDF in a tweet. Their site embeds that X feed, so the tweets can be read
# from circasports.com itself, with no X account or API. The contest pages link each tweet's PDF
# as a t.co short link; the contests blog shows the full wp-content URL as text.
FEED_PAGES = ["https://www.circasports.com/blog/category/contests"]
UPLOAD_RE = re.compile(r"https?://(?:www\.)?circasports\.com/wp-content/uploads/\d{4}/\d{2}/[\w.%-]+?\.pdf", re.I)
TCO_RE = re.compile(r"https?://t\.co/[A-Za-z0-9]{6,15}")
TCO_CACHE = RAWDIR / "tco.json"          # short link -> where it points (never changes), so each is resolved once
TCO_MAX = 40                             # new short links to resolve per run


def resolve_tco(links):
    """Where each t.co link points, from its redirect. Cached, since a short link never changes."""
    import requests
    cache = load(TCO_CACHE) or {}
    new = 0
    for u in links:
        if u in cache or new >= TCO_MAX:
            continue
        new += 1
        try:
            r = requests.get(u, headers={"User-Agent": "curl/8.5"}, allow_redirects=False, timeout=15)
            dest = r.headers.get("Location") or ""
            if not dest:                  # browser-style reply: the target sits in the page
                m = re.search(r"URL=([^\"'>]+)", r.text or "", re.I)
                dest = m.group(1) if m else ""
            cache[u] = dest
        except Exception as e:
            S.log(f"  circa: could not resolve {u}: {e}")
    if new:
        S.write_json(TCO_CACHE, cache)
    return {u: cache.get(u, "") for u in links}


def pdf_links(html, base):
    """Every Circa PDF URL a page mentions: plain links, wp-content URLs in tweet text, and
    t.co links from the embedded X feed."""
    urls = set(UPLOAD_RE.findall(html))
    for a in BeautifulSoup(html, "html.parser").find_all("a", href=True):
        if ".pdf" in a["href"].lower():
            urls.add(urljoin(base, a["href"]))
    tco = sorted(set(TCO_RE.findall(html)))
    urls.update(d for d in resolve_tco(tco).values() if ".pdf" in d.lower())
    return urls


def add_found(found, url):
    fname = unquote(url.split("?")[0].split("/")[-1])
    if not is_current_season(fname):
        return
    tag, wk = classify(fname), week_of(fname)
    if tag and wk:
        found.setdefault((tag[0], tag[1], wk), url.replace(" ", "%20"))


def probe(found, current):
    """Survivor and Grandissimo files are named the same way every week, so for a week the pages
    don't show yet, check the expected upload URLs directly (this month's and last month's folder)."""
    import requests
    from datetime import date
    today = date.today()
    months = [today, date(today.year - (today.month == 1), (today.month - 2) % 12 + 1, 1)]
    names = {("survivor", "picks"): "Circa-Survivor-{y}-Week-{w}-Selections.pdf",
             ("survivor", "used"): "Circa-Survivor-{y}-Week-{w}-Team-Availability.pdf",
             ("grandissimo", "picks"): "Circa-Grandissimo-{y}-Week-{w}-Selections.pdf",
             ("grandissimo", "used"): "Circa-Grandissimo-{y}-Week-{w}-Team-Availability.pdf"}
    for (contest, kind), pat in names.items():
        for w in (current, current + 1):
            if (contest, kind, w) in found or (OUT[contest] / f"week-{w}" / f"{kind}.json").exists():
                continue
            for d in months:
                url = (f"https://www.circasports.com/wp-content/uploads/{d.year}/{d.month:02d}/"
                       + pat.format(y=S.SEASON, w=w))
                try:
                    if requests.head(url, headers=S.HEADERS, timeout=15, allow_redirects=True).status_code == 200:
                        found[(contest, kind, w)] = url
                        S.log(f"circa {contest} {kind} week {w}: found at its usual URL")
                        break
                except Exception:
                    pass


def discover(current=None):
    """{(contest, kind, week): url} from Circa's pages and the tweets embedded in them."""
    found = {}
    for page in [*PAGES.values(), *FEED_PAGES]:
        try:
            html = S.get(page).text
        except Exception as e:
            S.log(f"! circa: could not read {page}: {e}")
            continue
        for url in sorted(pdf_links(html, page)):
            add_found(found, url)
    if current is not None:
        probe(found, current)
    S.log(f"circa: found {len(found)} current-season PDFs "
          f"({', '.join(f'{c} {k} wk{w}' for c, k, w in sorted(found)) or 'none'})")
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


def save_survivor_picks(week, src, contest="survivor"):
    entries, table = C.parse_survivor_selections(_text(_bytes(src)))
    got = Counter(e["pick"] for e in entries)
    if len(entries) < MIN_ROWS[contest] or (table and got != Counter(table)):
        S.log(f"! circa {contest} picks week {week}: {len(entries)} entries fail the count-table check; keeping old data, not a run failure")
        return True
    out = OUT[contest] / f"week-{week}"
    old = load(out / "picks.json")
    if not old or old.get("entries") != entries:
        S.write_json(out / "picks.json", {"week": week, "source": str(src), "count": len(entries), "entries": entries})
        S.log(f"  circa {contest} picks week {week}: {len(entries)} entries")
    return True


def save_survivor_used(week, src, contest="survivor"):
    data = _bytes(src)
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        real_week = content_week(pdf.pages[0].extract_text() or "") or week
        if real_week != week:
            S.log(f"  circa {contest} availability: link named 'week {week}' actually contains week {real_week} data; using week {real_week}")
        week = real_week
        if not sane_week(week, current_nfl_week()):
            S.log(f"  circa {contest} availability week {week}: skipped (beyond the current week; still a placeholder, not a problem)")
            return True
        used = C.parse_survivor_availability(pdf)
    if len(used) < MIN_ROWS[contest]:
        S.log(f"! circa {contest} availability week {week}: only {len(used)} rows; keeping old data, not a run failure")
        return True
    out = OUT[contest] / f"week-{week}"
    old = load(out / "used.json")
    if not old or old.get("entries") != used:
        S.write_json(out / "used.json", {"week": week, "source": str(src), "count": len(used), "entries": used})
        S.log(f"  circa {contest} availability through week {week}: {len(used)} entries")
    return True


def save_millio_picks(week, src):
    entries, table = C.parse_million_selections(_text(_bytes(src)))
    got = Counter(p["abbr"] for e in entries for p in e["picks"])
    if len(entries) < 50 or (table and got != Counter(table)):
        S.log(f"! circa millio picks week {week}: {len(entries)} entries fail the count-table check; keeping old data, not a run failure")
        return True
    out = OUT["millio"] / f"week-{week}"
    old = load(out / "picks.json")
    if not old or old.get("entries") != entries:
        S.write_json(out / "picks.json", {"week": week, "source": str(src), "count": len(entries), "entries": entries})
        S.log(f"  circa millio picks week {week}: {len(entries)} entries")
    return True


def save_millio_standings(week, src):
    text = _text(_bytes(src))
    real_week = content_week(text) or week
    if real_week != week:
        S.log(f"  circa millio standings: link named 'week {week}' actually contains week {real_week} data (Circa updates this file in place); using week {real_week}")
    week = real_week
    if not sane_week(week, current_nfl_week()):
        S.log(f"  circa millio standings week {week}: skipped (beyond the current week; still a placeholder, not a problem)")
        return True
    rows = C.parse_million_standings(text)
    if len(rows) < 50:
        S.log(f"! circa millio standings week {week}: only {len(rows)} rows; keeping old data, not a run failure")
        return True
    out = OUT["millio"] / f"week-{week}"
    old = load(out / "standings.json")
    if not old or old.get("rows") != rows:
        S.write_json(out / "standings.json", {"week": week, "source": str(src), "count": len(rows), "rows": rows})
        S.log(f"  circa millio standings week {week}: {len(rows)} rows")
    return True


SAVERS = {("survivor", "picks"): save_survivor_picks, ("survivor", "used"): save_survivor_used,
          ("grandissimo", "picks"): lambda w, s: save_survivor_picks(w, s, "grandissimo"),
          ("grandissimo", "used"): lambda w, s: save_survivor_used(w, s, "grandissimo"),
          ("millio", "picks"): save_millio_picks, ("millio", "standings"): save_millio_standings}


def build_manifest(contest):
    out = OUT[contest]
    kinds = ("picks", "used") if contest in SURVIVOR_LIKE else ("picks", "standings")
    weeks = {}
    for d in sorted(out.glob("week-*"), key=lambda p: int(p.name.split("-")[1])):
        weeks[int(d.name.split("-")[1])] = {k: (d / f"{k}.json").exists() for k in kinds}
    extra = {"picks_per_entry": 1} if contest in SURVIVOR_LIKE else {"picks_per_entry": 5}
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


# Circa's site links these two by their EVENTUAL target week (a quarter-end or "through" label
# chosen once, at creation), but the file behind the link is updated in place as the season
# progresses — so unlike the weekly selection sheets (confirmed one distinct URL per week), the
# filename's week number can't be trusted here at all. These are always re-fetched and re-parsed
# every run; the saver itself works out the real week from the document's own text.
EVOLVING = {("millio", "standings"), ("survivor", "used"), ("grandissimo", "used")}


def run():
    for c in OUT.values():
        c.mkdir(parents=True, exist_ok=True)
    current = current_nfl_week()
    prune_future(current)
    found = discover(current)
    for k, v in from_fallback().items():
        found.setdefault(k, v)                          # discovery wins; fallback fills gaps
    if not found:
        S.log("! circa: no PDFs found by discovery or fallback (raw/circa/)")
    skipped = [(c, k, w) for (c, k, w) in found if (c, k) not in EVOLVING and not sane_week(w, current)]
    for c, k, w in skipped:
        S.log(f"! circa {c} {k} week {w}: skipped (beyond week {current + 1}; likely a future-week placeholder link, not this week's real data)")
        del found[(c, k, w)]
    ok = True
    for (contest, kind, week), src in sorted(found.items()):
        saver = SAVERS.get((contest, kind))
        if not saver:
            continue
        if (contest, kind) not in EVOLVING:
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
