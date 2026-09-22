"""Survivor and Gold parsers against the real 2026 Westgate PDFs."""
from collections import Counter
from pathlib import Path
import pdfplumber
from scraper.survivor import parse_card, parse_selections, parse_used, survivor_state
from scraper.parse import parse_selections as parse_nfl_selections
from scraper.extra_scrape import nfl_count_table

F = Path(__file__).parent / "fixtures"
read = lambda n: (F / n).read_text()

# Week 1 straight-up winners (actual finals)
W1_WINNERS = {"SEA", "SF", "JAX", "CIN", "BAL", "PIT", "BUF", "CHI", "NYJ", "DET", "ARI", "LV", "PHI", "MIN", "NYG", "KC"}


def test_survivor_card():
    g = parse_card(read("surv_card_w1.txt"))
    assert len(g) == 16 and g[0]["away"]["abbr"] == "NE" and g[0]["home"]["abbr"] == "SEA"


def test_survivor_selections_match_count_tables():
    for f, n in (("surv_sel_w1.txt", 135), ("surv_sel_w2.txt", 89)):
        entries, table = parse_selections(read(f))
        assert len(entries) == n
        assert Counter(e["pick"] for e in entries) == Counter(table)


def test_week1_survivors_match_westgate_grid():
    picks = {e["id"]: e["pick"] for e in parse_selections(read("surv_sel_w1.txt"))[0]}
    results = {t: ("W" if t in W1_WINNERS else "L") for t in set(picks.values())}
    st = survivor_state([1], {1: picks}, {1: results})
    alive = {e for e, s in st.items() if s["alive"]}
    with pdfplumber.open(F / "surv_used_w1.pdf") as pdf:
        used = parse_used(pdf)
    assert alive == set(used) and len(alive) == 89
    assert all(used[e] == [picks[e]] for e in used)          # grid shows the team each survivor used


def test_gold_selections_match_count_table():
    text = read("gold_sel_w2.txt")
    entries = parse_nfl_selections(text)
    assert len(entries) == 66
    assert Counter(a for e in entries for a in e["picks"]) == nfl_count_table(text)
