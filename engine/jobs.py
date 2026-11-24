"""Manager career progression: job offers from clubs, comparison, accept/decline, moving clubs inside the SAME career.

Board confidence is an INDICATOR ONLY. There is no dismissal mechanic anywhere in this module (by decision).
No history is kept: a single reputation number, offers pending right now, and the current AI manager of each club.
"""
import json
import random
from datetime import date, timedelta

from . import db, manager as M, negotiation as N, season as S
from .match import team_strength

OFFER_VALID_DAYS = 14
LEVELS = ("low", "moderate", "good", "excellent")
_FIRST = ["Marek", "Tomas", "Luca", "Dario", "Ilan", "Soren", "Viktor", "Emil", "Rafa", "Anton", "Dmitri", "Joaquin",
          "Matteo", "Stefan", "Nils", "Pavel", "Corin", "Bastien", "Elio", "Hugo", "Lars", "Mikel", "Teo", "Yannick"]
_LAST = ["Valdoren", "Kestrin", "Moravec", "Dellacroix", "Hartmann", "Ostrova", "Brenner", "Calderi", "Fontaine",
         "Larkovic", "Montrel", "Sandoval", "Vireaux", "Thorne", "Aldovar", "Ferrante", "Kovalis", "Rennick",
         "Souvrin", "Baldessari", "Quintero", "Haldane", "Zeller", "Marchetti"]  # fictional on purpose


def ensure_schema(con):
    M.ensure_schema(con)
    N.ensure_schema(con)
    con.executescript("""
CREATE TABLE IF NOT EXISTS club_manager(club_id INTEGER PRIMARY KEY, name TEXT NOT NULL, reputation INTEGER NOT NULL,
  appointed_season INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS job_offer(id INTEGER PRIMARY KEY AUTOINCREMENT, club_id INTEGER NOT NULL, created TEXT NOT NULL,
  expires TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_job_status ON job_offer(status);
""")
    con.commit()


def _info(con):
    return con.execute("SELECT * FROM career_info").fetchone()


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


# ------------------------------------------------------------------ club facts
def league_of(con, club_id, season=None):
    season = _info(con)["season"] if season is None else season
    r = con.execute("SELECT league_id FROM club_season WHERE club_id=? AND season=?", (club_id, season)).fetchone()
    return r[0] if r else None


def club_summary(con, club_id):
    info = _info(con)
    c = con.execute("SELECT id,name,name_ar,reputation,league_id FROM world.clubs WHERE id=?", (club_id,)).fetchone()
    lid = league_of(con, club_id, info["season"]) or c["league_id"]
    lg = con.execute("SELECT name,name_ar,tier,country FROM world.leagues WHERE id=?", (lid,)).fetchone()
    fin = N.get_finance(con, club_id)
    tbl = S.table(con, info["season"], lid)
    pos = next((i + 1 for i, r in enumerate(tbl) if r["club_id"] == club_id), None)
    played = next((r["p"] for r in tbl if r["club_id"] == club_id), 0)
    return dict(club_id=club_id, name=c["name_ar"] or c["name"], league_id=lid, league=lg["name_ar"] or lg["name"],
                tier=lg["tier"], country=lg["country"], reputation=c["reputation"],
                transfer_budget=fin["transfer_budget"], wage_budget=fin["wage_budget"],
                strength=round(team_strength(db.squad(con, club_id))["ovr"], 1), position=pos, played=played,
                league_size=len(tbl))


def board_objectives(con, club_id):
    """League-position target from the club's reputation rank inside its CURRENT league (no cups: not modelled here)."""
    info = _info(con)
    lid = league_of(con, club_id, info["season"])
    members = [r[0] for r in con.execute("SELECT club_id FROM club_season WHERE season=? AND league_id=?", (info["season"], lid))]
    reps = sorted(((con.execute("SELECT reputation FROM world.clubs WHERE id=?", (m,)).fetchone()[0], m) for m in members),
                  reverse=True)
    n = len(reps)
    rank = 1 + next(i for i, (_, m) in enumerate(reps) if m == club_id)
    tier = con.execute("SELECT tier FROM world.leagues WHERE id=?", (lid,)).fetchone()[0]
    if rank <= 2:
        key, target = ("win_league" if tier == 1 else "win_promotion"), 1 if rank == 1 else 2
    elif rank <= 5:
        key, target = ("european_places" if tier == 1 else "promotion_playoff"), 5
    elif rank <= n - 5:
        key, target = "top_half", n // 2
    else:
        key, target = "avoid_relegation" if tier == 1 else "stay_safe", n - 3
    return dict(key=key, target_position=target, league_size=n)


