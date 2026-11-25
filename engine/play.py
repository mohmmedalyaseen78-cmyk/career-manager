"""Playable layer: user preferences (formation/XI/tactics), live match handling, offseason (development, contracts, youth)."""
import json
import random

from . import attrs as A
from . import db, jobs as J, manager as M, negotiation as N, season as S
from . import talents as T
from .match import FORMATIONS, MatchSession, auto_lineup, available
from .names_ar import pick_unique_name  # noqa: F401

DEFAULT_PREFS = dict(formation="4-3-3", mentality="balanced", pressing=50, tempo=50, xi=[])


def get_prefs(con):
    s = json.loads(con.execute("SELECT settings FROM career_info").fetchone()[0] or "{}")
    p = dict(DEFAULT_PREFS)
    p.update(s.get("prefs", {}))
    return p


def set_prefs(con, **kw):
    s = json.loads(con.execute("SELECT settings FROM career_info").fetchone()[0] or "{}")
    p = s.get("prefs", {})
    for k, v in kw.items():
        if k == "formation" and v not in FORMATIONS:
            raise ValueError("bad formation")
        if k == "mentality" and v not in ("defensive", "balanced", "attacking"):
            raise ValueError("bad mentality")
        if k in ("pressing", "tempo"):
            v = max(0, min(100, int(v)))
        if k in DEFAULT_PREFS:
            p[k] = v
    s["prefs"] = p
    with con:
        con.execute("UPDATE career_info SET settings=?", (json.dumps(s, ensure_ascii=False),))
    return get_prefs(con)


def get_setting(con, key, default=None):
    return json.loads(con.execute("SELECT settings FROM career_info").fetchone()[0] or "{}").get(key, default)


def put_setting(con, key, value):
    s = json.loads(con.execute("SELECT settings FROM career_info").fetchone()[0] or "{}")
    s[key] = value
    with con:
        con.execute("UPDATE career_info SET settings=?", (json.dumps(s, ensure_ascii=False),))


def user_side(squad, prefs):
    """(lineup, bench) honouring the manager's chosen XI when valid, else auto. Missing/unavailable picks are replaced."""
    f = prefs.get("formation", "4-3-3")
    auto, bench = auto_lineup(squad, f)
    xi = [i for i in prefs.get("xi", [])]
    by = {p["id"]: p for p in squad}
    chosen = [by[i] for i in xi if i in by and available(by[i])]
    if len(chosen) < 11:
        # fill the rest with best auto players not chosen
        for _, p in auto:
            if len(chosen) < 11 and p["id"] not in {c["id"] for c in chosen}:
                chosen.append(p)
    chosen = chosen[:11]
    slots = FORMATIONS[f]
    left, res = list(chosen), [None] * 11
    for i in sorted(range(11), key=lambda k: slots[k] != "GK"):
        sp = slots[i]
        pool = [p for p in left if (sp == "GK") == (p["pos"] == "GK")] or left
        best = max(pool, key=lambda p: A.ovr_at(p["attrs"], sp) - (0 if p["pos"] == sp or sp in p["pos2"].split(",") else 2))
        res[i] = (sp, best)
        left.remove(best)
    used = {p["id"] for _, p in res}
    bn = sorted([p for p in squad if available(p) and p["id"] not in used], key=lambda p: -p["ovr"])[:9]
    return res, bn


def tactics_of(prefs):
    return dict(mentality=prefs["mentality"], pressing=prefs["pressing"], tempo=prefs["tempo"])


def next_user_fixture(con):
    info = con.execute("SELECT club_id FROM career_info").fetchone()
    return con.execute("SELECT * FROM fixtures WHERE played=0 AND (home_id=? OR away_id=?) ORDER BY date,id LIMIT 1",
                       (info["club_id"], info["club_id"])).fetchone()


def start_live(con):
    """Create a MatchSession for the user's next fixture (the next date must be the fixture's date)."""
    info = con.execute("SELECT * FROM career_info").fetchone()
    fx = next_user_fixture(con)
    if fx is None:
        return None
    prefs = get_prefs(con)
    user = info["club_id"]
    hs, as_ = db.squad(con, fx["home_id"]), db.squad(con, fx["away_id"])
    if fx["home_id"] == user:
        hl, hb = user_side(hs, prefs)
        al, ab = auto_lineup(as_)
    else:
        hl, hb = auto_lineup(hs)
        al, ab = user_side(as_, prefs)
    seed = ((info["seed"] * 1000003 + int(fx["date"].replace("-", ""))) + fx["id"]) & 0x7FFFFFFF
    H = dict(club_id=fx["home_id"], lineup=hl, bench=hb, tactics=tactics_of(prefs) if fx["home_id"] == user else None)
    A_ = dict(club_id=fx["away_id"], lineup=al, bench=ab, tactics=tactics_of(prefs) if fx["away_id"] == user else None)
    side = 0 if fx["home_id"] == user else 1
    return MatchSession(H, A_, seed, auto=(side != 0, side != 1)), dict(fixture=dict(fx), side=side)


