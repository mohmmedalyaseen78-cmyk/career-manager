"""Local game server: serves the UI and a small JSON API over the engine. Binds 127.0.0.1 only; no network access."""
import json
import mimetypes
import os
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if getattr(sys, "frozen", False):
    ROOT = getattr(sys, "_MEIPASS", ROOT)
sys.path.insert(0, ROOT)
from engine import attrs as A, comps, db, jobs as J, manager as M, negotiation as N, play as P, season as S  # noqa: E402
from engine.career import CareerManager  # noqa: E402

POS_GROUP = {"GK": "GK", "CB": "DF", "LB": "DF", "RB": "DF", "CDM": "MF", "CM": "MF", "CAM": "MF", "LM": "MF", "RM": "MF",
             "LW": "FW", "RW": "FW", "ST": "FW"}
GRP_POS = {"GK": ["GK"], "DF": ["CB", "LB", "RB"], "MF": ["CDM", "CM", "CAM", "LM", "RM"], "FW": ["LW", "RW", "ST"]}


class Game:
    def __init__(self, saves_dir, world_path, ui_dir):
        self.saves, self.world, self.ui = saves_dir, world_path, ui_dir
        self.cm = CareerManager(saves_dir, world_path)
        self.con = None
        self.cid = None
        self.live = None  # (MatchSession, meta)
        self.lock = threading.RLock()
        self.shutdown_timer = None
        self.world_info = db.open_world(world_path).execute("SELECT key,value FROM meta").fetchall()

    # ---------- helpers
    def meta(self):
        return {r[0]: r[1] for r in self.world_info}

    def info(self):
        return self.con.execute("SELECT * FROM career_info").fetchone()

    def cname(self, cid):
        r = self.con.execute("SELECT name_ar,name FROM world.clubs WHERE id=?", (cid,)).fetchone()
        return (r[0] or r[1]) if r else "—"

    def pjson(self, p, detail=False, own=True):
        season = self.info()["season"]
        at = list(A.unpack(p["attrs"])) if isinstance(p["attrs"], (bytes, bytearray)) else list(p["attrs"])
        d = dict(id=p["id"], name=p.get("name_ar") or p.get("name"), pos=p["pos"], pos2=[x for x in (p["pos2"] or "").split(",") if x],
                 age=season - int(p["birth_date"][:4]), ovr=p["ovr"], form=p["form"], fitness=p["fitness"], morale=p["morale"],
                 injury=p["injury_days"], status=p["status"], wage=p["wage"], value=p["value"],
                 left=max(0, (p["contract_end"] or season) - season), grp=POS_GROUP[p["pos"]],
                 face=A.gk_stats(at) if p["pos"] == "GK" else A.main_stats(at))
        if own:
            d["pot"] = p["potential"]
        if detail:
            d["attrs"] = dict(zip(A.ATTRS, at))
        return d

    def get_player(self, pid):
        r = self.con.execute("SELECT * FROM v_player WHERE id=?", (pid,)).fetchone()
        return dict(r) if r else None

    # ---------- boot / careers
    def boot(self):
        lg = [dict(r) for r in db.open_world(self.world).execute("SELECT id,code,name_ar,name,country,tier FROM leagues ORDER BY id")]
        w = db.open_world(self.world)
        clubs = [dict(r) for r in w.execute("SELECT id,league_id,name_ar,name,reputation FROM clubs ORDER BY reputation DESC")]
        return dict(world=self.meta(), careers=self.cm.list_careers(), leagues=lg, clubs=clubs, open=self.cid)

    def open_career(self, cid):
        self.close()
        self.con = self.cm.open(cid)
        self.cid = cid
        J.ensure_schema(self.con)
        M.ensure_profile(self.con)
        comps.ensure_season(self.con)
        return self.home()

    def new_career(self, club_id, name):
        name = M.validate_name(name)
        cid = self.cm.create(int(club_id), name)
        return self.open_career(cid)

    def close(self):
        if self.con:
            try:
                self.cm.autosave(self.con)
                self.con.close()
            except Exception:
                pass
        self.con, self.cid, self.live = None, None, None

    def save(self):
        self.cm.autosave(self.con, backup=True)
        return dict(ok=True)

    # ---------- home
    def tasks(self):
        info, t = self.info(), []
        season, user = info["season"], info["club_id"]
        if S.next_date(self.con) is None:
            t.append(dict(prio=0, kind="season", text="انتهى الموسم — راجع الإنجازات وابدأ الموسم الجديد", go="office"))
        for p in db.squad(self.con, user):
            if p["injury_days"] > 0:
                t.append(dict(prio=1, kind="injury", text=f"{p['name_ar']} مصاب ({p['injury_days']} يوماً)", go="squad", pid=p["id"]))
            elif p["status"] == 1:
                t.append(dict(prio=2, kind="susp", text=f"{p['name_ar']} موقوف هذه المباراة", go="squad", pid=p["id"]))
            elif (p["contract_end"] or season) <= season and p["ovr"] >= 60:
                t.append(dict(prio=2, kind="contract", text=f"عقد {p['name_ar']} ينتهي هذا الموسم", go="squad", pid=p["id"]))
        for r in self.con.execute("SELECT id,state FROM negotiation WHERE status IN ('active','agreed') ORDER BY id DESC LIMIT 5"):
            st = N.from_json(r[1])
            pn = self.get_player(st["ctx"]["player"]["id"])
            t.append(dict(prio=1, kind="offer", text=f"مفاوضة مفتوحة: {pn['name_ar']}", go="transfers", nid=r[0]))
        for o in J.pending_offers(self.con):
            t.append(dict(prio=3, kind="job", text=f"عرض تدريب من {o['payload']['club']['name']}", go="office"))
        t.sort(key=lambda x: x["prio"])
        return t[:8]

    def news(self):
        info = self.info()
        season, user = info["season"], info["club_id"]
        lid = J.league_of(self.con, user)
        n = []
        last = self.con.execute("SELECT MAX(f.date) FROM fixtures f WHERE f.played=1 AND f.league_id=?", (lid,)).fetchone()[0]
        if last:
            rows = self.con.execute("SELECT f.home_id,f.away_id,r.hg,r.ag FROM results r JOIN fixtures f ON f.id=r.fixture_id "
                                    "WHERE f.league_id=? AND f.date=? ORDER BY ABS(r.hg-r.ag) DESC, r.hg+r.ag DESC", (lid, last)).fetchall()
            for r in rows[:2]:
                w, l = (r["home_id"], r["away_id"]) if r["hg"] >= r["ag"] else (r["away_id"], r["home_id"])
                n.append(dict(kind="نتيجة", title=f"{self.cname(w)} يتفوّق على {self.cname(l)}" if r["hg"] != r["ag"] else f"تعادل {self.cname(r['home_id'])} و{self.cname(r['away_id'])}",
                              line=f"{r['hg']} - {r['ag']}"))
        sc = self.con.execute("SELECT s.player_id,s.goals,s.club_id FROM player_season_stats s JOIN fixtures f ON 1=0 WHERE 0").fetchall() if False else \
            self.con.execute("SELECT player_id,goals,club_id FROM player_season_stats WHERE season=? ORDER BY goals DESC LIMIT 1", (season,)).fetchall()
        for r in sc:
            p = self.get_player(r["player_id"])
            if p and r["goals"] > 0:
                n.append(dict(kind="هدّافون", title=f"{p['name_ar']} يتصدر الهدافين", line=f"{r['goals']} أهداف مع {self.cname(r['club_id'])}"))
        tb = S.table(self.con, season, lid)
        if tb and tb[0]["p"] > 0:
            n.append(dict(kind="ترتيب", title=f"{self.cname(tb[0]['club_id'])} في الصدارة", line=f"{tb[0]['pts']} نقطة بعد {tb[0]['p']} مباراة"))
        for o in J.pending_offers(self.con):
            n.append(dict(kind="مدربون", title=f"{o['payload']['club']['name']} يرغب بالتعاقد معك", line="راجع العروض في مكتب النادي"))
        return n

    def home(self):
        c = self.con
        info = self.info()
        season, user = info["season"], info["club_id"]
        lid = J.league_of(c, user)
        lg = c.execute("SELECT name_ar,name,tier,country FROM world.leagues WHERE id=?", (lid,)).fetchone()
        tbl = S.table(c, season, lid)
        pos = next((i + 1 for i, r in enumerate(tbl) if r["club_id"] == user), None)
        fin = N.get_finance(c, user)
        prof = M.get_profile(c)
        fx = P.next_user_fixture(c)
        nxt = None
        if fx:
            opp = fx["away_id"] if fx["home_id"] == user else fx["home_id"]
            nxt = dict(comp=self.comp_name(fx["league_id"]), id=fx["id"], date=fx["date"], round=fx["round"], home=fx["home_id"] == user, opp=opp, opp_name=self.cname(opp),
                       opp_pos=next((i + 1 for i, r in enumerate(tbl) if r["club_id"] == opp), None))
        last = c.execute("SELECT f.*,r.hg,r.ag FROM fixtures f JOIN results r ON r.fixture_id=f.id WHERE (f.home_id=? OR f.away_id=?) "
                         "ORDER BY f.date DESC LIMIT 1", (user, user)).fetchone()
        lm = last and dict(comp=self.comp_name(last["league_id"]), date=last["date"], round=last["round"], home=self.cname(last["home_id"]), away=self.cname(last["away_id"]),
                           hg=last["hg"], ag=last["ag"], fid=last["id"])
        rows = [dict(pos=i + 1, club=self.cname(r["club_id"]), id=r["club_id"], p=r["p"], w=r["w"], d=r["d"], l=r["l"], gf=r["gf"], ga=r["ga"],
                     gd=r["gf"] - r["ga"], pts=r["pts"], me=r["club_id"] == user) for i, r in enumerate(tbl)]
        conf = J.board_confidence(c)
        return dict(season=f"{season}/{(season + 1) % 100:02d}", season_year=season, date=info["cur_date"], finished=S.next_date(c) is None,
                    club=dict(id=user, name=info["club_name"], league=lg["name_ar"] or lg["name"], tier=lg["tier"], position=pos,
                              league_size=len(tbl), transfer_budget=fin["transfer_budget"], wage_budget=fin["wage_budget"]),
                    manager=dict(name=info["manager_name"], reputation=prof["reputation"]),
                    board=dict(level=conf["level"], value=conf["value"], objective=conf["objective"]),
                    next=nxt, last=lm, tasks=self.tasks(), news=self.news()[:4], table=rows, prefs=P.get_prefs(c),
                    world=self.meta().get("kind", ""), settings=dict(difficulty=P.get_setting(c, "difficulty", "realistic")))

    # ---------- squad
    def squad(self):
        info = self.info()
        sq = sorted(db.squad(self.con, info["club_id"]), key=lambda p: -p["ovr"])
        stats = {r["player_id"]: r for r in self.con.execute("SELECT * FROM player_season_stats WHERE season=?", (info["season"],))}
        out = []
        for p in sq:
            j = self.pjson(p, detail=True)
            s = stats.get(p["id"])
            j["stats"] = dict(apps=s["apps"], goals=s["goals"], assists=s["assists"], rating=round(s["rating_sum"] / s["rated"], 1) if s and s["rated"] else None) if s else dict(apps=0, goals=0, assists=0, rating=None)
            out.append(j)
        lu, bn = P.user_side(db.squad(self.con, info["club_id"]), P.get_prefs(self.con))
        return dict(players=out, prefs=P.get_prefs(self.con), formations=list(P.FORMATIONS), slots=P.FORMATIONS,
                    xi=[p["id"] for _, p in lu], xi_slots=[s for s, _ in lu], bench=[p["id"] for p in bn])

    def set_prefs(self, b):
        return P.set_prefs(self.con, **{k: b[k] for k in b if k in P.DEFAULT_PREFS})

    # ---------- market
    def market(self, q):
        info = self.info()
        user = info["club_id"]
        grp, age, omin, text = q.get("grp", "ALL"), int(q.get("age", 99)), int(q.get("ovr", 0)), q.get("q", "").strip()
        club = q.get("club")
        sql = "SELECT * FROM v_player WHERE (club_id IS NULL OR club_id<>?) AND ovr>=?"
        args = [user, omin]
        if grp != "ALL":
            sql += " AND pos IN (%s)" % ",".join("?" * len(GRP_POS[grp]))
            args += GRP_POS[grp]
        if text:
            from engine.names_ar import normalize
            t = normalize(text)
            sql += " AND search >= ? AND search < ?"
            args += [t, t + "￿"]
        sql += " ORDER BY ovr DESC LIMIT 400"
        rows = [dict(r) for r in self.con.execute(sql, args)]
        out = []
        free = q.get("free") == "1"
        for r in rows:
            if (age < 99 and info["season"] - int(r["birth_date"][:4]) > age):
                continue
            if free and r["club_id"] is not None:
                continue
            ctx = N.build_context(self.con, "buy" if r["club_id"] else "free_agent", r["id"], user,
                                  difficulty=P.get_setting(self.con, "difficulty", "realistic"))
            est = N.market_estimate(ctx)
            j = self.pjson(r, own=False)
            j.update(club=self.cname(r["club_id"]) if r["club_id"] else "بلا نادٍ", club_id=r["club_id"], vlow=est["low"], vhigh=est["high"], conf=est["confidence"])
            out.append(j)
            if len(out) >= 60:
                break
        return dict(players=out)

    # ---------- negotiation
    def _nview(self, st, extra=None):
        v = N.public_view(st)
        p = self.get_player(st["ctx"]["player"]["id"])
        v.update(player=dict(id=p["id"], name=p["name_ar"], pos=p["pos"], age=st["ctx"]["player"]["age"], ovr=p["ovr"],
                             club=self.cname(p["club_id"]) if p["club_id"] else "بلا نادٍ", wage=p["wage"]),
                 budget=N.get_finance(self.con, self.info()["club_id"])["transfer_budget"], extra=extra or {})
        if st["stage"] in ("confirm",) or st["status"] in ("agreed", "done"):
            v["impact"] = N.budget_impact(st)
        return v

    def neg_start(self, kind, pid):
        user = self.info()["club_id"]
        p = self.get_player(pid)
        if kind == "buy" and not p["club_id"]:
            kind = "free_agent"
        for r in self.con.execute("SELECT id,state FROM negotiation WHERE status='active' AND player_id=?", (pid,)):
            st = N.from_json(r[1])
            if st["kind"] == kind:
                return self._nview(st, N.inquire(st) if st["stage"] == "inquiry" else {})
        wopen, wleft = P.window(self.info()["cur_date"])
        if kind in ("buy", "loan") and not wopen:
            return dict(error="نافذة الانتقالات مغلقة (تفتح من 1 يونيو إلى 31 أغسطس ومن 1 إلى 31 يناير)")
        ctx = N.build_context(self.con, kind, pid, user, difficulty=P.get_setting(self.con, "difficulty", "realistic"),
                              scouting=P.get_scouting(self.con), window_open=wopen or kind == "free_agent", window_days_left=wleft or 30)
        st = N.new_negotiation(ctx)
        inq = N.inquire(st)
        N.save(self.con, st)
        return self._nview(st, inq)

    def neg_act(self, nid, act, offer=None):
        st = N.load(self.con, nid)
        resp = None
        try:
            if act == "club":
                resp = N.submit_club_offer(st, offer)
            elif act == "contract":
                resp = N.submit_contract_offer(st, offer)
            elif act == "counter":
                resp = N.accept_counter(st)
            elif act in ("accept", "reject", "sellcounter"):
                resp = N.respond_incoming(st, "counter" if act == "sellcounter" else act, int(offer) if offer else None)
            elif act == "confirm":
                N.confirm(st)
                st = N.apply_deal(self.con, st)
                resp = dict(response="done")
            elif act == "walk":
                N.walk_away(st)
                resp = dict(response="walked")
        except N.NegotiationError as e:
            return dict(error=str(e), view=self._nview(st))
        N.save(self.con, st)
        return dict(resp=resp, view=self._nview(st))

    def neg_list(self):
        out = []
        for r in self.con.execute("SELECT id,state FROM negotiation WHERE status IN ('active','agreed') ORDER BY id DESC"):
            out.append(self._nview(N.from_json(r[1])))
        return dict(items=out)

    def renew(self, pid):
        user = self.info()["club_id"]
        ctx = N.build_context(self.con, "renewal", pid, user, difficulty=P.get_setting(self.con, "difficulty", "realistic"))
        st = N.new_negotiation(ctx)
        N.save(self.con, st)
        return self._nview(st, N.inquire(st))

    def comp_name(self, lid):
        if lid < 1000:
            return None
        r = self.con.execute("SELECT name FROM comp_info WHERE league_id=? ORDER BY season DESC", (lid,)).fetchone()
        return r[0] if r else None

    # ---------- competitions / calendar
    def league(self, lid=None, rnd=None):
        info = self.info()
        season = info["season"]
        lid = int(lid) if lid else J.league_of(self.con, info["club_id"])
        tbl = S.table(self.con, season, lid)
        rows = [dict(pos=i + 1, club=self.cname(r["club_id"]), id=r["club_id"], p=r["p"], w=r["w"], d=r["d"], l=r["l"], gf=r["gf"], ga=r["ga"],
                     gd=r["gf"] - r["ga"], pts=r["pts"], me=r["club_id"] == info["club_id"]) for i, r in enumerate(tbl)]
        maxr = self.con.execute("SELECT MAX(round) FROM fixtures WHERE season=? AND league_id=?", (season, lid)).fetchone()[0]
        cur = self.con.execute("SELECT COALESCE(MIN(round),?) FROM fixtures WHERE season=? AND league_id=? AND played=0", (maxr, season, lid)).fetchone()[0]
        rnd = int(rnd) if rnd else cur
        fx = [dict(home=self.cname(r["home_id"]), away=self.cname(r["away_id"]), hg=r["hg"], ag=r["ag"], date=r["date"], me=info["club_id"] in (r["home_id"], r["away_id"]))
              for r in self.con.execute("SELECT f.*,r.hg,r.ag FROM fixtures f LEFT JOIN results r ON r.fixture_id=f.id WHERE f.season=? AND f.league_id=? AND f.round=?", (season, lid, rnd))]
        scorers = [dict(name=(self.get_player(r["player_id"]) or {}).get("name_ar", "?"), club=self.cname(r["club_id"]), goals=r["goals"], assists=r["assists"])
                   for r in self.con.execute("SELECT s.* FROM player_season_stats s JOIN club_season c ON c.club_id=s.club_id AND c.season=s.season "
                                             "WHERE s.season=? AND c.league_id=? AND s.goals>0 ORDER BY s.goals DESC, s.assists DESC LIMIT 10", (season, lid))]
        leagues = [dict(id=r["id"], name=r["name_ar"] or r["name"], tier=r["tier"], country=r["country"]) for r in self.con.execute("SELECT * FROM world.leagues")]
        return dict(table=rows, round=rnd, rounds=maxr, fixtures=fx, scorers=scorers, league_id=lid, leagues=leagues)

    def cups(self):
        info = self.info()
        out = []
        for ci in self.con.execute("SELECT league_id,name,comp FROM comp_info WHERE season=? ORDER BY comp,league_id", (info["season"],)):
            v = comps.view(self.con, ci["league_id"])
            for rd in v["rounds"]:
                for f in rd["fixtures"]:
                    f["home"], f["away"] = self.cname(f["home"]), self.cname(f["away"])
                    f["winner"] = self.cname(f["winner"]) if f["winner"] else None
            out.append(dict(id=ci["league_id"], name=ci["name"], kind=ci["comp"], rounds=v["rounds"]))
        hon = [dict(season=r[0], comp=r[1], text=r[2], won=r[3]) for r in self.con.execute("SELECT season,comp_name,result,won FROM club_honours ORDER BY season DESC")]
        return dict(items=out, honours=hon, status=[dict(comp=a, text=b, won=c) for a, b, c in comps.user_status(self.con, info["club_id"], info["season"])])

    def calendar(self):
        info = self.info()
        user = info["club_id"]
        out = []
        for r in self.con.execute("SELECT f.*,r.hg,r.ag FROM fixtures f LEFT JOIN results r ON r.fixture_id=f.id WHERE f.season=? AND (f.home_id=? OR f.away_id=?) ORDER BY f.date", (info["season"], user, user)):
            home = r["home_id"] == user
            opp = r["away_id"] if home else r["home_id"]
            res = None
            if r["played"]:
                m, t = (r["hg"], r["ag"]) if home else (r["ag"], r["hg"])
                res = dict(score=f"{r['hg']} - {r['ag']}", out="w" if m > t else "d" if m == t else "l")
            out.append(dict(comp=self.comp_name(r["league_id"]), date=r["date"], round=r["round"], home=home, opp=self.cname(opp), result=res))
        return dict(items=out, today=info["cur_date"])

    # ---------- match / days
    def day_quick(self):
        sm = S.advance_matchday(self.con)
        return self._after_day(sm)

    def _after_day(self, sm):
        if sm is None:
            return dict(finished=True, home=self.home())
        P.post_day(self.con, sm)
        comps.advance(self.con)
        P.expire_incoming(self.con)
        P.generate_incoming(self.con)
        J.generate_offers(self.con)
        self.cm.autosave(self.con)
        return dict(summary=self._summary(sm), home=self.home())

    def _summary(self, sm):
        if not sm.get("user"):
            return dict(date=sm["date"])
        u = sm["user"]
        return dict(date=sm["date"], home=self.cname(u["home"]), away=self.cname(u["away"]), score=list(u["score"]), fid=u["fixture_id"])

    def match_start(self):
        fx = P.next_user_fixture(self.con)
        if fx is None:
            return dict(error="لا توجد مباراة قادمة")
        # make sure all earlier dates are processed (should be none) - the user's fixture date is the next date
        if fx["date"] != S.next_date(self.con):
            sm = S.advance_matchday(self.con)
            self._after_day(sm)
        self.live = P.start_live(self.con)
        return self.match_state()

    def _side_view(self, ms, i):
        s = ms.S[i]
        return dict(club=self.cname(s.club_id), goals=s.goals, subs=s.subs,
                    on=[dict(id=x["p"]["id"], name=x["p"].get("name_ar"), slot=x["slot"], pos=x["p"]["pos"], ovr=x["p"]["ovr"], fit=x["p"]["fitness"]) for x in s.on],
                    bench=[dict(id=b["id"], name=b.get("name_ar"), pos=b["pos"], ovr=b["ovr"]) for b in s.bench],
                    tactics=dict(s.tactics), stats=dict(s.stats, xg=round(s.stats["xg"], 2)), vacant=len(getattr(s, "vacant", [])))

    def match_state(self, new_from=0):
        ms, meta = self.live
        names = {}
        for s in ms.S:
            for x in s.all.values():
                names[x["p"]["id"]] = x["p"].get("name_ar")
        ev = [dict(e, name=names.get(e["player_id"]), name2=names.get(e["player2_id"]), side=0 if e["club_id"] == ms.S[0].club_id else 1) for e in ms.events[new_from:]]
        return dict(minute=ms.minute, finished=ms.finished, half=ms.at_half_time, score=list(ms.score()), side=meta["side"],
                    sides=[self._side_view(ms, 0), self._side_view(ms, 1)], events=ev, n_events=len(ms.events),
                    max_subs=ms.cfg["max_subs"], formations=list(P.FORMATIONS))

    def match_advance(self, b):
        ms, meta = self.live
        n0 = len(ms.events)
        mode = b.get("mode", "event")
        if mode == "event":
            ms.advance(stop_on_event=True)
        elif mode == "half":
            ms.advance(until=45 if ms.minute < 45 else 90)
        elif mode == "end":
            ms.advance()
        else:
            ms.advance(until=min(90, ms.minute + int(b.get("minutes", 5))))
        return self.match_state(int(b.get("from", n0)))

    def match_act(self, b):
        ms, meta = self.live
        side, a = meta["side"], b["act"]
        r = "ok"
        if a == "sub":
            r = ms.substitute(side, int(b["out"]), int(b["in"]))
        elif a == "tactics":
            ms.set_tactics(side, b.get("mentality"), b.get("pressing"), b.get("tempo"))
        elif a == "formation":
            r = ms.set_formation(side, b["formation"])
        elif a == "fill":
            r = ms.fill_vacancy(side, int(b["in"]))
        st = self.match_state(int(b.get("from", len(ms.events))))
        st["result"] = r
        return st

    def match_commit(self):
        ms, meta = self.live
        if not ms.finished:
            ms.advance()
        res = ms.result()
        sm = P.finish_day(self.con, meta["fixture"]["id"], res)
        self.live = None
        out = self._after_day(sm)
        fid = meta["fixture"]["id"]
        ts = [json.loads(r[0]) for r in self.con.execute("SELECT stats FROM match_team_stats WHERE fixture_id=? ORDER BY rowid", (fid,))] if False else res["team_stats"]
        players = sorted(res["players"], key=lambda p: -p["rating"])[:5]
        pn = {p["player_id"]: (self.get_player(p["player_id"]) or {}).get("name_ar", "?") for p in players}
        out["report"] = dict(score=list(res["score"]), home=self.cname(meta["fixture"]["home_id"]), away=self.cname(meta["fixture"]["away_id"]),
                             team_stats=res["team_stats"], top=[dict(name=pn[p["player_id"]], rating=p["rating"], goals=p["goals"], assists=p["assists"]) for p in players],
                             motm=(self.get_player(res["motm"]) or {}).get("name_ar"))
        return out

    # ---------- season end / archive
    def season_end(self):
        if S.next_date(self.con) is not None:
            return dict(error="الموسم لم ينتهِ بعد")
        h = self.home()
        out = P.end_of_season(self.con)
        self.cm.autosave(self.con, backup=True)
        arch = S.club_archive(self.con)
        return dict(done=out, last=arch[0] if arch else None, honours=self.cups()["honours"][:6], home=self.home())

    def archive(self):
        return dict(items=S.club_archive(self.con))

    # ---------- jobs
    def offers(self):
        return dict(items=[dict(id=o["id"], club=o["payload"]["club"], objective=o["payload"]["objective"], wage=o["payload"]["weekly_wage"],
                                years=o["payload"]["length_years"], expires=o["expires"]) for o in J.pending_offers(self.con)])

    def offer_act(self, oid, act):
        if act == "compare":
            return J.compare(self.con, oid)
        if act == "decline":
            J.decline_offer(self.con, oid)
            return dict(ok=True)
        if act == "accept":
            r = J.accept_offer(self.con, oid)
            self.cm.autosave(self.con, backup=True)
            return dict(ok=True, home=self.home(), **r)

    def training(self, b=None):
        if b:
            P.set_training(self.con, b.get("focus"), b.get("intensity"))
            if "scouting" in b:
                P.set_scouting(self.con, b["scouting"])
        return dict(training=P.get_training(self.con), scouting=P.get_scouting(self.con), scout_cost=P.SCOUT_COST)

    def photo_set(self, b):
        import base64
        data = base64.b64decode(b["data"].split(",")[-1])
        try:
            M.set_photo(self.con, self.saves, data, declared_name=b.get("name"))
        except M.ManagerError as e:
            return dict(error=str(e))
        self.cm.autosave(self.con)
        return dict(ok=True, version=M.get_profile(self.con)["photo_version"])

    def photo_remove(self):
        M.remove_photo(self.con, self.saves)
        return dict(ok=True)

    def set_setting(self, key, val):
        if key == "difficulty" and val in N.DIFFICULTIES:
            P.put_setting(self.con, key, val)
        return dict(ok=True)

    def player_detail(self, pid):
        p = self.get_player(pid)
        info = self.info()
        own = p["club_id"] == info["club_id"]
        j = self.pjson(p, detail=own, own=own)
        j["club"] = self.cname(p["club_id"]) if p["club_id"] else "بلا نادٍ"
        j["nat"], j["foot"], j["height"], j["weight"] = p["nationality"], p["foot"], p["height"], p["weight"]
        return j


