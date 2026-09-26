"""Updater for the SuperContest College contest -> docs/data/<season>/ncaaf/week-N/.

Files per week:
  card.json       games with contest lines; each game gets an espn_id once paired with ESPN
  picks.json      every entry's 7 picks (game-sheet team names) + short labels
  standings.json  official standings after the week
  results.json    ESPN scores for the week's games
  overrides.json  {"official": {...}} which side covered, worked out from Westgate's standings
                  (a fallback for any game ESPN couldn't be matched to); manual "results" kept
"""
import json
from pathlib import Path
from urllib.parse import urljoin, unquote

from bs4 import BeautifulSoup

from . import scrape as S
from .lines import missed_rows
from .college import parse_card, parse_selections, map_abbreviations, derive_results, match_espn, _team_keys, _wanted
from .parse import parse_standings

PAGES = {
    "card": S.BASE + f"{S.SEASON}-supercontest-college-card/",
    "picks": S.BASE + f"{S.SEASON}-supercontest-college-selections",
    "standings": S.BASE + f"{S.SEASON}-supercontest-college-standings/",
}
OUT = S.ROOT / "docs" / "data" / str(S.SEASON) / "ncaaf"
RAW = S.ROOT / "raw" / str(S.SEASON) / "ncaaf"
ESPN = ("https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard"
        "?dates={date}&groups={group}&limit=400")
MIN = {"card": 20, "picks": 100, "standings": 100}


def wk(w):
    return OUT / f"week-{w}"


def load(path):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return None


def list_pdfs(kind):
    soup = BeautifulSoup(S.get(PAGES[kind]).text, "html.parser")
    found = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/supercontest/download/" not in href or ".pdf" not in href.lower():
            continue
        fname = unquote(href.split("/download/", 1)[1].split("?", 1)[0])
        if "COLLEGE" not in fname.upper():
            continue
        m = S.WEEK_RE.search(fname)
        if m:
            found[int(m.group(1))] = urljoin(PAGES[kind], href).replace(" ", "%20")
    return found


def fetch_text(kind, week, url):
    text = S.pdf_text(url)
    (RAW / f"week-{week}").mkdir(parents=True, exist_ok=True)
    (RAW / f"week-{week}" / f"{kind}.txt").write_text(text)
    return text


def save_card(week, url, text):
    games = parse_card(text)
    miss = missed_rows(text, games)
    if miss:
        S.log(f"! college card week {week}: couldn't read {len(miss)} row(s), those games are missing: {miss}")
    if len(games) < MIN["card"]:
        S.log(f"! college card week {week}: only {len(games)} games parsed; keeping old data")
        return False
    old = load(wk(week) / "card.json")
    old_by_row = {(g["fav"]["abbr"], g["dog"]["abbr"]): g for g in (old or {}).get("games", [])}
    out = []
    for g in games:
        row = {"id": g["id"], "date": g["date"], "time_pt": g["time_pt"], "site": g["site"],
               "fav": {**g["fav"], "abbr": g["fav"]["name"]}, "dog": {**g["dog"], "abbr": g["dog"]["name"]}}
        for side in ("fav", "dog"):
            row[side].pop("name", None)
        prev = old_by_row.get((row["fav"]["abbr"], row["dog"]["abbr"]))
        if prev:                                   # keep ESPN pairing and labels already worked out
            if prev.get("espn_id"):
                row["espn_id"] = prev["espn_id"]
            for side in ("fav", "dog"):
                if prev[side].get("label"):
                    row[side]["label"] = prev[side]["label"]
        out.append(row)
    if old and [(_g["fav"], _g["dog"], _g.get("espn_id")) for _g in old["games"]] == \
            [(_g["fav"], _g["dog"], _g.get("espn_id")) for _g in out]:
        return True
    S.write_json(wk(week) / "card.json", {"week": week, "source": url, "count": len(out), "games": out})
    S.log(f"  college card week {week}: {len(out)} games")
    return True


def save_picks(week, url, text):
    card = load(wk(week) / "card.json")
    if not card:
        S.log(f"! college picks week {week}: no game sheet yet; will retry")
        return False
    entries, table = parse_selections(text)
    names = [s["abbr"] for g in card["games"] for s in (g["fav"], g["dog"])]
    try:
        mapping = map_abbreviations(table.keys(), names)
    except ValueError as e:
        bad = getattr(e, "bad", [])
        if bad and all(not c for _, c in bad):
            S.log(f"! college picks week {week}: {[a for a, _ in bad]} match nothing on the card. "
                  f"Usually a game the card parser dropped (see card warnings / raw card.txt), "
                  f"otherwise add the spelling to ALIASES in scraper/college.py")
        else:
            S.log(f"! college picks week {week}: {e}. Add the spelling to ALIASES in scraper/college.py")
        return False
    total = sum(len(e["picks"]) for e in entries)
    if len(entries) < MIN["picks"] or total != sum(table.values()):
        S.log(f"! college picks week {week}: {len(entries)} entries / {total} picks vs "
              f"{sum(table.values())} in Westgate's count table; keeping old data")
        return False
    labels = {n: a for a, n in mapping.items()}
    rows = [{"id": e["id"], "picks": [mapping[a] for a in e["picks"]]} for e in entries]
    old = load(wk(week) / "picks.json")
    if not old or old.get("entries") != rows:
        S.write_json(wk(week) / "picks.json", {"week": week, "source": url, "count": len(rows),
                                               "entries": rows, "labels": labels})
        S.log(f"  college picks week {week}: {len(rows)} entries (count table matches)")
    # short labels on the card ("N CAROLINA" for NORTH CAROLINA)
    changed = False
    for g in card["games"]:
        for side in ("fav", "dog"):
            lab = labels.get(g[side]["abbr"])
            if lab and g[side].get("label") != lab:
                g[side]["label"] = lab; changed = True
    if changed:
        S.write_json(wk(week) / "card.json", card)
    return True