def board_confidence(con, club_id=None):
    """INDICATOR ONLY. 0..100 and one of low/moderate/good/excellent. Has no consequence anywhere."""
    info = _info(con)
    cid = info["club_id"] if club_id is None else club_id
    obj = board_objectives(con, cid)
    cs = club_summary(con, cid)
    if cs["played"] == 0:
        val = 60.0
    else:
        val = 60.0 + (obj["target_position"] - cs["position"]) * 3.0
    val = _clamp(val, 5, 95)
    level = LEVELS[0 if val < 30 else 1 if val < 55 else 2 if val < 78 else 3]
    return dict(value=round(val), level=level, objective=obj, position=cs["position"], played=cs["played"])


# ------------------------------------------------------------------ reputation
def season_reputation_update(con):
    """Call once when a season has been played (before S.end_season). Changes ONE number; keeps no history."""
    info = _info(con)
    cs = club_summary(con, info["club_id"])
    obj = board_objectives(con, info["club_id"])
    delta = _clamp((obj["target_position"] - cs["position"]) * 0.8, -4, 6)
    if cs["position"] == 1:
        delta += 2
    return M.add_reputation(con, round(delta))


# ------------------------------------------------------------------ AI managers (fictional, sparse, no history)
def _new_name(rng, used):
    for _ in range(200):
        n = f"{rng.choice(_FIRST)} {rng.choice(_LAST)}"
        if n not in used:
            return n
    return f"{rng.choice(_FIRST)} {rng.choice(_LAST)} {rng.randint(2, 99)}"


def get_club_manager(con, club_id):
    ensure_schema(con)
    r = con.execute("SELECT * FROM club_manager WHERE club_id=?", (club_id,)).fetchone()
    if r:
        return dict(r)
    info = _info(con)
    rng = random.Random(f"{info['seed']}:{club_id}:mgr")
    used = {x[0] for x in con.execute("SELECT name FROM club_manager")}
    rep = con.execute("SELECT reputation FROM world.clubs WHERE id=?", (club_id,)).fetchone()[0]
    name = _new_name(rng, used)
    with con:
        con.execute("INSERT INTO club_manager VALUES(?,?,?,?)",
                    (club_id, name, int(_clamp(rep * 0.7 + rng.randint(-6, 6), 1, 100)), info["season"]))
    return dict(con.execute("SELECT * FROM club_manager WHERE club_id=?", (club_id,)).fetchone())


def appoint_replacement(con, club_id):
    """The club the user left gets a new AI manager (a different name from the previous one)."""
    ensure_schema(con)
    info = _info(con)
    old = con.execute("SELECT name FROM club_manager WHERE club_id=?", (club_id,)).fetchone()
    rng = random.Random(f"{info['seed']}:{club_id}:{info['season']}:{info['cur_date']}:repl")
    used = {x[0] for x in con.execute("SELECT name FROM club_manager")}
    if old:
        used.add(old[0])
    rep = con.execute("SELECT reputation FROM world.clubs WHERE id=?", (club_id,)).fetchone()[0]
    with con:
        con.execute("INSERT INTO club_manager VALUES(?,?,?,?) ON CONFLICT(club_id) DO UPDATE SET name=excluded.name,"
                    "reputation=excluded.reputation,appointed_season=excluded.appointed_season",
                    (club_id, _new_name(rng, used), int(_clamp(rep * 0.7 + rng.randint(-6, 6), 1, 100)), info["season"]))
    return dict(con.execute("SELECT * FROM club_manager WHERE club_id=?", (club_id,)).fetchone())


# ------------------------------------------------------------------ offers
def eligible_clubs(con, reputation, exclude=()):
    """Clubs whose reputation is within reach of a manager with this reputation. Over a career (reputation 10..100)
    every one of the 198 clubs becomes reachable."""
    lo, hi = reputation - 45, reputation + 22
    ex = set(exclude)
    return [r[0] for r in con.execute("SELECT id FROM world.clubs WHERE reputation BETWEEN ? AND ? ORDER BY id", (lo, hi))
            if r[0] not in ex]


def _expire(con):
    cur = _info(con)["cur_date"]
    with con:
        con.execute("UPDATE job_offer SET status='expired' WHERE status='pending' AND expires<?", (cur,))


def pending_offers(con):
    ensure_schema(con)
    _expire(con)
    return [dict(r, payload=json.loads(r["payload"])) for r in
            con.execute("SELECT * FROM job_offer WHERE status='pending' ORDER BY id")]