def make_handler(game):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json; charset=utf-8"):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store" if ctype.startswith("application/json") else "max-age=3600")
            self.end_headers()
            self.wfile.write(body)

        def _static(self, path):
            path = path.lstrip("/") or "index.html"
            fp = os.path.normpath(os.path.join(game.ui, path))
            if not fp.startswith(os.path.normpath(game.ui)) or not os.path.isfile(fp):
                return self._send(404, b"not found", "text/plain")
            ct = mimetypes.guess_type(fp)[0] or "application/octet-stream"
            if fp.endswith(".js"):
                ct = "text/javascript; charset=utf-8"
            elif fp.endswith(".css"):
                ct = "text/css; charset=utf-8"
            elif fp.endswith(".html"):
                ct = "text/html; charset=utf-8"
            self._send(200, open(fp, "rb").read(), ct)

        def do_GET(self):
            u = urlparse(self.path)
            if u.path.startswith("/api/"):
                return self._api(u.path[5:], {k: v[0] for k, v in parse_qs(u.query).items()}, {})
            self._static(u.path)

        def do_POST(self):
            u = urlparse(self.path)
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n else b"{}"
            try:
                body = json.loads(raw or b"{}")
            except ValueError:
                body = {}
            self._api(u.path[5:], {k: v[0] for k, v in parse_qs(u.query).items()}, body)

        def _api(self, ep, q, b):
            with game.lock:
                if game.shutdown_timer:
                    game.shutdown_timer.cancel()
                    game.shutdown_timer = None
                try:
                    out = route(game, ep, q, b)
                    self._send(200, out)
                except Exception as e:  # report the problem to the UI instead of dying
                    traceback.print_exc()
                    self._send(200, dict(error=f"{type(e).__name__}: {e}"))
    return H


