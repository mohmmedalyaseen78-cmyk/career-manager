"""Calendar progression: matchday simulation (incremental) and season rollover with promotion/relegation."""
import json
import random

from . import attrs as A
from . import db
from .fixtures import round_robin, round_date, season_start
from .match import (ATT_W, auto_lineup, simulate_detailed, simulate_fast, team_strength, FORMATIONS)

PROMO_N = 3  # internal simplified format: 3 up / 3 down in every country (documented deviation)


def _info(con):
    return con.execute("SELECT * FROM career_info").fetchone()


def next_date(con):
    r = con.execute("SELECT MIN(date) FROM fixtures WHERE played=0").fetchone()
    return r[0]


def _upsert_stats(con, season, pid, club, minutes, goals=0, assists=0, yc=0, rc=0, rating=None):
    con.execute(
        "INSERT INTO player_season_stats(season,player_id,club_id,apps,minutes,goals,assists,yc,rc,rating_sum,rated)"
        " VALUES(?,?,?,1,?,?,?,?,?,?,?) ON CONFLICT(season,player_id) DO UPDATE SET apps=apps+1,"
        "minutes=minutes+excluded.minutes,goals=goals+excluded.goals,assists=assists+excluded.assists,"
        "yc=yc+excluded.yc,rc=rc+excluded.rc,rating_sum=rating_sum+excluded.rating_sum,rated=rated+excluded.rated",
        (season, pid, club, minutes, goals, assists, yc, rc, rating or 0.0, 1 if rating else 0))


def _update_table(con, season, league, hid, aid, hg, ag):
    def upd(c, gf, ga):
        w, d, l = (1, 0, 0) if gf > ga else (0, 1, 0) if gf == ga else (0, 0, 1)
        con.execute("UPDATE standings SET p=p+1,w=w+?,d=d+?,l=l+?,gf=gf+?,ga=ga+?,pts=pts+? "
                    "WHERE season=? AND league_id=? AND club_id=?", (w, d, l, gf, ga, 3 * w + d, season, league, c))
    upd(hid, hg, ag)
    upd(aid, ag, hg)


def _fast_events(rng, lineup, goals):
    """Assign scorers/assisters to a fast-simulated team's XI. Returns [(minute, scorer, assister|None)]."""
    out = []
    outfield = [(s, p) for s, p in lineup if s != "GK"]
    for _ in range(goals):
        sc = rng.choices(outfield, [ATT_W[s] ** 1.5 * p["attrs"][A.IDX["finishing"]] + 1 for s, p in outfield])[0]
        cands = [x for x in outfield if x[1]["id"] != sc[1]["id"]]
        asst = rng.choices(cands, [ATT_W[s] + .2 for s, _ in cands])[0][1]["id"] if rng.random() < .7 else None
        out.append((rng.randint(1, 90), sc[1]["id"], asst))
    return out