def finish_day(con, fixture_id, res):
    """Commit the user's (live-played) result and simulate the rest of that date."""
    return S.advance_matchday(con, user_result=(fixture_id, res))


def squad_view(con, club_id, season):
    out = []
    for p in db.squad(con, club_id):
        at = list(p["attrs"]) if not isinstance(p["attrs"], (bytes, bytearray)) else list(A.unpack(p["attrs"]))
        out.append(dict(p, attrs=at))
    return out


# ---------------------------------------------------------------- offseason
def offseason(con, on_rows):
    """Develop every player, renew AI contracts, release the user's expired contracts, refill thin squads with new talents."""
    info = con.execute("SELECT season,seed,club_id FROM career_info").fetchone()
    new_season, user = info["season"], info["club_id"]  # called AFTER end_season (season already incremented)
    rng = random.Random(f"{info['seed']}:{new_season}:offseason")
    stats = {r[0]: r for r in on_rows}
    matches = 38.0
    rows = con.execute("SELECT id,pos,birth_date,ovr,potential,growth,attrs,club_id,contract_end,wage,injury_days,morale "
                       "FROM v_player WHERE club_id IS NOT NULL").fetchall()
    upd = []
    for r in rows:
        age = new_season - int(r["birth_date"][:4]) - 1  # age during the season that just ended
        st = stats.get(r["id"])
        share = min(1.0, (st[3] / 90.0) / matches) if st else 0.0
        avg = (st[6] / st[7]) if st and st[7] else 0.0
        cq = 0.6
        if r["club_id"] == user:
            tr = get_training(con)
            cq += {"low": -0.08, "normal": 0.0, "high": 0.10}[tr["intensity"]] + (0.10 if tr["focus"] == "youth" and age <= 21 else 0)
        ovr = T.season_development(r["ovr"], r["potential"], age, r["growth"] or 1, share, avg, min(0.95, cq), r["morale"], r["injury_days"], 0.8, rng)
        pot = max(ovr, T.update_potential(r["ovr"], r["potential"], age, share, rng))
        d = ovr - r["ovr"]
        at = r["attrs"]
        if d and at:
            a = list(A.unpack(at))
            at = A.pack([max(1, min(99, x + d)) for x in a])
        ce = r["contract_end"] or new_season
        wage, club = r["wage"], r["club_id"]
        if ce < new_season:  # contract expired
            if club == user:
                club = 0  # leaves as a free agent
            else:
                ce = new_season + rng.randint(1, 4)
        val = T.market_value(ovr, pot, age + 1)
        upd.append((r["id"], club, ovr, pot, at, wage, val, ce, 70, 100, 70, 0, 0))
    with con:
        con.executemany("INSERT INTO player_state(player_id,club_id,ovr,potential,attrs,wage,value,contract_end,form,fitness,morale,injury_days,status) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(player_id) DO UPDATE SET club_id=excluded.club_id,ovr=excluded.ovr,"
                        "potential=excluded.potential,attrs=excluded.attrs,wage=excluded.wage,value=excluded.value,contract_end=excluded.contract_end,"
                        "form=70,fitness=100,morale=excluded.morale,injury_days=0,status=0", upd)
    # refill: every club to at least 22 players (new talents), unique names
    used = {r[0] for r in con.execute("SELECT name FROM v_player")}
    nid = max(10_000_000, (con.execute("SELECT MAX(id) FROM gen_players").fetchone()[0] or 0) + 1)
    country = {r[0]: r[1] for r in con.execute("SELECT c.id,l.country FROM world.clubs c JOIN world.leagues l ON l.id=c.league_id")}
    cnt = {r[0]: r[1] for r in con.execute("SELECT club_id,COUNT(*) FROM v_player WHERE club_id IS NOT NULL GROUP BY club_id")}
    new = 0
    with con:
        for cid, ctry in country.items():
            for _ in range(max(0, 23 - cnt.get(cid, 0))):
                y = T.generate_youth(rng, used, new_season, cid, ctry, next_id=nid)
                nid += 1
                cols = list(y)
                con.execute(f"INSERT INTO gen_players({','.join(cols)}) VALUES({','.join('?' * len(cols))})", [y[c] for c in cols])
                new += 1
    loans = return_loans(con)
    sc = SCOUT_COST[get_scouting(con)]
    if sc:
        f = N.get_finance(con, user)
        N._set_finance(con, user, max(0, f["transfer_budget"] - sc))
    return dict(developed=len(upd), new_talents=new, loans_returned=loans)


