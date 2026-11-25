"""Domestic cups (both tiers of a country, single-leg knockout) and two European knockout competitions for qualified clubs only.
Fixtures live in the same `fixtures` table with comp != 'league'. Next rounds are drawn when the previous round is complete."""
import json
import random
from datetime import date, timedelta

from .fixtures import round_date

CUP_BASE = 1000      # league_id of a country's cup = 1000 + index (countries sorted)
EURO = {"CL": 2000, "EL": 2001}
EURO_NAME = {"CL": "دوري أبطال أوروبا", "EL": "الدوري الأوروبي"}
CUP_NAME_AR = {"England": "كأس إنجلترا", "Spain": "كأس إسبانيا", "Germany": "كأس ألمانيا", "Italy": "كأس إيطاليا", "France": "كأس فرنسا"}
CL_QUOTA = {"England": 4, "Spain": 3, "Germany": 3, "Italy": 3, "France": 3}
EL_QUOTA = dict(CL_QUOTA)
ROUND_NAME = {1: "النهائي", 2: "نصف النهائي", 4: "ربع النهائي", 8: "دور الـ16", 16: "دور الـ32", 32: "دور الـ64"}

SQL = """
CREATE TABLE IF NOT EXISTS comp_result(fixture_id INTEGER PRIMARY KEY, winner_id INTEGER NOT NULL, pens INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS comp_info(season INTEGER NOT NULL, comp TEXT NOT NULL, league_id INTEGER NOT NULL, name TEXT NOT NULL,
  rounds INTEGER NOT NULL, dates TEXT NOT NULL, PRIMARY KEY(season, league_id));
CREATE TABLE IF NOT EXISTS club_honours(season INTEGER NOT NULL, comp_name TEXT NOT NULL, result TEXT NOT NULL, won INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(season, comp_name));
"""


def ensure_schema(con):
    con.executescript(SQL)


def _countries(con):
    return sorted({r[0] for r in con.execute("SELECT DISTINCT country FROM world.leagues")})


def _round_label(n_remaining_matches):
    return ROUND_NAME.get(n_remaining_matches, f"الدور {n_remaining_matches * 2}")


def _dates(season, rounds, first_league_round, gap, offset_days):
    return [(date.fromisoformat(round_date(season, first_league_round + i * gap)) + timedelta(days=offset_days)).isoformat() for i in range(rounds)]


def _qualifiers(con, season):
    """European places: from the previous season's final tables (stored at rollover); the first season uses club reputation."""
    stored = con.execute("SELECT value FROM comp_kv WHERE key=?", (f"euro_{season}",)).fetchone() if _has_kv(con) else None
    if stored:
        d = json.loads(stored[0])
        return d["CL"], d["EL"]
    cl, el = [], []
    for ctry in _countries(con):
        t1 = [r[0] for r in con.execute(
            "SELECT c.id FROM world.clubs c JOIN world.leagues l ON l.id=c.league_id JOIN club_season cs ON cs.club_id=c.id AND cs.season=? "
            "WHERE l.country=? AND l.tier=1 AND cs.league_id=l.id ORDER BY c.reputation DESC", (season, ctry))]
        q1, q2 = CL_QUOTA[ctry], EL_QUOTA[ctry]
        cl += t1[:q1]
        el += t1[q1:q1 + q2]
    return cl, el


