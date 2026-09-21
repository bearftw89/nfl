"""College parser tests against the real 2026 Westgate PDFs (extracted text)."""
from collections import Counter
from pathlib import Path
from scraper.college import parse_card, parse_selections, map_abbreviations, derive_results, canon
from scraper.parse import parse_standings

F = Path(__file__).parent / "fixtures"
read = lambda n: (F / n).read_text()


def card_for(w):
    games = parse_card(read(f"college_card_w{w}.txt"))
    for g in games:                       # the shape the updater stores
        for s in ("fav", "dog"):
            g[s]["abbr"] = g[s]["name"]
    return games


def test_cards_complete():
    counts = {w: len(card_for(w)) for w in (1, 2, 3)}
    assert counts == {1: 42, 2: 49, 3: 57}
    g3 = {g["fav"]["num"]: g for g in card_for(3)}
    # rows whose favorite a naive text extraction loses, and the two neutral sites
    assert g3[65]["fav"]["name"] == "APPALACHIAN STATE" and g3[65]["dog"]["name"] == "CHARLOTTE"
    assert g3[71]["fav"]["name"] == "JACKSONVILLE STATE" and g3[109]["fav"]["name"] == "NORTH DAKOTA STATE"
    assert g3[9]["site"] == "London, Eng" and g3[83]["site"] == "Charlotte, Nc"
    assert g3[1]["date"] == "2026-09-17" and g3[113]["date"] == "2026-09-19"


def test_canonical_names():
    assert canon("MIAMI-FLORIDA") == canon("MIAMI-FL") == "MIAMI-FL"
    assert canon("SOUTHERN MISSISSIPPI") == canon("SOUTHERN MISS") == "SOUTHERN MISS"
    assert canon("MID TENNESSEE ST") == canon("MIDDLE TENNESSEE ST") == "MIDDLE TENNESSEE"
    assert canon("ARIZONA ST") == "ARIZONA STATE" and canon("CAL") == "CALIFORNIA"


def test_selections_match_count_table():
    for w, n in ((1, 774), (3, 778)):
        entries, table = parse_selections(read(f"college_sel_w{w}.txt"))
        assert len(entries) == n
        assert all(len(e["picks"]) == 7 for e in entries)
        assert Counter(a for e in entries for a in e["picks"]) == Counter(table)   # every team, every count
        names = [s["name"] for g in parse_card(read(f"college_card_w{w}.txt")) for s in (g["fav"], g["dog"])]
        m = map_abbreviations(table.keys(), names)
        assert m["N` WESTERN" if w == 3 else "MIAMI FL"] in ("NORTHWESTERN", "MIAMI-FL")
    assert "UNLV" in parse_selections(read("college_sel_w1.txt"))[1]            # "UNLV -2½" quirk


def test_week3_reconciles_with_official_standings():
    card = card_for(3)
    entries, table = parse_selections(read("college_sel_w3.txt"))
    m = map_abbreviations(table.keys(), [s["abbr"] for g in card for s in (g["fav"], g["dog"])])
    picks = [{"id": e["id"], "picks": [m[a] for a in e["picks"]]} for e in entries]
    now = {r["id"]: r for r in parse_standings(read("college_stand_w3.txt"))}
    prev = parse_standings(read("college_stand_w2.txt"))
    res, bad = derive_results(card, picks, now, prev)
    assert bad == 0 and len(res) == 114                # all 57 games, all 778 entries agree
    assert res["HOUSTON"] == "W" and res["TEXAS TECH"] == "L"