def advance_matchday(con, formation="4-3-3", tactics=None, user_detailed=True, user_result=None):
    """Simulate every unplayed fixture on the next date. Only the user's match is detailed.
    All writes happen in ONE transaction (atomic). Returns summary dict."""
    info = _info(con)
    date = next_date(con)
    if date is None:
        return None
    season, user = info["season"], info["club_id"]
    fx = con.execute("SELECT * FROM fixtures WHERE date=? AND played=0", (date,)).fetchall()
    cache = {}

    def get_squad(c):
        if c not in cache:
            cache[c] = db.squad(con, c)
        return cache[c]

    summary = dict(date=date, played=0, user=None)
    base_seed = info["seed"] * 1000003 + int(date.replace("-", ""))
    with con:
        for f in fx:
            seed = (base_seed + f["id"]) & 0x7FFFFFFF
            rng = random.Random(seed)
            hid, aid = f["home_id"], f["away_id"]
            if user_detailed and user in (hid, aid):
                if user_result is not None and user_result[0] == f["id"]:
                    res = user_result[1]
                else:
                    from . import play
                    prefs = play.get_prefs(con)
                    hs, as_ = get_squad(hid), get_squad(aid)
                    if hid == user:
                        hl, hb = play.user_side(hs, prefs)
                        al, ab = auto_lineup(as_, "4-3-3")
                    else:
                        hl, hb = auto_lineup(hs, "4-3-3")
                        al, ab = play.user_side(as_, prefs)
                    H = dict(club_id=hid, lineup=hl, bench=hb, tactics=play.tactics_of(prefs) if hid == user else None)
                    Aw = dict(club_id=aid, lineup=al, bench=ab, tactics=play.tactics_of(prefs) if aid == user else None)
                    res = simulate_detailed(H, Aw, seed)
                hg, ag = res["score"]
                con.execute("INSERT INTO results VALUES(?,?,?,?,1)", (f["id"], hg, ag, seed))
                con.executemany("INSERT INTO match_events VALUES(?,?,?,?,?,?)",
                                [(f["id"], e["minute"], e["type"], e["club_id"], e["player_id"], e["player2_id"])
                                 for e in res["events"]])
                con.executemany("INSERT INTO match_player_stats VALUES(?,?,?,?,?,?,?,?,?,?)",
                                [(f["id"], p["player_id"], p["club_id"], p["minutes"], p["rating"], p["goals"],
                                  p["assists"], p["yc"], p["rc"], p["saves"]) for p in res["players"]])
                con.executemany("INSERT INTO match_team_stats VALUES(?,?,?)",
                                [(f["id"], t["club_id"], json.dumps(t)) for t in res["team_stats"]])
                for p in res["players"]:
                    if p["minutes"] > 0 and f["comp"] == "league":
                        _upsert_stats(con, season, p["player_id"], p["club_id"], p["minutes"], p["goals"],
                                      p["assists"], p["yc"], p["rc"], p["rating"])
                summary["user"] = dict(fixture_id=f["id"], home=hid, away=aid, score=(hg, ag), motm=res["motm"])
            else:
                hl, _ = auto_lineup(get_squad(hid))
                al, _ = auto_lineup(get_squad(aid))
                st = lambda lu: team_strength_from_lineup(lu)
                hg, ag = simulate_fast(st(hl), st(al), rng)
                con.execute("INSERT INTO results VALUES(?,?,?,?,0)", (f["id"], hg, ag, seed))
                for lu, cid, goals in ((hl, hid, hg), (al, aid, ag)):
                    scorers = {}
                    for minute, sc, asst in _fast_events(rng, lu, goals):
                        con.execute("INSERT INTO match_events VALUES(?,?,?,?,?,?)",
                                    (f["id"], minute, "goal", cid, sc, asst))
                        scorers.setdefault(sc, [0, 0])[0] += 1
                        if asst:
                            scorers.setdefault(asst, [0, 0])[1] += 1
                    for s, p in lu:
                        g, a = scorers.get(p["id"], [0, 0])
                        if f["comp"] == "league":
                            _upsert_stats(con, season, p["id"], cid, 90, g, a)
            if f["comp"] != "league":
                from . import comps
                comps.resolve_draw(con, f, hg, ag, rng)
            con.execute("UPDATE fixtures SET played=1 WHERE id=?", (f["id"],))
            if f["comp"] == "league":
                _update_table(con, season, f["league_id"], hid, aid, hg, ag)
            summary["played"] += 1
        con.execute("UPDATE career_info SET cur_date=?", (date,))
    return summary


def team_strength_from_lineup(lineup):
    from .match import _eff, ratings, DEFAULT_TACTICS
    on = [dict(slot=s, eff=_eff(p, s)) for s, p in lineup]
    att, mid, dfn, gk = ratings(on, DEFAULT_TACTICS)
    return dict(att=att, mid=mid, dfn=dfn, gk=gk)


def table(con, season, league_id):
    return con.execute("SELECT club_id,p,w,d,l,gf,ga,gf-ga AS gd,pts FROM standings WHERE season=? AND league_id=? "
                       "ORDER BY pts DESC, gf-ga DESC, gf DESC, club_id", (season, league_id)).fetchall()


def _best(con, season, club, order, cond=""):
    r = con.execute(f"SELECT s.player_id pid, {order[0]} v FROM player_season_stats s WHERE s.season=? AND s.club_id=? {cond} "
                    f"ORDER BY {order[1]} LIMIT 1", (season, club)).fetchone()
    if not r or not r["v"]:
        return None, 0
    n = con.execute("SELECT name_ar FROM v_player WHERE id=?", (r["pid"],)).fetchone()
    return (n[0] if n else None), r["v"]


def _club_summary_row(con, info, leagues, by_country):
    """Achievements of the USER's club for the season that just ended (kept as the club archive)."""
    season, club = info["season"], info["club_id"]
    row = con.execute("SELECT league_id FROM club_season WHERE season=? AND club_id=?", (season, club)).fetchone()
    if not row:
        return None
    lid = row[0]
    tbl = table(con, season, lid)
    pos = next(i + 1 for i, r in enumerate(tbl) if r["club_id"] == club)
    me = tbl[pos - 1]
    lg = con.execute("SELECT name_ar,name,country FROM world.leagues WHERE id=?", (lid,)).fetchone()
    cn = con.execute("SELECT name_ar,name FROM world.clubs WHERE id=?", (club,)).fetchone()
    ts, tsg = _best(con, season, club, ("s.goals", "s.goals DESC, s.apps"))
    ta, tag = _best(con, season, club, ("s.assists", "s.assists DESC, s.apps"))
    br, brv = _best(con, season, club, ("ROUND(s.rating_sum / s.rated, 2)", "s.rating_sum / s.rated DESC"), "AND s.rated >= 10")
    ma, mav = _best(con, season, club, ("s.apps", "s.apps DESC, s.minutes DESC"))
    return dict(season=season, club_id=club, club_name=cn[0] or cn[1], league_id=lid, league_name=lg[0] or lg[1],
                position=pos, league_size=len(tbl), p=me["p"], w=me["w"], d=me["d"], l=me["l"], gf=me["gf"], ga=me["ga"],
                pts=me["pts"], champion=int(pos == 1), top_scorer=ts, top_scorer_goals=tsg, top_assister=ta,
                top_assists=tag, best_rated=br, best_rating=brv, most_apps=ma, most_apps_n=mav,
                manager_name=info["manager_name"], country=lg[2])


