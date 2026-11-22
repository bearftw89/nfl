from scraper.scrape import WEEK_RE


def wk(name):
    m = WEEK_RE.search(name)
    return int(m.group(1)) if m else None


def test_westgate_file_names():
    assert wk("2026 SUPERCONTEST GAME SHEET WEEK 9.pdf") == 9
    assert wk("2026 SUPERCONTEST GAME SHEET WK 10.pdf") == 10
    # week 11 had neither WEEK nor WK; the scraper never saw it and the main contest skipped the week
    assert wk("2026 SUPERCONTEST GAME SHEET 11.pdf") == 11
    assert wk("2026 GOLD GAME SHEET WEEK 11.pdf") == 11
    assert wk("2026 SUPERCONTEST COLLEGE WK 11.pdf") == 11
    # the year alone must never read as a week
    assert wk("2026 SUPERCONTEST RULES.pdf") is None