def generate_offers(con, max_offers=3):
    """Deterministic per (career seed, date). Idempotent for a date: calling twice the same day adds nothing.
    How many / which clubs depends on reputation, results this season and board confidence (indicator)."""
    ensure_schema(con)
    info = _info(con)
    prof = M.ensure_profile(con)
    _expire(con)
    if prof["last_offer_check"] == info["cur_date"]:
        return []
    with con:
        con.execute("UPDATE manager_profile SET last_offer_check=?", (info["cur_date"],))
    rng = random.Random(f"{info['seed']}:{info['season']}:{info['cur_date']}:offers")
    conf = board_confidence(con)
    mu = 0.4 + (prof["reputation"] - 50) / 60.0 + (conf["value"] - 60) / 80.0
    n = int(_clamp(round(rng.gauss(mu, 0.8)), 0, max_offers))
    have = {o["club_id"] for o in pending_offers(con)}
    pool = eligible_clubs(con, prof["reputation"], exclude=have | {info["club_id"]})
    if not pool or n == 0:
        return []
    reps = {r[0]: r[1] for r in con.execute("SELECT id,reputation FROM world.clubs")}
    weights = [1.0 / (1 + abs(reps[c] - prof["reputation"]) / 10.0) for c in pool]
    chosen = []
    for _ in range(min(n, len(pool))):
        c = rng.choices(pool, weights)[0]
        i = pool.index(c)
        pool.pop(i)
        weights.pop(i)
        chosen.append(c)
    cur = date.fromisoformat(info["cur_date"])
    out = []
    for c in chosen:
        cs = club_summary(con, c)
        payload = dict(club=cs, objective=board_objectives(con, c),
                       weekly_wage=int(max(2000, cs["reputation"] * 450 * (0.8 + 0.4 * rng.random()))),
                       length_years=rng.randint(1, 4))
        with con:
            cur_id = con.execute("INSERT INTO job_offer(club_id,created,expires,payload) VALUES(?,?,?,?)",
                                 (c, info["cur_date"], (cur + timedelta(days=OFFER_VALID_DAYS)).isoformat(),
                                  json.dumps(payload))).lastrowid
        out.append(cur_id)
    return out


def get_offer(con, offer_id):
    r = con.execute("SELECT * FROM job_offer WHERE id=?", (offer_id,)).fetchone()
    if not r:
        raise ValueError("unknown offer")
    return dict(r, payload=json.loads(r["payload"]))


def compare(con, offer_id):
    """Side-by-side current club vs offered club (the offered numbers are re-read live, not from the stale payload)."""
    o = get_offer(con, offer_id)
    info = _info(con)
    cur, new = club_summary(con, info["club_id"]), club_summary(con, o["club_id"])
    keys = ("reputation", "transfer_budget", "wage_budget", "strength", "tier")
    return dict(current=cur, offered=new, deltas={k: new[k] - cur[k] for k in keys},
                objective_current=board_objectives(con, info["club_id"]),
                objective_offered=board_objectives(con, o["club_id"]), terms=dict(weekly_wage=o["payload"]["weekly_wage"],
                length_years=o["payload"]["length_years"]), expires=o["expires"], status=o["status"])


def decline_offer(con, offer_id):
    o = get_offer(con, offer_id)
    if o["status"] != "pending":
        raise ValueError("offer is not pending")
    with con:
        con.execute("UPDATE job_offer SET status='declined' WHERE id=?", (offer_id,))


def accept_offer(con, offer_id):
    """Move the user to the offered club in the SAME career. One transaction. Reputation is kept; the old club gets
    a replacement AI manager; the new club's AI manager is simply replaced by the user; open negotiations of the old
    club are cancelled; the lineup is cleared (the squad is different)."""
    ensure_schema(con)
    _expire(con)
    o = get_offer(con, offer_id)
    if o["status"] != "pending":
        raise ValueError("offer is not pending (expired, declined or already accepted)")
    info = _info(con)
    old, new = info["club_id"], o["club_id"]
    if new == old:
        raise ValueError("already managing this club")
    nm = con.execute("SELECT name_ar,name FROM world.clubs WHERE id=?", (new,)).fetchone()
    N.cancel_for_club(con, old)
    appoint_replacement(con, old)
    with con:
        con.execute("DELETE FROM club_manager WHERE club_id=?", (new,))
        con.execute("UPDATE career_info SET club_id=?, club_name=?", (new, nm["name_ar"] or nm["name"]))
        con.execute("UPDATE manager_profile SET current_club_id=?", (new,))
        con.execute("DELETE FROM lineup")
        con.execute("UPDATE job_offer SET status='accepted' WHERE id=?", (offer_id,))
        con.execute("UPDATE job_offer SET status='withdrawn' WHERE status='pending' AND id<>?", (offer_id,))
    return dict(old_club=old, new_club=new, reputation=M.get_profile(con)["reputation"])