def club_archive(con):
    """All finished seasons of the user's club (newest first) - the 'achievements' archive."""
    return [dict(r) for r in con.execute("SELECT * FROM club_history ORDER BY season DESC")]


def end_season(con, on_season_stats=None):
    """Champion record, promotion/relegation between tier 1 and 2 of each country, next season fixtures.
    on_season_stats(rows) is called with the finished season's per-player stats (for development) BEFORE they are
    purged: the game keeps NO player/manager history (decision 2026-11-22), only the current season."""
    info = _info(con)
    season = info["season"]
    if con.execute("SELECT COUNT(*) FROM fixtures WHERE season=? AND played=0", (season,)).fetchone()[0]:
        raise RuntimeError("season not finished")
    leagues = con.execute("SELECT id,country,tier FROM world.leagues ORDER BY id").fetchall()
    by_country = {}
    for l in leagues:
        by_country.setdefault(l["country"], {})[l["tier"]] = l["id"]
    new_membership = {}
    summary = _club_summary_row(con, info, leagues, by_country)
    with con:
        for country, tiers in by_country.items():
            t1, t2 = table(con, season, tiers[1]), table(con, season, tiers[2])
            down = [r["club_id"] for r in t1[-PROMO_N:]]
            up = [r["club_id"] for r in t2[:PROMO_N]]
            for r in t1:
                new_membership[r["club_id"]] = tiers[2] if r["club_id"] in down else tiers[1]
            for r in t2:
                new_membership[r["club_id"]] = tiers[1] if r["club_id"] in up else tiers[2]
            con.execute("INSERT INTO season_history VALUES(?,?,?,?,?)",
                        (season, tiers[1], t1[0]["club_id"], ",".join(map(str, up)), ",".join(map(str, down))))
            con.execute("INSERT INTO season_history VALUES(?,?,?,?,?)",
                        (season, tiers[2], t2[0]["club_id"], ",".join(map(str, up)), ""))
        if summary:
            promoted = int(summary["league_id"] == by_country[summary["country"]][2] and summary["position"] <= PROMO_N)
            relegated = int(summary["league_id"] == by_country[summary["country"]][1] and
                            summary["position"] > summary["league_size"] - PROMO_N)
            summary.pop("country")
            summary.update(promoted=promoted, relegated=relegated)
            cols = ",".join(summary)
            con.execute(f"INSERT OR REPLACE INTO club_history({cols}) VALUES({','.join('?' * len(summary))})",
                        list(summary.values()))
        ns = season + 1
        con.executemany("INSERT INTO club_season VALUES(?,?,?)", [(c, ns, l) for c, l in new_membership.items()])
        by_league = {}
        for c, l in new_membership.items():
            by_league.setdefault(l, []).append(c)
        rows, st = [], []
        for lid, ids in by_league.items():
            for r, rnd in enumerate(round_robin(sorted(ids))):
                d = round_date(ns, r)
                rows += [(ns, lid, "league", r + 1, d, h, a) for h, a in rnd]
            st += [(ns, lid, c) for c in ids]
        con.executemany("INSERT INTO fixtures(season,league_id,comp,round,date,home_id,away_id) VALUES(?,?,?,?,?,?,?)",
                        rows)
        con.executemany("INSERT INTO standings(season,league_id,club_id) VALUES(?,?,?)", st)
        con.execute("UPDATE career_info SET season=?, cur_date=?", (ns, season_start(ns).isoformat()))
        if on_season_stats:
            on_season_stats(con.execute("SELECT player_id,club_id,apps,minutes,goals,assists,rating_sum,rated "
                                        "FROM player_season_stats WHERE season=?", (season,)).fetchall())
        # no player history: drop previous seasons' per-player data (keeps career files small)
        con.execute("DELETE FROM player_season_stats WHERE season<?", (ns,))
        con.execute("DELETE FROM match_player_stats WHERE fixture_id IN (SELECT id FROM fixtures WHERE season<?)", (ns,))
        con.execute("DELETE FROM match_events WHERE fixture_id IN (SELECT id FROM fixtures WHERE season<?)", (ns,))
        con.execute("DELETE FROM match_team_stats WHERE fixture_id IN (SELECT id FROM fixtures WHERE season<?)", (ns,))
    return ns
