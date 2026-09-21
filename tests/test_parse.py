from pathlib import Path
from scraper.parse import parse_card, parse_selections, parse_standings

F = Path(__file__).parent / "fixtures"

def test_card():
    g = parse_card((F / "card_w2.txt").read_text())
    assert len(g) == 16
    assert g[0]["fav"]["abbr"] == "BUF" and g[0]["fav"]["home"] and g[0]["dog"]["line"] == 4.5
    tb = g[5]; assert tb["fav"]["abbr"] == "TB" and tb["dog"]["abbr"] == "CLE"
    assert g[8]["dog"]["abbr"] == "TEN" and g[8]["dog"]["home"] and g[8]["dog"]["line"] == 7
    assert g[13]["fav"]["abbr"] == "SF" and g[13]["fav"]["line"] == -13.5

def test_selections():
    e = parse_selections((F / "sel_w2.txt").read_text())
    ids = [x["id"] for x in e]
    assert ids == ["$80K FRIDAY ALAN-1", "'@THEPAGEKC-2", "2 P.I.C.-1",
                   "DANDY'S 9ERS-2", "MARVELOUS MARK-10", "YYUR YYUB ICUR YY4ME-1"]
    assert e[1]["picks"] == ["NYJ", "TB", "HOU", "PHI", "SEA"]
    assert all(len(x["picks"]) == 5 for x in e)

def test_standings():
    s = parse_standings((F / "stand_w1.txt").read_text())
    assert [r["id"] for r in s] == ["MOTIVATION-1", "JJ & JF-1", "2 DYE 4-2",
        "'@TODDQSPORTS-1", "2345 WILLIAMS. BOYS-1", "UNDERS4PETE-1"]
    assert s[2]["place"] == "14T" and s[2]["pts"] == 4.0 and s[2]["l"] == 1

def test_card_week1_date_headers():
    # Real week 1 sheet: games directly under "PRO FOOTBALL - <DAY>, <DATE>, 2026" headers
    # used to be dropped, plus a neutral-site game (Rams vs 49ers in Melbourne).
    g = parse_card((F / "card_w1.txt").read_text())
    assert len(g) == 16
    firsts = {x["fav"]["num"] for x in g}
    assert {1, 3, 5, 31} <= firsts                     # first game of each day
    rams = next(x for x in g if x["fav"]["abbr"] == "LAR")
    assert rams["dog"]["abbr"] == "SF" and not rams["fav"]["home"] and not rams["dog"]["home"]

def test_card_header_glued_line():
    text = "PRO FOOTBALL - MONDAY, SEPTEMBER 21, 2026\n31 RAMS* 5:15 PM 32 GIANTS +7\n"
    g = parse_card(text)
    assert len(g) == 1 and g[0]["fav"]["abbr"] == "LAR" and g[0]["dog"]["line"] == 7
