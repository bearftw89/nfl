"""Circa PDF discovery from the X feed embedded on circasports.com (no network)."""
from scraper import circa_scrape as CS

SURVIVOR_PAGE = """
<div class="sbi-tweet"><p>#CircaSurvivor 2026 Week 2 Selections
<a href="https://t.co/gc8GMOQGxk">https://t.co/gc8GMOQGxk</a> pic.twitter.com/iXkN6j8ISc</p></div>
<a href="/wp-content/uploads/2026/06/CircaSportsSurvivorContest.2026-FinalRules-19-JUNE-2026.pdf">Rules</a>
"""
BLOG_PAGE = """
<p>#CircaGrandissimo 2026 Week 1 Selections
https://www.circasports.com/wp-content/uploads/2026/09/Circa-Grandissimo-2026-Week-1-Selections.pdf</p>
<p>Old: https://circasports.com/wp-content/uploads/2025/09/Circa-Survivor-2025-Week-3-Selections.pdf</p>
"""


def test_tweet_links_found(monkeypatch):
    monkeypatch.setattr(CS, "resolve_tco", lambda links: {
        u: "https://www.circasports.com/wp-content/uploads/2026/09/Circa-Survivor-2026-Week-2-Selections.pdf"
        for u in links})
    found = {}
    for html, base in ((SURVIVOR_PAGE, CS.PAGES["survivor"]), (BLOG_PAGE, CS.FEED_PAGES[0])):
        for u in CS.pdf_links(html, base):
            CS.add_found(found, u)
    assert found[("survivor", "picks", 2)].endswith("Circa-Survivor-2026-Week-2-Selections.pdf")
    assert found[("grandissimo", "picks", 1)].endswith("Circa-Grandissimo-2026-Week-1-Selections.pdf")
    assert ("survivor", "picks", 3) not in found          # 2025 file ignored
    assert len(found) == 2                                  # rules PDF isn't a contest file


def test_million_standings_skips_quarter_only_and_last_place():
    # Week 5 posts both a full-season and a 2nd-quarter standings PDF; the quarter-only one
    # (5-0 records) used to overwrite the full-season totals.
    c = CS.classify
    assert c("Circa-Sports-Million-VIII-Full-Season-Standings-After-Week-5.pdf") == ("millio", "standings")
    assert c("Circa-Sports-Million-VIII-2nd-Quarter-Standings-After-Week-5.pdf") is None
    assert c("Circa-Sports-Million-VIII-2nd-Quarter-Last-Place-Leaders-After-Week-5.pdf") is None
    assert c("Circa-Sports-Million-VIII-Full-Season-Last-Place-Leaders-After-Week-5.pdf") is None
    # 1st-quarter files are full-season totals (quarter 1 is weeks 1-4) and must still be read
    assert c("Circa-Sports-Million-VIII-Full-Season-1st-Quarter-Standings-After-Week-3.pdf") == ("millio", "standings")
    assert c("Circa-Sports-Million-VIII-Full-Season-Standings-1st-Quarter-Winners-After-Week-4.pdf") == ("millio", "standings")