def end_of_season(con):
    """Run end_season then the offseason. Returns summary."""
    from . import comps
    comps.record_honours_and_qualifiers(con)
    seen = []
    ns = S.end_season(con, on_season_stats=lambda rows: seen.extend([tuple(r) for r in rows]))
    rep = offseason(con, seen)
    comps.ensure_season(con)
    J.season_reputation_update(con)
    return dict(new_season=ns, **rep)


# ---------------------------------------------------------------- condition (user's club only)
def set_state(con, pid, **cols):
    r = con.execute("SELECT 1 FROM player_state WHERE player_id=?", (pid,)).fetchone()
    if not r:
        p = con.execute("SELECT club_id,ovr,potential,attrs,wage,value,contract_end,form,fitness,morale,injury_days,status "
                        "FROM v_player WHERE id=?", (pid,)).fetchone()
        con.execute("INSERT INTO player_state(player_id,club_id,ovr,potential,attrs,wage,value,contract_end,form,fitness,morale,"
                    "injury_days,status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (pid, *tuple(p)))
    sets = ",".join(f"{k}=?" for k in cols)
    con.execute(f"UPDATE player_state SET {sets} WHERE player_id=?", (*cols.values(), pid))


def post_day(con, summary):
    """After a matchday: fatigue/recovery, injuries, suspensions, form and morale for the USER's club; pay installments."""
    info = con.execute("SELECT club_id,season,seed,cur_date FROM career_info").fetchone()
    user = info["club_id"]
    rng = random.Random(f"{info['seed']}:{info['cur_date']}:cond")
    played = {}
    ev_inj, ev_red = {}, set()
    won = lost = False
    u = summary.get("user") if summary else None
    if u:
        fid = u["fixture_id"]
        for r in con.execute("SELECT player_id,club_id,minutes,rating,rc FROM match_player_stats WHERE fixture_id=?", (fid,)):
            if r["club_id"] == user:
                played[r["player_id"]] = r
                if r["rc"]:
                    ev_red.add(r["player_id"])
        for r in con.execute("SELECT player_id,club_id FROM match_events WHERE fixture_id=? AND type='injury'", (fid,)):
            if r["club_id"] == user:
                ev_inj[r["player_id"]] = rng.choice([7, 10, 14, 14, 21, 28, 35, 49, 63])
        hg, ag = u["score"]
        mine, theirs = (hg, ag) if u["home"] == user else (ag, hg)
        won, lost = mine > theirs, mine < theirs
    sq = db.squad(con, user)
    with con:
        for p in sq:
            pid = p["id"]
            inj = max(0, p["injury_days"] - 7)
            fit, form, mor, stat = p["fitness"], p["form"], p["morale"], p["status"]
            if pid in played:
                pl = played[pid]
                fit = max(45, fit - int(pl["minutes"] / 90 * 14))
                if pl["rating"]:
                    form = int(max(25, min(95, 0.6 * form + 0.4 * (50 + (pl["rating"] - 6.0) * 25))))
            else:
                fit = min(100, fit + 10)
            if won:
                mor = min(95, mor + 3 if pid in played else mor + 1)
            elif lost:
                mor = max(25, mor - 3 if pid in played else mor - 1)
            tr = get_training(con)
            if pid not in played:
                fit = min(100, fit + {"fitness": 6, "balanced": 2}.get(tr["focus"], 2) - {"low": -3, "normal": 0, "high": 4}[tr["intensity"]])
            if inj == 0 and rng.random() < {"low": 0.003, "normal": 0.007, "high": 0.016}[tr["intensity"]]:
                inj = rng.choice([4, 7, 10, 14, 21])
            if pid in ev_inj:
                inj = ev_inj[pid]
            if stat == 1 and pid not in ev_red:
                stat = 0
            if pid in ev_red:
                stat = 1
            fit = min(100, fit + 5) if pid not in played else fit
            if (inj, fit, form, mor, stat) != (p["injury_days"], p["fitness"], p["form"], p["morale"], p["status"]):
                set_state(con, pid, injury_days=inj, fitness=fit, form=form, morale=mor, status=stat)
    N.settle_due_payments(con)


# ---------------------------------------------------------------- transfer window, incoming offers, training, scouting
SCOUT_COST = [0, 1_000_000, 2_500_000, 5_000_000]   # per season, taken from the transfer budget at rollover
TRAIN_FOCUS = ("balanced", "attack", "defense", "fitness", "youth")
TRAIN_INT = ("low", "normal", "high")


def window(cur_date):
    """(open, days_left): summer 1 Jun - 31 Aug, winter 1 - 31 Jan."""
    from datetime import date
    d = date.fromisoformat(cur_date)
    for (m1, d1, m2, d2) in ((6, 1, 8, 31), (1, 1, 1, 31)):
        a, b = date(d.year, m1, d1), date(d.year, m2, d2)
        if a <= d <= b:
            return True, (b - d).days
    return False, 0


def get_training(con):
    t = get_setting(con, "training", {}) or {}
    return dict(focus=t.get("focus", "balanced"), intensity=t.get("intensity", "normal"))


def set_training(con, focus=None, intensity=None):
    t = get_training(con)
    if focus:
        if focus not in TRAIN_FOCUS:
            raise ValueError("bad focus")
        t["focus"] = focus
    if intensity:
        if intensity not in TRAIN_INT:
            raise ValueError("bad intensity")
        t["intensity"] = intensity
    put_setting(con, "training", t)
    return t


def get_scouting(con):
    return int(get_setting(con, "scouting", 0) or 0)


def set_scouting(con, level):
    level = int(level)
    if not 0 <= level <= 3:
        raise ValueError("scouting level 0..3")
    put_setting(con, "scouting", level)
    return level


def generate_incoming(con):
    """After a matchday: with some probability an AI club bids for one of the user's players (only while the window is open)."""
    info = con.execute("SELECT club_id,cur_date,seed,season FROM career_info").fetchone()
    open_, left = window(info["cur_date"])
    if not open_:
        return None
    N.ensure_schema(con)
    active = [r for r in con.execute("SELECT state FROM negotiation WHERE status='active'")]
    sells = [s for s in (N.from_json(r[0]) for r in active) if s["kind"] == "sell"]
    if len(sells) >= 3:
        return None
    rng = random.Random(f"{info['seed']}:{info['cur_date']}:incoming")
    if rng.random() > 0.35:
        return None
    user = info["club_id"]
    sq = sorted(db.squad(con, user), key=lambda p: -p["ovr"])
    already = {s["ctx"]["player"]["id"] for s in sells}
    pool = [p for p in sq[:20] if p["id"] not in already and p["injury_days"] == 0]
    if not pool:
        return None
    p = rng.choice(pool)
    cands = [r for r in con.execute("SELECT id,reputation FROM world.clubs WHERE id<>?", (user,))]
    rng.shuffle(cands)
    diff = get_setting(con, "difficulty", "realistic")
    for c in cands[:25]:
        fin = N.get_finance(con, c["id"])
        if fin["transfer_budget"] < p["value"] * 0.8:
            continue
        ctx = N.build_context(con, "sell", p["id"], c["id"], difficulty=diff, window_open=open_, window_days_left=left,
                              interest=rng.random())
        st = N.new_negotiation(ctx)
        if st["current_offer"] > fin["transfer_budget"]:
            continue
        st["created"] = info["cur_date"]
        N.save(con, st)
        return st["id"]
    return None


def expire_incoming(con, days=14):
    from datetime import date
    info = con.execute("SELECT cur_date FROM career_info").fetchone()
    cur = date.fromisoformat(info["cur_date"])
    N.ensure_schema(con)
    for r in con.execute("SELECT id,state FROM negotiation WHERE status='active'").fetchall():
        st = N.from_json(r["state"])
        if st["kind"] == "sell" and st.get("created") and (cur - date.fromisoformat(st["created"])).days > days:
            st["status"] = "failed"
            st["fail_reason"] = "walked_away"
            N.save(con, st)
        if not window(info["cur_date"])[0] and st["kind"] in ("buy", "loan", "sell") and st["status"] == "active":
            st["status"] = "failed"
            st["fail_reason"] = "window_closed"
            N.save(con, st)


def return_loans(con):
    """At rollover loanees go back to their parent club."""
    N.ensure_schema(con)
    n = 0
    with con:
        for r in con.execute("SELECT player_id,terms FROM deal_terms").fetchall():
            t = json.loads(r["terms"])
            if t.get("loan_from"):
                set_state(con, r["player_id"], club_id=t["loan_from"])
                t["loan_from"] = None
                con.execute("UPDATE deal_terms SET terms=? WHERE player_id=?", (json.dumps(t), r["player_id"]))
                n += 1
    return n