def _has_kv(con):
    con.execute("CREATE TABLE IF NOT EXISTS comp_kv(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    return True


def ensure_season(con):
    """Idempotently create this season's cup/European round-1 fixtures and metadata."""
    ensure_schema(con)
    _has_kv(con)
    season, seed = con.execute("SELECT season,seed FROM career_info").fetchone()
    if con.execute("SELECT 1 FROM comp_info WHERE season=?", (season,)).fetchone():
        return False
    rng = random.Random(f"{seed}:{season}:comps")
    with con:
        for idx, ctry in enumerate(_countries(con)):
            clubs = [r[0] for r in con.execute(
                "SELECT cs.club_id FROM club_season cs JOIN world.leagues l ON l.id=cs.league_id JOIN world.clubs c ON c.id=cs.club_id "
                "WHERE cs.season=? AND l.country=? ORDER BY c.reputation DESC, c.id", (season, ctry))]
            if len(clubs) < 4:
                continue
            _make_knockout(con, season, "cup", CUP_BASE + idx, CUP_NAME_AR.get(ctry, "كأس " + ctry), clubs, rng, 4, 5, 3, seeded_byes=True)
        cl, el = _qualifiers(con, season)
        for key, ids, first, gap, off in (("CL", cl, 8, 8, 4), ("EL", el, 9, 8, 5)):
            if len(ids) >= 4:
                _make_knockout(con, season, "euro", EURO[key], EURO_NAME[key], ids, rng, first, gap, off, seeded_byes=False)
    return True


def _make_knockout(con, season, comp, league_id, name, clubs, rng, first_round, gap, offset, seeded_byes):
    n = len(clubs)
    size = 1
    while size < n:
        size *= 2
    rounds = size.bit_length() - 1
    dates = _dates(season, rounds, first_round, gap, offset)
    con.execute("INSERT INTO comp_info VALUES(?,?,?,?,?,?)", (season, comp, league_id, name, rounds, json.dumps(dates)))
    byes = size - n
    bye_clubs = clubs[:byes] if seeded_byes else []
    rest = [c for c in clubs if c not in bye_clubs]
    rng.shuffle(rest)
    _insert_round(con, season, comp, league_id, 1, dates[0], rest, bye_clubs, rng)


def _insert_round(con, season, comp, league_id, rnd, d, clubs, byes, rng):
    """Pair `clubs` (those with byes are recorded as already through)."""
    rows = [(season, league_id, comp, rnd, d, clubs[i], clubs[i + 1]) for i in range(0, len(clubs) - 1, 2)]
    con.executemany("INSERT INTO fixtures(season,league_id,comp,round,date,home_id,away_id) VALUES(?,?,?,?,?,?,?)", rows)
    if byes:
        con.execute("INSERT OR REPLACE INTO comp_kv VALUES(?,?)", (f"byes_{season}_{league_id}", json.dumps(byes)))


def winner_of(con, f):
    """Winner club id of a played knockout fixture row (draws are decided by the stored shoot-out)."""
    r = con.execute("SELECT hg,ag FROM results WHERE fixture_id=?", (f["id"],)).fetchone()
    if r is None:
        return None
    if r["hg"] != r["ag"]:
        return f["home_id"] if r["hg"] > r["ag"] else f["away_id"]
    w = con.execute("SELECT winner_id FROM comp_result WHERE fixture_id=?", (f["id"],)).fetchone()
    return w[0] if w else f["home_id"]


def resolve_draw(con, f, hg, ag, rng):
    """Called when a knockout match ends level: extra time is folded into the score; a shoot-out decides it."""
    if f["comp"] == "league" or hg != ag:
        return None
    w = f["home_id"] if rng.random() < 0.5 else f["away_id"]
    con.execute("INSERT OR REPLACE INTO comp_result VALUES(?,?,1)", (f["id"], w))
    return w


def advance(con):
    """Draw the next round of every knockout whose current round is complete. Returns number of fixtures created."""
    ensure_schema(con)
    _has_kv(con)
    season, seed = con.execute("SELECT season,seed FROM career_info").fetchone()
    made = 0
    for ci in con.execute("SELECT * FROM comp_info WHERE season=?", (season,)).fetchall():
        lid = ci["league_id"]
        cur = con.execute("SELECT MAX(round) FROM fixtures WHERE season=? AND league_id=?", (season, lid)).fetchone()[0]
        if cur is None or cur >= ci["rounds"]:
            continue
        if con.execute("SELECT 1 FROM fixtures WHERE season=? AND league_id=? AND round=? AND played=0", (season, lid, cur)).fetchone():
            continue
        win = [winner_of(con, f) for f in con.execute("SELECT * FROM fixtures WHERE season=? AND league_id=? AND round=? ORDER BY id", (season, lid, cur))]
        if cur == 1:
            b = con.execute("SELECT value FROM comp_kv WHERE key=?", (f"byes_{season}_{lid}",)).fetchone()
            win = (json.loads(b[0]) if b else []) + win
        rng = random.Random(f"{seed}:{season}:{lid}:{cur}")
        rng.shuffle(win)
        dates = json.loads(ci["dates"])
        with con:
            _insert_round(con, season, ci["comp"], lid, cur + 1, dates[cur], win, [], rng)
        made += len(win) // 2
    return made


def view(con, league_id):
    """Rounds of a competition with results (for the UI)."""
    season = con.execute("SELECT season FROM career_info").fetchone()[0]
    ci = con.execute("SELECT * FROM comp_info WHERE season=? AND league_id=?", (season, league_id)).fetchone()
    if not ci:
        return None
    out = []
    for rnd in range(1, ci["rounds"] + 1):
        fx = con.execute("SELECT f.*,r.hg,r.ag FROM fixtures f LEFT JOIN results r ON r.fixture_id=f.id WHERE f.season=? AND f.league_id=? AND f.round=? ORDER BY f.id",
                         (season, league_id, rnd)).fetchall()
        remaining = 2 ** (ci["rounds"] - rnd)
        row = []
        for f in fx:
            w = winner_of(con, f) if f["played"] else None
            pens = con.execute("SELECT pens FROM comp_result WHERE fixture_id=?", (f["id"],)).fetchone()
            row.append(dict(home=f["home_id"], away=f["away_id"], hg=f["hg"], ag=f["ag"], winner=w, pens=bool(pens and pens[0]), date=f["date"]))
        out.append(dict(round=rnd, label=_round_label(remaining), fixtures=row, date=json.loads(ci["dates"])[rnd - 1]))
    return dict(name=ci["name"], comp=ci["comp"], rounds=out)


def user_status(con, club_id, season):
    """(comp_name, result_text, won) for every competition of this season the club took part in."""
    out = []
    for ci in con.execute("SELECT * FROM comp_info WHERE season=?", (season,)).fetchall():
        lid = ci["league_id"]
        fx = con.execute("SELECT * FROM fixtures WHERE season=? AND league_id=? AND (home_id=? OR away_id=?) ORDER BY round", (season, lid, club_id, club_id)).fetchall()
        b = con.execute("SELECT value FROM comp_kv WHERE key=?", (f"byes_{season}_{lid}",)).fetchone()
        had_bye = bool(b and club_id in json.loads(b[0]))
        if not fx and not had_bye:
            continue
        reached, won = 0, 0
        last = None
        for f in fx:
            if f["played"]:
                w = winner_of(con, f)
                reached = f["round"]
                if w == club_id and f["round"] == ci["rounds"]:
                    won = 1
                last = (f, w)
        remaining = 2 ** (ci["rounds"] - max(reached, 1)) if reached else 2 ** (ci["rounds"] - 1)
        if won:
            txt = "بطل"
        elif reached:
            txt = "خرج في " + _round_label(2 ** (ci["rounds"] - reached)) if last and last[1] != club_id else "وصل إلى " + _round_label(2 ** (ci["rounds"] - reached))
        else:
            txt = "لم يلعب"
        out.append((ci["name"], txt, won))
    return out


def record_honours_and_qualifiers(con):
    """Call BEFORE season rollover: stores the user's results in each competition and next season's European places."""
    ensure_schema(con)
    _has_kv(con)
    season, club = con.execute("SELECT season,club_id FROM career_info").fetchone()
    with con:
        for name, txt, won in user_status(con, club, season):
            con.execute("INSERT OR REPLACE INTO club_honours VALUES(?,?,?,?)", (season, name, txt, won))
    # European places for next season from this season's final tables (S.table ordering)
    from . import season as S
    cl, el = [], []
    for ctry in _countries(con):
        t1 = con.execute("SELECT id FROM world.leagues WHERE country=? AND tier=1", (ctry,)).fetchone()[0]
        order = [r["club_id"] for r in S.table(con, season, t1)]
        q1, q2 = CL_QUOTA[ctry], EL_QUOTA[ctry]
        cl += order[:q1]
        el += order[q1:q1 + q2]
    with con:
        con.execute("INSERT OR REPLACE INTO comp_kv VALUES(?,?)", (f"euro_{season + 1}", json.dumps({"CL": cl, "EL": el})))
