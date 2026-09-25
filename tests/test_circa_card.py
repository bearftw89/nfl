"""Circa Million spreads sheet: outlined text, read via vector layout + OCR. Needs tesseract."""
import json
import shutil
import unittest
from pathlib import Path

from scraper.circa_card import parse_million_card
from scraper.circa_scrape import classify, week_of
from scraper.teams import TEAMS

FIX = Path(__file__).parent / "fixtures" / "Circa-Sports-Million-VIII-Contest-Point-Spreads-Week-3.pdf"
WEEK3 = {  # (fav, line, dog) straight off the sheet
    ("GB", -4.5, "ATL"), ("SEA", -7.5, "WSH"), ("CIN", -3.5, "PIT"), ("DET", -6.5, "NYJ"), ("NYG", -2.5, "TEN"),
    ("JAX", -3, "NE"), ("KC", -11.5, "MIA"), ("HOU", -1.5, "IND"), ("CAR", -2.5, "CLE"), ("BUF", -7, "LAC"),
    ("MIN", -1, "TB"), ("SF", -8.5, "ARI"), ("NO", -3, "LV"), ("BAL", -3, "DAL"), ("LAR", -2.5, "DEN"), ("PHI", -4.5, "CHI")}


@unittest.skipUnless(shutil.which("tesseract"), "tesseract not installed")
class CircaCard(unittest.TestCase):
    def test_week3(self):
        games, problems = parse_million_card(FIX.read_bytes(), TEAMS)
        self.assertEqual(problems, [])
        self.assertEqual({(g["fav"]["abbr"], g["fav"]["line"], g["dog"]["abbr"]) for g in games}, WEEK3)
        self.assertTrue(all(g["dog"]["line"] == -g["fav"]["line"] for g in games))
        brazil = next(g for g in games if g["fav"]["abbr"] == "BAL")
        self.assertTrue(brazil["neutral"])
        self.assertFalse(brazil["fav"]["home"] or brazil["dog"]["home"])


class Discover(unittest.TestCase):
    def test_classify(self):
        n = "Circa-Sports-Million-VIII-Contest-Point-Spreads-Week-3.pdf"
        self.assertEqual(classify(n), ("millio", "card"))
        self.assertEqual(week_of(n), 3)


if __name__ == "__main__":
    unittest.main()
