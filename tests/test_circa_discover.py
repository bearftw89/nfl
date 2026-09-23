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