def save_standings(week, url, text):
    rows = parse_standings(text)
    if len(rows) < MIN["standings"]:
        S.log(f"! college standings week {week}: only {len(rows)} rows; keeping old data")
        return False
    old = load(wk(week) / "standings.json")
    if not old or old.get("rows") != rows:
        S.write_json(wk(week) / "standings.json", {"week": week, "source": url, "count": len(rows), "rows": rows})
        S.log(f"  college standings week {week}: {len(rows)} rows")
    return True


SAVERS = {"card": save_card, "picks": save_picks, "standings": save_standings}


def scrape_kind(kind):
    try:
        pdfs = list_pdfs(kind)
    except Exception as e:
        S.log(f"! could not read college {kind} listing: {e}")
        return False
    S.log(f"college {kind}: weeks listed {sorted(pdfs)}")
    latest = max(pdfs) if pdfs else None
    for week, url in sorted(pdfs.items()):
        if (wk(week) / f"{kind}.json").exists() and week != latest:
            continue
        try:
            SAVERS[kind](week, url, fetch_text(kind, week, url))
        except Exception as e:
            S.log(f"! college {kind} week {week}: {e}")   # keeping old data; retried next run
    return True


def espn_events(dates):
    events = {}
    for d in dates:
        for group in (80, 81):                      # FBS, then FCS (North Dakota State etc.)
            try:
                data = S.espn_get(ESPN.format(date=d.replace("-", ""), group=group)).json()
            except S.Blocked:
                return list(events.values())
            except Exception as e:
                S.log(f"! ESPN college {d} group {group}: {e}")
                continue
            for e in data.get("events", []):
                events[e["id"]] = e
    return list(events.values())


def scrape_results(week):
    card = load(wk(week) / "card.json")
    if not card:
        return
    old = load(wk(week) / "results.json")
    if old and old.get("games") and len(old["games"]) == len(card["games"]) and \
            all(g["state"] == "post" for g in old["games"]):
        return
    events = espn_events(sorted({g["date"] for g in card["games"] if g.get("date")}))
    if not events:
        return
    pairs = match_espn(card["games"], events)
    games, new_ids = [], False
    for g in card["games"]:
        e = pairs.get(g["id"])
        if not e:
            continue
        if g.get("espn_id") != e["id"]:
            g["espn_id"] = e["id"]; new_ids = True
        comp = e["competitions"][0]
        st = comp.get("status", e.get("status", {}))["type"]
        row = {"espn_id": e["id"], "kickoff": e.get("date"), "state": st.get("state"),
               "status": st.get("name"), "detail": st.get("shortDetail")}
        for c in comp["competitors"]:
            # which game-sheet team is this ESPN competitor?
            mine = g["fav"]["abbr"] if _team_keys(c["team"]) & _wanted(g["fav"]["abbr"]) else g["dog"]["abbr"]
            row[c["homeAway"]] = mine
            row[c["homeAway"] + "_score"] = int(c["score"]) if str(c.get("score", "")).isdigit() else None
        if row.get("home") == row.get("away"):     # couldn't tell sides apart; skip rather than guess
            continue
        games.append(row)
    unmatched = [f"{g['fav']['abbr']} v {g['dog']['abbr']}" for g in card["games"] if g["id"] not in pairs]
    if unmatched:
        S.log(f"  college week {week}: no ESPN game found for {len(unmatched)}: {unmatched}")
    if new_ids:
        S.write_json(wk(week) / "card.json", card)
    if S.write_json(wk(week) / "results.json", {"week": week, "games": games, "unmatched": unmatched}):
        S.log(f"  college results week {week}: {sum(g['state'] == 'post' for g in games)}/{len(card['games'])} final")


def official_results(week):
    """Which side covered, from Westgate's own standings (needs this week's and last week's)."""
    card, picks, now = (load(wk(week) / f) for f in ("card.json", "picks.json", "standings.json"))
    prev = load(wk(week - 1) / "standings.json") if week > 1 else {"rows": []}
    if not (card and picks and now and prev is not None):
        return
    res, bad = derive_results(card["games"], picks["entries"], {r["id"]: r for r in now["rows"]}, prev["rows"])
    if bad:
        S.log(f"! college week {week}: official records don't reconcile for {bad} entries; skipping")
        return
    path = wk(week) / "overrides.json"
    doc = load(path) or {}
    if doc.get("official") != res:
        doc["official"] = res
        S.write_json(path, doc)
        S.log(f"  college week {week}: covers confirmed from official standings ({len(res) // 2} games)")


def build_manifest():
    weeks = {}
    for d in sorted(OUT.glob("week-*"), key=lambda p: int(p.name.split("-")[1])):
        w = int(d.name.split("-")[1])
        weeks[w] = {k: (d / f"{k}.json").exists() for k in ("card", "picks", "standings", "results", "overrides")}
    S.write_json(OUT / "manifest.json", {"season": S.SEASON, "league": "ncaaf", "picks_per_entry": 7, "weeks": weeks})


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    ok = True
    for kind in ("card", "picks", "standings"):
        ok &= scrape_kind(kind)
    for d in sorted(OUT.glob("week-*"), key=lambda p: int(p.name.split("-")[1])):
        w = int(d.name.split("-")[1])
        try:
            scrape_results(w)
            official_results(w)
        except Exception as e:
            S.log(f"! college week {w} results: {e}")   # non-fatal; retried next run
    build_manifest()
    return ok
