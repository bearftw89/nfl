import pytest
from scraper.lines import to_float, missed_rows
from scraper import college, parse


@pytest.mark.parametrize("tok,val", [
    ("+3.5", 3.5), ("-3.5", -3.5), ("+.5", .5), ("-.5", -.5), ("+3½", 3.5), ("½", .5), ("-½", -.5),
    ("PK", 0.0), ("PICK", 0.0), ("EVEN", 0.0), ("\u22127", -7.0), ("\u20132.5", -2.5), ("10", 10.0)])
def test_to_float(tok, val):
    assert to_float(tok) == val


@pytest.mark.parametrize("tok", ["ABC", "", "3.5.5", "+"])
def test_to_float_rejects(tok):
    assert to_float(tok) is None


HDR = "COLLEGE FOOTBALL - FRIDAY, SEPTEMBER 25, 2026\n"


@pytest.mark.parametrize("line,val", [("+.5", .5), ("+3½", 3.5), ("PICK", 0.0), ("\u22127", 7.0), ("EVEN", 0.0)])
def test_college_card_line_formats(line, val):
    g = college.parse_card(HDR + f"9 CLEMSON 7:30 PM 10 CAL* {line}\n")
    assert len(g) == 1 and g[0]["dog"]["line"] == val


def test_college_card_odd_team_chars_fall_back():
    g = college.parse_card(HDR + "1 MIAMI (FL) 7:30 PM 2 TEXAS A&M* +3.5\n3 ARMY 1:00 PM 4 TEMPLE* +3.5\n")
    assert [x["fav"]["num"] for x in g] == [1, 3]


def test_missed_rows_reports_unreadable():
    text = HDR + "3 ARMY 1:00 PM 4 TEMPLE* +3.5\n9 CLEMSON 7:30 PM 10 CAL* ??\n"
    g = college.parse_card(text)
    assert missed_rows(text, g) == ["9 CLEMSON 7:30 PM 10 CAL* ??"]


def test_nfl_card_half_point():
    g = parse.parse_card("3 PACKERS 10:00 AM 4 JETS* +.5\n1 BILLS* 5:15 PM 2 LIONS PK\n")
    assert [x["dog"]["line"] for x in g] == [0.5, 0.0]
