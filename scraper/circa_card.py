"""Circa Million weekly Contest Point Spreads sheet ("Circa-Sports-Million-VIII-Contest-Point-Spreads-Week-N.pdf").

Circa exports this sheet with every letter and number converted to vector outlines, so
there's no text layer to read. The parse combines the two things that ARE reliable:

  * layout and the spread's shape, from the vector data: the horizontal rules frame each
    game; a minus sign is a small filled rect; a plus is a square outline; the ½ glyph is
    a wider full-height outline (digits are <= 8pt wide, ½ is ~9pt) with a small 1 and 2;
  * team names and the whole-number digits, from OCR (tesseract) of a 400-dpi render.
    The OCR'd digit string must have exactly as many digits as there are digit outlines,
    and every narrow outline must read as "1", or the row is rejected.

Team names are fuzzy-matched (OCR sometimes reads 49ERS as AOERS), then checked against
the week's real NFL matchups from the main SuperContest card when that's available.
Needs the `tesseract` binary (apt: tesseract-ocr).
"""
import difflib
import io
import re
import subprocess
import tempfile

import pdfplumber

RES = 400          # render dpi for OCR
VALUE_W = 62       # width (pt) of the spread cell at the right edge of each column


def _ocr(img, wl=None):
    with tempfile.NamedTemporaryFile(suffix=".png") as f:
        img.save(f.name)
        cmd = ["tesseract", f.name, "-", "--psm", "7"]
        if wl:
            cmd += ["-c", f"tessedit_char_whitelist={wl}"]
        return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.strip()


def _black(c):
    col = c.get("non_stroking_color")
    vals = col if isinstance(col, (list, tuple)) else [col]
    return col is not None and all(v == 0 for v in vals)


def _area(c):
    return (c["x1"] - c["x0"]) * (c["bottom"] - c["top"])


def _outer(cs):
    """Drop inner outlines (the holes in 4, 6, 8, 9, 0)."""
    return [c for c in cs if not any(o is not c and o["x0"] <= c["x0"] and o["x1"] >= c["x1"] and o["top"] <= c["top"]
                                     and o["bottom"] >= c["bottom"] and _area(o) > _area(c) for o in cs)]


def _spread(pg, img, s, cx0, x1, t, b):
    """(line, problem) for one spread cell."""
    cs = [c for c in pg.curves if _black(c) and c["x0"] >= cx0 and c["x1"] <= x1 + 1 and c["top"] >= t - 1 and c["bottom"] <= b + 1]
    gl = sorted(_outer(cs), key=lambda c: c["x0"])
    minus = [r for r in pg.rects if r["x0"] >= cx0 and r["x1"] <= x1 + 1 and r["top"] >= t and r["bottom"] <= b
             and r["x1"] - r["x0"] < 10 and r["bottom"] - r["top"] < 4]
    H = max((g["bottom"] - g["top"] for g in gl), default=0)
    if not H:
        return None, "empty spread cell"
    plus = [g for g in gl if g["bottom"] - g["top"] < .75 * H and abs((g["x1"] - g["x0"]) - (g["bottom"] - g["top"])) < 1.5]
    wide = [g for g in gl if g not in plus and g["x1"] - g["x0"] > 8.4 and g["bottom"] - g["top"] > .85 * H]
    half = [g for g in gl if g not in plus and any(g["x0"] >= w["x0"] - 1 and g["x1"] <= w["x1"] + 1 for w in wide)]
    digits = [g for g in gl if g not in plus and g not in half and g["bottom"] - g["top"] > .85 * H]
    if not minus and not plus and not half:          # no sign: pick'em
        txt = re.sub(r"\W", "", _ocr(img.crop((cx0 * s, t * s, (x1 + 1) * s, b * s))).upper())
        return (0.0, None) if txt in ("PK", "PICK", "PICKEM", "EVEN", "EV") else (None, f"unreadable spread {txt!r}")
    whole = 0
    if digits:
        box = (min(g["x0"] for g in digits) - 1.5, t, max(g["x1"] for g in digits) + 1.5, b)
        txt = re.sub(r"\D", "", _ocr(img.crop(tuple(v * s for v in box)), "0123456789"))
        ones = [i for i, g in enumerate(digits) if g["x1"] - g["x0"] < 5.5]
        if len(txt) != len(digits) or any(txt[i] != "1" for i in ones):
            return None, f"digits read {txt!r} but {len(digits)} digit outlines"
        whole = int(txt)
    v = whole + (.5 if half else 0)
    return (-v if minus else float(v)), None


_LABEL = re.compile(r"(\d{1,2})\s+([A-Z0-9]{3,}(?:\s+[A-Z]{2,})?)\s*$")
_TIME = re.compile(r"(\d{1,2}:\d{2})\s*([AP]M)")