def route(g, ep, q, b):
    if ep == "boot":
        return g.boot()
    if ep == "bye":
        def _quit():
            with g.lock:
                g.close()
            os._exit(0)
        g.shutdown_timer = threading.Timer(4.0, _quit)
        g.shutdown_timer.start()
        return dict(ok=True)
    if ep == "career/new":
        return g.new_career(b["club_id"], b.get("name", ""))
    if ep == "career/open":
        return g.open_career(b["id"])
    if ep == "career/delete":
        if g.cid == b["id"]:
            g.close()
        g.cm.delete(b["id"], confirmed=bool(b.get("confirm")))
        return dict(ok=True, careers=g.cm.list_careers())
    if ep == "career/close":
        g.close()
        return g.boot()
    if g.con is None:
        return dict(error="no career open")
    table = {
        "home": lambda: g.home(), "save": lambda: g.save(), "squad": lambda: g.squad(),
        "prefs": lambda: g.set_prefs(b), "market": lambda: g.market(q),
        "player": lambda: g.player_detail(int(q["id"])),
        "neg/start": lambda: g.neg_start(b["kind"], int(b["player_id"])), "neg/act": lambda: g.neg_act(int(b["id"]), b["act"], b.get("offer")),
        "neg/list": lambda: g.neg_list(), "neg/renew": lambda: g.renew(int(b["player_id"])),
        "league": lambda: g.league(q.get("lid"), q.get("round")), "calendar": lambda: g.calendar(),
        "day/quick": lambda: g.day_quick(), "match/start": lambda: g.match_start(), "match/state": lambda: g.match_state(),
        "match/advance": lambda: g.match_advance(b), "match/act": lambda: g.match_act(b), "match/commit": lambda: g.match_commit(),
        "season/end": lambda: g.season_end(), "archive": lambda: g.archive(),
        "offers": lambda: g.offers(), "offer/act": lambda: g.offer_act(int(b["id"]), b["act"]),
        "cups": lambda: g.cups(), "training": lambda: g.training(b or None), "photo/set": lambda: g.photo_set(b), "photo/remove": lambda: g.photo_remove(),
        "setting": lambda: g.set_setting(b["key"], b["value"]), "news": lambda: dict(items=g.news()),
    }
    if ep not in table:
        return dict(error="unknown endpoint " + ep)
    return table[ep]()


def serve(saves_dir, world_path, ui_dir, port=0):
    game = Game(saves_dir, world_path, ui_dir)
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(game))
    srv.daemon_threads = True
    return srv, game
