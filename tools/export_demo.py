"""Export REAL engine output (synthetic test world) to ui/data/demo.js for the UI mockups.
Everything shown comes from the engine functions (squad, table, fixtures, negotiation market estimate, job board...).
The world itself is fictional test data and is labelled so in the UI."""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from engine import attrs as A, db, jobs as J, manager as M, negotiation as N, season as S
from engine.career import CareerManager
from engine.worldgen import build_world

AR_DAYS = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
AR_MON = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]
POS_AR = {"GK": "حارس", "CB": "قلب دفاع", "LB": "ظهير أيسر", "RB": "ظهير أيمن", "CDM": "ارتكاز", "CM": "وسط", "CAM": "صانع ألعاب",
          "LM": "جناح أيسر", "RM": "جناح أيمن", "LW": "جناح أيسر", "RW": "جناح أيمن", "ST": "مهاجم"}
GROUP = {"GK": "GK", "CB": "DF", "LB": "DF", "RB": "DF", "CDM": "MF", "CM": "MF", "CAM": "MF", "LM": "MF", "RM": "MF",
         "LW": "FW", "RW": "FW", "ST": "FW"}


def ar_date(iso):
    import datetime
    d = datetime.date.fromisoformat(iso)
    return f"{AR_DAYS[d.weekday()]} {d.day} {AR_MON[d.month - 1]} {d.year}"