def _rows(pdf_bytes):
    """Raw boxes: [{neutral, rows:[{num, name, line, err, time}, x2]}] in sheet order."""
    boxes = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        pg = pdf.pages[0]
        s = RES / 72
        img = pg.to_image(resolution=RES).original.convert("L")
        rules = [r for r in pg.rects if r["x1"] - r["x0"] > 150 and r["bottom"] - r["top"] < 2.5]
        cols = {}
        for r in rules:
            cols.setdefault(round(r["x0"] / 20), []).append(r)
        for _, rs in sorted(cols.items()):
            rs = sorted(rs, key=lambda r: r["top"])
            x0, x1 = min(r["x0"] for r in rs), max(r["x1"] for r in rs)
            for a, b in zip(rs, rs[1:]):
                gap, top, neutral = b["top"] - a["top"], a["bottom"], False
                if 60 < gap < 75:        # a header strip ("at RIO DE JANIERO, BRAZIL") sits above the game
                    top = b["top"] - gap * 2 / 3
                    neutral = _ocr(img.crop((x0 * s, a["bottom"] * s, x1 * s, top * s))).lower().startswith("at ")
                elif not 38 < gap < 50:
                    continue
                mid = (top + b["top"]) / 2
                rows = []
                for t, bt in ((top, mid), (mid, b["top"])):
                    label = re.sub(r"['‘’`]", "", _ocr(img.crop((x0 * s, t * s, (x1 - VALUE_W) * s, bt * s))).upper())
                    m = _LABEL.search(label)
                    if not m:
                        rows.append(None)
                        continue
                    line, err = _spread(pg, img, s, x1 - VALUE_W, x1, t, bt)
                    tm = _TIME.search(label)
                    rows.append({"num": int(m.group(1)), "name": m.group(2), "line": line, "err": err,
                                 "time": f"{tm.group(1)} {tm.group(2)}" if tm else None})
                if rows == [None, None]:
                    continue             # blank spacer between boxes
                boxes.append({"neutral": neutral, "rows": rows})
    return boxes


def _assign(names, teams):
    """OCR'd names -> abbreviations, best matches first, each team used once."""
    keys = list(teams)
    cand = sorted(((difflib.SequenceMatcher(None, n, k).ratio(), i, teams[k]) for i, n in enumerate(names) for k in keys), reverse=True)
    out, used = [None] * len(names), set()
    for r, i, ab in cand:
        if r < .5 or out[i] is not None or ab in used:
            continue
        out[i] = ab
        used.add(ab)
    return out


def parse_million_card(pdf_bytes, teams, nfl_games=None):
    """(games, problems). games use the SuperContest card shape:
    {id, time_pt, neutral, fav:{num, abbr, home, line}, dog:{...}}; bottom row is home unless neutral.
    nfl_games: the main card's games, used to check/repair team names against real matchups."""
    boxes, problems = _rows(pdf_bytes), []
    flat = [r for bx in boxes for r in bx["rows"] if r]
    for r, ab in zip(flat, _assign([r["name"] for r in flat], teams)):
        r["abbr"] = ab
    opp = {}
    for g in nfl_games or []:
        opp[g["fav"]["abbr"]], opp[g["dog"]["abbr"]] = g["dog"]["abbr"], g["fav"]["abbr"]
    games = []
    for bx in boxes:
        away, home = bx["rows"]
        if not away or not home:
            problems.append(f"game box with an unreadable row: {away or home}")
            continue
        if opp and opp.get(away["abbr"]) != home["abbr"]:     # repair one bad name from the real matchup
            if opp.get(away["abbr"]) and home["abbr"] not in opp:
                home["abbr"] = opp[away["abbr"]]
            elif opp.get(home["abbr"]) and away["abbr"] not in opp:
                away["abbr"] = opp[home["abbr"]]
            elif opp.get(away["abbr"]) and opp.get(home["abbr"]) and opp[away["abbr"]] != home["abbr"]:
                # both look like real teams but aren't opponents: trust the side the matchup table can pin
                problems.append(f"{away['name']}/{home['name']} read as {away['abbr']}/{home['abbr']}, not a real matchup")
                continue
        for r in (away, home):
            if r["err"]:
                problems.append(f"{r['name']}: {r['err']}")
        if away["err"] or home["err"]:
            continue
        if away["line"] != -home["line"]:
            problems.append(f"{away['abbr']} {away['line']} / {home['abbr']} {home['line']} don't mirror")
            continue
        side = lambda r, is_home: {"num": r["num"], "abbr": r["abbr"], "home": is_home and not bx["neutral"], "line": r["line"]}
        a, h = side(away, False), side(home, True)
        fav, dog = (a, h) if a["line"] < h["line"] or (a["line"] == h["line"] and a["num"] < h["num"]) else (h, a)
        games.append({"id": len(games) + 1, "time_pt": home["time"] or away["time"], "neutral": bx["neutral"], "fav": fav, "dog": dog})
    abbrs = [s["abbr"] for g in games for s in (g["fav"], g["dog"])]
    dup = {a for a in abbrs if abbrs.count(a) > 1}
    if dup or None in abbrs:
        problems.append(f"team names didn't resolve cleanly (duplicates: {sorted(d for d in dup if d)})")
    return games, problems
