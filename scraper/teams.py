"""Westgate team nicknames -> ESPN abbreviations.

Westgate uses full nicknames on the card (BUCCANEERS) and sometimes short
forms on the selections sheet (BUCS). Add aliases here if a new one shows up.
"""

TEAMS = {
    "BILLS": "BUF", "DOLPHINS": "MIA", "PATRIOTS": "NE", "JETS": "NYJ",
    "RAVENS": "BAL", "BENGALS": "CIN", "BROWNS": "CLE", "STEELERS": "PIT",
    "TEXANS": "HOU", "COLTS": "IND", "JAGUARS": "JAX", "JAGS": "JAX", "TITANS": "TEN",
    "BRONCOS": "DEN", "CHIEFS": "KC", "RAIDERS": "LV", "CHARGERS": "LAC",
    "COWBOYS": "DAL", "GIANTS": "NYG", "EAGLES": "PHI", "COMMANDERS": "WSH",
    "BEARS": "CHI", "LIONS": "DET", "PACKERS": "GB", "VIKINGS": "MIN",
    "FALCONS": "ATL", "PANTHERS": "CAR", "SAINTS": "NO",
    "BUCCANEERS": "TB", "BUCS": "TB",
    "CARDINALS": "ARI", "RAMS": "LAR", "49ERS": "SF", "NINERS": "SF", "SEAHAWKS": "SEA",
}

# Display nickname per abbreviation (first nickname listed wins)
NICK = {}
for _name, _abbr in TEAMS.items():
    NICK.setdefault(_abbr, _name.title().replace("49Ers", "49ers"))


def to_abbr(name: str):
    return TEAMS.get(name.strip().upper().rstrip("*"))