def main(out_js, club_id=1, matchdays=6, seed=21):
    tmp = tempfile.mkdtemp(prefix="cm_demo_")
    world = os.path.join(tmp, "world.db")
    build_world(world, seed=7)
    cm = CareerManager(os.path.join(tmp, "saves"), world)
    con = cm.open(cm.create(club_id, "كريم الحربي", seed=seed))
    J.ensure_schema(con)
    M.ensure_profile(con)
    for _ in range(matchdays):
        S.advance_matchday(con)
    info = con.execute("SELECT * FROM career_info").fetchone()
    season, cur = info["season"], info["cur_date"]
    cn = lambda cid: (con.execute("SELECT name_ar FROM world.clubs WHERE id=?", (cid,)).fetchone()[0])
    lid = J.league_of(con, club_id)
    lg = con.execute("SELECT name_ar,country FROM world.leagues WHERE id=?", (lid,)).fetchone()
    tbl = S.table(con, season, lid)
    pos = next(i + 1 for i, r in enumerate(tbl) if r["club_id"] == club_id)

    # ----- squad
    sq = sorted(db.squad(con, club_id), key=lambda p: -p["ovr"])
    first = {p["id"] for p in sorted(sq, key=lambda p: -p["ovr"])[:11]}
    squad = []
    for i, p in enumerate(sq):
        at = list(p["attrs"])
        face = A.gk_stats(at) if p["pos"] == "GK" else A.main_stats(at)
        left = max(0, (p["contract_end"] or season) - season)
        squad.append(dict(id=p["id"], name=p["name_ar"], pos=p["pos"], pos_ar=POS_AR[p["pos"]], grp=GROUP[p["pos"]],
                          pos2=[POS_AR[x] for x in p["pos2"].split(",") if x], age=season - int(p["birth_date"][:4]),
                          ovr=p["ovr"], pot=p["potential"], form=p["form"], fitness=p["fitness"], morale=p["morale"],
                          injury_days=p["injury_days"], role="أساسي" if p["id"] in first else "مهم" if i < 18 else "تدوير",
                          wage=p["wage"], value=p["value"], contract_left=left, face=face, quality="تجريبي"))
    # real player details that the engine knows but the list does not show
    for s_ in squad:
        r = con.execute("SELECT nationality,foot,height,weight,shirt FROM v_player v JOIN world.players w ON w.id=v.id WHERE v.id=?",
                        (s_["id"],)).fetchone() if False else None
    base = {r["id"]: r for r in con.execute("SELECT id,nationality,foot,height,weight,shirt,growth FROM world.players WHERE club_id=?", (club_id,))}
    for s_ in squad:
        b = base.get(s_["id"])
        s_.update(nat=b["nationality"] if b else "—", foot={"L": "اليسرى", "R": "اليمنى"}.get(b["foot"] if b else "R", "اليمنى"),
                  height=b["height"] if b else None, weight=b["weight"] if b else None, shirt=b["shirt"] if b else None,
                  growth=["بطيء", "طبيعي", "سريع", "استثنائي"][b["growth"] if b else 1])

    # ----- next match / last result
    nx = con.execute("SELECT * FROM fixtures WHERE played=0 AND (home_id=? OR away_id=?) ORDER BY date LIMIT 1", (club_id, club_id)).fetchone()
    last = con.execute("SELECT f.*,r.hg,r.ag FROM fixtures f JOIN results r ON r.fixture_id=f.id WHERE (f.home_id=? OR f.away_id=?) "
                       "ORDER BY f.date DESC LIMIT 1", (club_id, club_id)).fetchone()
    mk = lambda f: dict(home=cn(f["home_id"]), away=cn(f["away_id"]), home_id=f["home_id"], away_id=f["away_id"], date=ar_date(f["date"]),
                        round=f["round"], comp=lg[0], venue="على أرضك" if f["home_id"] == club_id else "خارج أرضك")
    nxt = mk(nx)
    nxt["opp_pos"] = next(i + 1 for i, r in enumerate(tbl) if r["club_id"] == (nx["away_id"] if nx["home_id"] == club_id else nx["home_id"]))
    lst = mk(last)
    lst.update(hg=last["hg"], ag=last["ag"])

    # ----- tasks (real data: expiring contracts, injuries, a real negotiation, job board)
    tasks = []
    obj = J.board_objectives(con, club_id)
    conf = J.board_confidence(con)
    for p in squad:
        if p["injury_days"] > 0:
            tasks.append(dict(prio=1, kind="injury", text=f"{p['name']} مصاب — يحتاج قراراً", go="squad", pid=p["id"]))
    ctx_players = [p for p in squad if p["contract_left"] <= 1][:2]
    for p in ctx_players:
        tasks.append(dict(prio=2, kind="contract", text=f"عقد {p['name']} ينتهي قريباً", go="squad", pid=p["id"]))
    other = con.execute("SELECT id,name_ar FROM v_player WHERE club_id<>? AND club_id IS NOT NULL ORDER BY ovr DESC LIMIT 1 OFFSET 40", (club_id,)).fetchone()
    ctx = N.build_context(con, "buy", other["id"], club_id, seed=5)
    st = N.new_negotiation(ctx)
    N.inquire(st)
    ask = st["current_ask"] if "current_ask" in st else None
    N.submit_club_offer(st, dict(immediate=int(N.public_view(st).get("stated_ask", 1_000_000) * 0.85)))
    N.save(con, st)
    pv = N.public_view(st)
    tasks.append(dict(prio=1, kind="offer", text=f"رد النادي على عرضك لضم {other['name_ar']} ينتظرك", go="transfers"))
    M.set_reputation(con, 78)
    for d in range(40):
        if J.generate_offers(con):
            break
        con.execute("UPDATE career_info SET cur_date=date(cur_date,'+1 day')")
    offers = J.pending_offers(con)
    if offers:
        tasks.append(dict(prio=3, kind="job", text=f"عرض تدريب من {offers[0]['payload']['club']['name']}", go="office"))
    con.execute("UPDATE career_info SET cur_date=?", (cur,))
    tasks.sort(key=lambda t: t["prio"])

    # ----- news (derived from real results)
    news = []
    big = con.execute("SELECT f.home_id,f.away_id,r.hg,r.ag,f.date FROM results r JOIN fixtures f ON f.id=r.fixture_id WHERE f.league_id=? "
                      "ORDER BY ABS(r.hg-r.ag) DESC, r.hg+r.ag DESC LIMIT 1", (lid,)).fetchone()
    news.append(dict(kind="نتيجة", title=f"{cn(big['home_id'])} يكتسح {cn(big['away_id'])}" if big["hg"] > big["ag"] else f"{cn(big['away_id'])} يفوز بقوة على {cn(big['home_id'])}",
                     line=f"انتهت المباراة {big['hg']}-{big['ag']}", date=ar_date(big["date"])))
    top = con.execute("SELECT s.player_id,s.goals FROM player_season_stats s WHERE s.season=? ORDER BY s.goals DESC LIMIT 1", (season,)).fetchone()
    tn = con.execute("SELECT name_ar,club_id FROM v_player WHERE id=?", (top["player_id"],)).fetchone()
    news.append(dict(kind="ترتيب", title=f"{tn['name_ar']} يتصدر الهدافين", line=f"{top['goals']} أهداف مع {cn(tn['club_id'])}", date=ar_date(cur)))
    news.append(dict(kind="ترتيب", title=f"{cn(tbl[0]['club_id'])} في صدارة الدوري", line=f"{tbl[0]['pts']} نقطة بعد {tbl[0]['p']} جولات", date=ar_date(cur)))

    # ----- table around the club (top 5 + user's club if outside)
    def trow(i, r):
        return dict(pos=i + 1, club=cn(r["club_id"]), club_id=r["club_id"], p=r["p"], gd=r["gd"], pts=r["pts"], me=r["club_id"] == club_id)
    rows = [trow(i, r) for i, r in enumerate(tbl)]
    snippet = rows[:5] + ([rows[pos - 1]] if pos > 5 else [])

    # ----- market (other clubs' players: estimated value RANGE + confidence; never the secret price)
    market = []
    for r in con.execute("SELECT id FROM v_player WHERE club_id IS NOT NULL AND club_id<>? ORDER BY ovr DESC LIMIT 400", (club_id,)).fetchall()[::3][:120]:
        c2 = N.build_context(con, "buy", r["id"], club_id, seed=5)
        est = N.market_estimate(c2)
        p = c2["player"]
        pr = con.execute("SELECT name_ar,pos,birth_date FROM v_player WHERE id=?", (r["id"],)).fetchone()
        market.append(dict(id=r["id"], name=pr["name_ar"], club=cn(p["club_id"]), pos=pr["pos"], pos_ar=POS_AR[pr["pos"]],
                           age=p["age"], ovr=p["ovr"], pot_hint="", value_low=est["low"], value_high=est["high"],
                           confidence=est["confidence"], wage=p["wage"], contract_left=p["contract_years_left"], scout="غير مكتشف",
                           quality="تجريبي"))
    fin = N.get_finance(con, club_id)
    data = dict(demo=True, season=f"{season}/{str(season + 1)[2:]}", date=ar_date(cur),
                club=dict(id=club_id, name=cn(club_id), badge=club_id % 12 + 1, league=lg[0], country=lg[1], position=pos,
                          league_size=len(tbl), pts=next(r["pts"] for r in tbl if r["club_id"] == club_id),
                          transfer_budget=fin["transfer_budget"], wage_budget=fin["wage_budget"]),
                manager=dict(name=M.get_name(con), reputation=M.get_profile(con)["reputation"], photo=None),
                board=dict(level=conf["level"], value=conf["value"], objective=obj["key"], target=obj["target_position"]),
                next_match=nxt, last_match=lst, tasks=tasks, news=news, table=snippet, squad=squad, market=market,
                job_offers=[dict(club=o["payload"]["club"]["name"], league=o["payload"]["club"]["league"]) for o in offers],
                negotiation=dict(player=other["name_ar"], stage=pv["stage"], tension=pv["tension"]["club"]))
    os.makedirs(os.path.dirname(out_js), exist_ok=True)
    open(out_js, "w", encoding="utf-8").write("window.DEMO=" + json.dumps(data, ensure_ascii=False) + ";")
    print(f"demo exported: squad {len(squad)}, market {len(market)}, tasks {len(tasks)}, news {len(news)} -> {out_js}")
    con.close()


if __name__ == "__main__":
    main(os.path.join(ROOT, "ui", "data", "demo.js"))
