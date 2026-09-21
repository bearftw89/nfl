# Contest Board

Consensus picks and live standings for the Westgate SuperContest, updated automatically each week.

## How it works

- **Updater** (`scraper/`, a GitHub Action every 15 min): reads the Westgate game sheet, selections and standings pages, downloads each week's PDF, parses it, and saves JSON under `docs/data/2026/week-N/`. It also saves ESPN scores as a backup. It refuses to overwrite good data with a parse that comes up short.
- **Site** (`docs/index.html`, one file, hosted on GitHub Pages): pulls live scores from ESPN every 30 s while games are on (5 min otherwise), grades every pick against the contest line, and builds standings as *last official Westgate standings + later weeks as games stand now*.

Weeks 1 and 2 are already loaded (Week 1 verified: all 596 entries match Westgate's official standings).

## Tabs

- **Picks by game**: each game with the contest line, live score, and a bar of how the field split, colored by cover status. Plus the five most-picked teams.
- **Standings**: live place, movement since the last official standings, each entry's picks colored by result, W-L-T-C record, search, and a star to track entries.
- **Consensus**: every team on the card, how many entries took it, and how it did. Click a team for the entry list.
- **Teams ATS**: all 32 teams' season record against the contest line, with home/away and favorite/underdog splits, week-by-week results, and how the field did picking them.
- **Top entries**: pick "standings 1 to N"; shows what those leaders (ranked by standings *entering* the week) picked, most-picked first, and each leader's picks. Ties at the cutoff are included by default.
- **Data**: which weeks are on file.

## NCAAF (SuperContest College)

Switch with the **NFL | NCAAF** buttons at the top (or link straight to it with `#lg=ncaaf`). Every tab works for both.

- The updater also reads Westgate's College game sheet, selections and standings pages each run and saves them under `docs/data/2026/ncaaf/week-N/` (Weeks 1–14, 7 picks per entry).
- **Team names:** picks use Westgate's short names ("N CAROLINA", "MISS ST"). They're matched to the game sheet's names, and each week's picks are checked against Westgate's own team-count table before anything is saved. A new spelling that can't be matched stops that week (red X in Actions) instead of guessing; add it to `ALIASES` in `scraper/college.py`.
- **Scores:** the updater pairs each game-sheet row with its ESPN game. The page then pulls live college scores by that ID. Any game that couldn't be paired is listed in the Action log.
- **Safety net:** once Westgate posts a week's official standings, the updater works out which side covered every game from them and saves it (`overrides.json`, key `official`). Those results are used for any game ESPN couldn't be matched to. Weeks 1–3 were loaded this way, and every entry's record matched Westgate's official standings exactly.

## Contest rules implemented (2026 SuperContest rules)

- **Graded against the spread, never the straight score.** Pick result = team score + contest line vs. opponent score, using the static Westgate line from the weekly card.
- **Rule 8:** cover = 1 point, push = ½ point, loss = 0.
- **Rule 12:** an entry with no picks for a week gets 0 that week.
- **Rule 15:** if an entry appears twice on a selections sheet, the first one counts.
- **Rule 22:** a postponed/cancelled game stays pending until Tuesday 11:59 PM PT of that week; if unplayed by then, every pick on it gets ½ point and shows as **C** (the C in W-L-T-C).
- **Rule 8 forfeits and any grading correction:** add `docs/data/2026/week-N/overrides.json`, e.g. `{"results": {"NYJ": "W", "GB": "L"}}` (values W, L, P or C), commit it, and run the updater once so the manifest lists it. Overrides beat the score feed.
- **Rule 16 tiebreaker** only applies to the overall winner at season end; ties show as "T" like Westgate's standings.
- Westgate's posted standings always win: once they post a week, the site uses their numbers for it.

## Setup (about 10 minutes)

1. Create a new GitHub repo (public is simplest for free Pages) and push this folder to `main`.
2. **Settings → Pages**: Source = *Deploy from a branch*, Branch = `main`, folder = `/docs`.
3. **Settings → Actions → General → Workflow permissions**: *Read and write*.
4. **Actions → Update contest data → Run workflow** once to load Weeks 1 and 2 now. After that it runs on its own.
5. Open `https://<you>.github.io/<repo>/`.

Note: with free GitHub Pages the repository must be public, so the contest data (already public on Westgate's site) is visible to anyone who finds it.

Run locally instead:

```
pip install -r requirements.txt
python -m scraper.scrape
cd docs && python -m http.server 8000     # open http://localhost:8000
```

## If something breaks

- **A week didn't load**: the Action log says which PDF failed. The raw extracted text is saved in `raw/2026/week-N/` so you can see what the parser saw. Parsers are in `scraper/parse.py`, with tests in `tests/` (`python -m pytest`).
- **New team spelling** on a PDF (e.g. "NINERS"): add it to `scraper/teams.py`.
- **"Live feed unreachable"** in the header: the browser couldn't reach ESPN, so the page is using the scores the updater saved (up to ~15 min old).
- Westgate changing the PDF layout is the most likely failure point. The updater refuses to overwrite good data with a bad parse.

## Next ideas

In-season bonus contests (rule 16: 3-week, 6-week and 9-week windows), season-end tiebreaker, per-entry season history, consensus vs. field records, SuperContest Gold, alerts for your starred entries.
