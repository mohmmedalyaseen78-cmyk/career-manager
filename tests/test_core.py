import os
import random
import shutil
import sqlite3
import statistics
import sys
import tempfile
import unittest
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine import attrs as A, talents as T, db, season as S
from engine.career import CareerManager, ConfirmRequired
from engine.match import (MatchSession, auto_lineup, simulate_detailed, simulate_fast, team_strength, validate_match)
from engine.names_ar import FIRST, FAMILY, normalize
from engine.worldgen import build_world

TMP = tempfile.mkdtemp(prefix="grafeco_test_")
WORLD = os.path.join(TMP, "world.db")


def setUpModule():
    build_world(WORLD, seed=7)


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


class TestAttributes(unittest.TestCase):
    def test_ovr_exact_and_consistent(self):
        rng = random.Random(1)
        for pos in A.POSITIONS:
            for target in (45, 60, 72, 85, 93):
                for _ in range(40):
                    v, _ = A.generate_attrs(pos, target, rng)
                    self.assertEqual(A.check_consistency(v, pos, target), [], (pos, target))

    def test_not_all_strikers_fast_or_same(self):
        rng = random.Random(2)
        sp = [A.generate_attrs("ST", 75, rng)[0][A.IDX["sprint_speed"]] for _ in range(400)]
        self.assertGreater(statistics.pstdev(sp), 7)
        self.assertLess(sum(1 for s in sp if s >= 85) / len(sp), 0.25)

    def test_position_shapes(self):
        rng = random.Random(3)
        cb = [A.generate_attrs("CB", 75, rng)[0] for _ in range(100)]
        st = [A.generate_attrs("ST", 75, rng)[0] for _ in range(100)]
        m = lambda L, n: statistics.mean(x[A.IDX[n]] for x in L)
        self.assertGreater(m(cb, "def_awareness"), m(st, "def_awareness") + 25)
        self.assertGreater(m(st, "finishing"), m(cb, "finishing") + 25)


class TestTalents(unittest.TestCase):
    def test_names_arabic_unique(self):
        rng = random.Random(4)
        used = set()
        names = [T.generate_youth(rng, used, 2026, 1, "Spain")["name"] for _ in range(3000)]
        self.assertEqual(len(set(names)), 3000)
        for n in names[:200]:
            first, fam = n.split(" ", 1)
            self.assertIn(first, FIRST)
            self.assertIn(fam, FAMILY)
            self.assertNotRegex(n, r"[A-Za-z0-9]")

    def test_rarity(self):
        rng = random.Random(5)
        used = set()
        N = 40000
        pots, tiers, growth = [], Counter(), Counter()
        for _ in range(N):
            y = T.generate_youth(rng, set(), 2026, 1, "England")
            pots.append(y["potential"])
            tiers[y["tier"]] += 1
            growth[y["growth"]] += 1
            self.assertTrue(28 <= y["ovr"] <= y["potential"])
        elite = sum(1 for p in pots if p >= 85) / N
        exc = sum(1 for p in pots if p >= 90) / N
        print(f"\n  youth potential>=85: {elite:.3%}  >=90: {exc:.3%}  mean pot {statistics.mean(pots):.1f}  tiers {dict(tiers)}")
        self.assertLess(elite, 0.012)
        self.assertLess(exc, 0.0025)
        self.assertGreater(elite, 0.001)
        self.assertGreater(growth[3] / N, 0.01)
        self.assertLess(growth[3] / N, 0.06)

    def test_no_rating_inflation_long_term(self):
        """Cohort of 20k youths developed to age 29 with normal conditions: 90+ must stay very rare."""
        rng = random.Random(6)
        peak = []
        for _ in range(20000):
            y = T.generate_youth(rng, set(), 2026, 1, "France")
            ovr, pot, age = y["ovr"], y["potential"], y["age"] if "age" in y else 2026 - int(y["birth_date"][:4])
            share = rng.uniform(0.0, 1.0)
            for a in range(age, 29):
                prev = ovr
                ovr = T.season_development(ovr, pot, a, y["growth"], share, rng.uniform(6.0, 7.5),
                                           rng.uniform(.3, .8), rng.randint(50, 90), rng.choice([0, 0, 0, 40]), 0.7, rng)
                self.assertLessEqual(abs(ovr - prev), 8)
                pot = T.update_potential(ovr, pot, a, share, rng)
            peak.append(ovr)
        top = sum(1 for o in peak if o >= 90) / len(peak)
        top85 = sum(1 for o in peak if o >= 85) / len(peak)
        print(f"\n  after development: >=85 {top85:.3%}, >=90 {top:.3%}, mean {statistics.mean(peak):.1f}")
        self.assertLess(top, 0.004)
        self.assertLess(top85, 0.02)

    def test_development_not_automatic(self):
        rng = random.Random(8)
        play = [T.season_development(60, 80, 18, 1, 0.9, 7.2, .6, 80, 0, .9, rng) for _ in range(400)]
        bench = [T.season_development(60, 80, 18, 1, 0.0, 5.8, .6, 40, 0, .3, rng) for _ in range(400)]
        self.assertGreater(statistics.mean(play), statistics.mean(bench) + 1.0)


class TestWorldAndCareers(unittest.TestCase):
    def test_world_scope(self):
        w = db.open_world(WORLD)
        self.assertEqual(w.execute("SELECT COUNT(*) FROM leagues").fetchone()[0], 10)
        self.assertEqual(w.execute("SELECT COUNT(*) FROM clubs").fetchone()[0], 198)
        self.assertEqual(w.execute("SELECT MAX(tier) FROM leagues").fetchone()[0], 2)
        self.assertEqual(w.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        for (pos, ovr, blob) in w.execute("SELECT pos,ovr,attrs FROM players LIMIT 500"):
            self.assertEqual(A.check_consistency(list(blob), pos, ovr), [])

    def test_multi_career_isolated_and_small(self):
        cm = CareerManager(os.path.join(TMP, "saves1"), WORLD)
        a, b = cm.create(1, "أ", seed=1), cm.create(30, "ب", seed=2)
        sizes = {c["id"]: c["size_kb"] for c in cm.list_careers()}
        world_kb = os.path.getsize(WORLD) // 1024
        print(f"\n  world.db {world_kb} KB | new career file {sizes[a]} KB (not a copy of the world)")
        self.assertLess(sizes[a], world_kb * 0.5)
        ca, cb = cm.open(a), cm.open(b)
        S.advance_matchday(ca)
        self.assertEqual(cb.execute("SELECT COUNT(*) FROM results").fetchone()[0], 0)
        self.assertGreater(ca.execute("SELECT COUNT(*) FROM results").fetchone()[0], 0)
        # world is read-only
        with self.assertRaises(sqlite3.OperationalError):
            ca.execute("UPDATE world.players SET ovr=99")
        ca.close(); cb.close()
        with self.assertRaises(ConfirmRequired):
            cm.delete(a)
        cm.delete(a, confirmed=True)
        self.assertEqual([c["id"] for c in cm.list_careers()], [b])

    def test_override_view_and_search(self):
        cm = CareerManager(os.path.join(TMP, "saves2"), WORLD)
        cid = cm.create(1, seed=3)
        con = cm.open(cid)
        pid = con.execute("SELECT id,name_ar,club_id FROM v_player WHERE club_id=1 LIMIT 1").fetchone()
        with con:
            con.execute("INSERT INTO player_state(player_id,club_id,ovr) VALUES(?,?,?)", (pid["id"], 2, 99))
        self.assertEqual(len(db.squad(con, 1)), 25)
        self.assertEqual(len(db.squad(con, 2)), 27)
        row = con.execute("SELECT club_id,ovr FROM v_player WHERE id=?", (pid["id"],)).fetchone()
        self.assertEqual((row[0], row[1]), (2, 99))
        base = db.open_world(WORLD).execute("SELECT ovr,club_id FROM players WHERE id=?", (pid["id"],)).fetchone()
        self.assertNotEqual(base[0], 99)  # base world untouched
        hits = db.search_players(con, pid["name_ar"].split()[0])
        self.assertTrue(any(h["id"] == pid["id"] for h in hits))
        plan = " ".join(r[3] for r in con.execute(
            "EXPLAIN QUERY PLAN SELECT id FROM v_player WHERE search >= 'a' AND search < 'b'"))
        self.assertIn("ix_players_search", plan)
        con.close()

    def test_backup_restore_after_corruption(self):
        cm = CareerManager(os.path.join(TMP, "saves3"), WORLD)
        cid = cm.create(5, seed=4)
        con = cm.open(cid)
        S.advance_matchday(con)
        cm.autosave(con, backup=True)
        n = con.execute("SELECT COUNT(*) FROM results").fetchone()[0]
        con.close()
        p = cm.path(cid)
        for ext in ("-wal", "-shm"):
            if os.path.exists(str(p) + ext):
                os.remove(str(p) + ext)
        with open(p, "r+b") as f:  # corrupt the file
            f.seek(0)
            f.write(b"\x00" * 4096)
        con = cm.open(cid)  # auto-restores from backup
        self.assertEqual(con.execute("SELECT COUNT(*) FROM results").fetchone()[0], n)
        con.close()


class TestMatch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cm = CareerManager(os.path.join(TMP, "saves4"), WORLD)
        cls.cid = cls.cm.create(1, seed=9)
        cls.con = cls.cm.open(cls.cid)

    def _teams(self, h, a):
        hl, hb = auto_lineup(db.squad(self.con, h))
        al, ab = auto_lineup(db.squad(self.con, a))
        return (dict(club_id=h, lineup=hl, bench=hb), dict(club_id=a, lineup=al, bench=ab))

    def test_consistency_many_matches(self):
        H, Aw = self._teams(1, 2)
        probs = []
        goals = []
        for seed in range(600):
            r = simulate_detailed(H, Aw, seed)
            p = validate_match(r, H, Aw)
            if p:
                probs.append((seed, p))
            goals.append(sum(r["score"]))
            rt = [x["rating"] for x in r["players"]]
            self.assertGreater(len(set(rt)), 5)  # ratings not constant
            self.assertTrue(all(3.0 <= x <= 10.0 for x in rt))
        print(f"\n  detailed matches: {len(goals)}, mean goals {statistics.mean(goals):.2f}, problems {len(probs)}")
        self.assertEqual(probs, [])
        self.assertTrue(2.3 <= statistics.mean(goals) <= 3.1)

    def test_determinism(self):
        H, Aw = self._teams(1, 2)
        self.assertEqual(simulate_detailed(H, Aw, 123)["events"], simulate_detailed(H, Aw, 123)["events"])

    def test_stronger_team_wins_more_but_upsets_happen(self):
        sq = {c: db.squad(self.con, c) for c in (1, 30)}
        strong = max(range(1, 21), key=lambda c: team_strength(db.squad(self.con, c))["ovr"])
        weak = min(range(1, 21), key=lambda c: team_strength(db.squad(self.con, c))["ovr"])
        sh, sw = team_strength(db.squad(self.con, strong)), team_strength(db.squad(self.con, weak))
        rng = random.Random(1)
        w = d = l = 0
        for _ in range(4000):
            g1, g2 = simulate_fast(sh, sw, rng)
            w, d, l = w + (g1 > g2), d + (g1 == g2), l + (g1 < g2)
        print(f"\n  strongest(ovr {sh['ovr']:.1f}) vs weakest(ovr {sw['ovr']:.1f}) home: W{w} D{d} L{l}")
        self.assertGreater(w, l * 2)
        self.assertGreater(l, 40)  # upsets exist

    def test_red_card_and_subs_logic_over_many_seeds(self):
        H, Aw = self._teams(3, 4)
        reds = subs = 0
        for seed in range(400):
            r = simulate_detailed(H, Aw, seed)
            reds += sum(1 for e in r["events"] if e["type"] == "rc")
            subs += sum(1 for e in r["events"] if e["type"] == "sub")
        self.assertGreater(reds, 0)
        self.assertGreater(subs, 400)


class TestInteractiveMatch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cm = CareerManager(os.path.join(TMP, "saves6"), WORLD)
        cls.con = cls.cm.open(cls.cm.create(1, seed=21))
        hl, hb = auto_lineup(db.squad(cls.con, 1))
        al, ab = auto_lineup(db.squad(cls.con, 2))
        cls.H = dict(club_id=1, lineup=hl, bench=hb)
        cls.A = dict(club_id=2, lineup=al, bench=ab)

    def test_pause_resume_equals_one_shot(self):
        for seed in range(40):
            one = MatchSession(self.H, self.A, seed).finish()
            m = MatchSession(self.H, self.A, seed)
            m.advance(until=30)
            self.assertEqual(m.minute, 30)
            m.advance(until=45)
            self.assertTrue(m.at_half_time)
            m.advance(stop_on_event=True)
            m.advance(until=70)
            two = m.finish()
            self.assertEqual(one["events"], two["events"])
            self.assertEqual(one["score"], two["score"])

    def test_manual_substitution_rules(self):
        m = MatchSession(self.H, self.A, 5, auto=(False, True))
        m.advance(until=60)
        on = [x for x in m.S[0].on if x["slot"] != "GK"]
        out = on[0]["p"]["id"]
        bench = [b for b in m.S[0].bench if b["pos"] != "GK"]
        self.assertEqual(m.substitute(0, out, bench[0]["id"]), "ok")
        self.assertEqual(m.substitute(0, out, bench[1]["id"]), "out_player_not_on_pitch")  # already off
        self.assertEqual(m.substitute(0, on[1]["p"]["id"], bench[0]["id"]), "in_player_not_on_bench")  # already on
        n = 1
        for k in range(1, 6):
            cur = [x for x in m.S[0].on if x["slot"] != "GK"][0]["p"]["id"]
            r = m.substitute(0, cur, bench[k]["id"]) if k < len(bench) else "no_substitutions_left"
            n += r == "ok"
        self.assertLessEqual(n, 5)
        self.assertEqual(m.substitute(0, [x for x in m.S[0].on if x["slot"] != "GK"][0]["p"]["id"],
                                      bench[-1]["id"]) in ("no_substitutions_left", "in_player_not_on_bench"), True)
        res = m.finish()
        self.assertEqual(validate_match(res, self.H, self.A), [])

    def test_tactics_change_outcomes(self):
        def run(ment):
            gf = ga = 0
            for seed in range(500):
                m = MatchSession(self.H, self.A, seed, auto=(False, False))
                m.set_tactics(0, mentality=ment)
                r = m.finish()
                gf += r["score"][0]
                ga += r["score"][1]
            return gf / 500, ga / 500
        att, bal, dfn = run("attacking"), run("balanced"), run("defensive")
        print(f"\n  goals for/against  attacking {att}  balanced {bal}  defensive {dfn}")
        self.assertGreater(att[0], bal[0])
        self.assertGreater(bal[0], dfn[0])
        self.assertLess(dfn[1], att[1])

    def test_formation_and_instruction_midgame(self):
        m = MatchSession(self.H, self.A, 9, auto=(False, True))
        m.advance(until=45)
        self.assertEqual(m.set_formation(0, "4-2-3-1"), "ok")
        slots = sorted(x["slot"] for x in m.S[0].on)
        self.assertEqual(slots, sorted(["GK", "LB", "CB", "CB", "RB", "CDM", "CDM", "LW", "CAM", "RW", "ST"]))
        pid = [x for x in m.S[0].on if x["slot"] == "RB"][0]["p"]["id"]
        self.assertEqual(m.set_instruction(0, pid, "forward"), "ok")
        self.assertEqual(m.set_instruction(0, 999999, "forward"), "invalid")
        res = m.finish()
        self.assertEqual(validate_match(res, self.H, self.A), [])
        self.assertTrue(any(i[2] == "formation" for i in res["interventions"]))

    def test_comeback_example_from_spec(self):
        """Trailing at 65': sub + attacking must raise the chance of scoring afterwards."""
        base = changed = n = 0
        for seed in range(3000):
            m = MatchSession(self.H, self.A, seed, auto=(False, True))
            m.advance(until=65)
            if m.score()[0] >= m.score()[1]:
                continue
            n += 1
            m2 = MatchSession(self.H, self.A, seed, auto=(False, True))
            m2.advance(until=65)
            g0 = m.score()[0]
            base += m.finish()["score"][0] - g0
            m2.set_tactics(0, mentality="attacking")
            bench = [b for b in m2.S[0].bench if b["pos"] == "ST"] or [b for b in m2.S[0].bench if b["pos"] != "GK"]
            m2.substitute(0, [x for x in m2.S[0].on if x["slot"] in ("CB", "CDM", "CM")][0]["p"]["id"], bench[0]["id"])
            changed += m2.finish()["score"][0] - g0
        print(f"\n  trailing at 65' in {n} matches: goals after, unchanged {base}, attacking+sub {changed}")
        self.assertGreater(n, 100)
        self.assertGreater(changed, base)


class TestSeason(unittest.TestCase):
    def test_full_season_tables_and_promotion(self):
        cm = CareerManager(os.path.join(TMP, "saves5"), WORLD)
        cid = cm.create(7, seed=11)
        con = cm.open(cid)
        import time
        t0 = time.time()
        days = 0
        while S.advance_matchday(con):
            days += 1
        dt = time.time() - t0
        print(f"\n  full season (3758 matches, all 10 leagues): {days} matchdays in {dt:.1f}s on this sandbox")
        self.assertEqual(con.execute("SELECT COUNT(*) FROM results").fetchone()[0], 3758)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM fixtures WHERE played=0").fetchone()[0], 0)
        # pair uniqueness: each ordered pair once
        dup = con.execute("SELECT COUNT(*) FROM (SELECT home_id,away_id,COUNT(*) c FROM fixtures "
                          "GROUP BY home_id,away_id HAVING c>1)").fetchone()[0]
        self.assertEqual(dup, 0)
        # points arithmetic per league
        for lid in range(1, 11):
            rows = S.table(con, 2026, lid)
            n = len(rows)
            self.assertTrue(all(r["p"] == 2 * (n - 1) for r in rows))
            self.assertEqual(sum(r["w"] for r in rows), sum(r["l"] for r in rows))
            self.assertEqual(sum(r["gf"] for r in rows), sum(r["ga"] for r in rows))
            self.assertEqual(sum(r["pts"] for r in rows), 3 * sum(r["w"] for r in rows) + sum(r["d"] for r in rows) * 1)
            res_pts = con.execute("SELECT SUM(CASE WHEN hg=ag THEN 2 ELSE 3 END) FROM results r JOIN fixtures f "
                                  "ON f.id=r.fixture_id WHERE f.league_id=?", (lid,)).fetchone()[0]
            self.assertEqual(sum(r["pts"] for r in rows), res_pts)
        # recompute standings from results and compare (incremental == full recompute)
        full = con.execute("""SELECT f.league_id l, t.c c, SUM(t.pts) pts FROM (
              SELECT f.id fid, f.home_id c, CASE WHEN hg>ag THEN 3 WHEN hg=ag THEN 1 ELSE 0 END pts FROM results r JOIN fixtures f ON f.id=r.fixture_id
              UNION ALL SELECT f.id, f.away_id, CASE WHEN ag>hg THEN 3 WHEN hg=ag THEN 1 ELSE 0 END FROM results r JOIN fixtures f ON f.id=r.fixture_id) t
              JOIN fixtures f ON f.id=t.fid GROUP BY f.league_id, t.c""").fetchall()
        inc = {(r["league_id"], r["club_id"]): r["pts"] for r in con.execute("SELECT * FROM standings WHERE season=2026")}
        for r in full:
            self.assertEqual(inc[(r["l"], r["c"])], r["pts"])
        # promotion / relegation
        before = {r["club_id"]: r["league_id"] for r in con.execute("SELECT * FROM club_season WHERE season=2026")}
        seen = []
        ns = S.end_season(con, on_season_stats=lambda rows: seen.extend(rows))
        self.assertEqual(ns, 2027)
        self.assertGreater(len(seen), 1000)  # development hook got last season's stats
        # club archive: one row for the user's club with achievements (names stored as text)
        arch = S.club_archive(con)
        self.assertEqual(len(arch), 1)
        a = arch[0]
        self.assertEqual((a["season"], a["club_id"]), (2026, 7))
        self.assertEqual(a["p"], a["w"] + a["d"] + a["l"])
        self.assertTrue(1 <= a["position"] <= a["league_size"])
        self.assertTrue(a["top_scorer"] and a["top_scorer_goals"] > 0)
        self.assertEqual(a["manager_name"], "المدرب")
        # no player history is kept after rollover
        self.assertEqual(con.execute("SELECT COUNT(*) FROM player_season_stats WHERE season<2027").fetchone()[0], 0)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM match_events").fetchone()[0], 0)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM match_player_stats").fetchone()[0], 0)
        after = {r["club_id"]: r["league_id"] for r in con.execute("SELECT * FROM club_season WHERE season=2027")}
        moved = [c for c in before if before[c] != after[c]]
        self.assertEqual(len(moved), 5 * 3 * 2)
        for lid in range(1, 11):
            self.assertEqual(sum(1 for c in after if after[c] == lid), sum(1 for c in before if before[c] == lid))
        self.assertEqual(con.execute("SELECT COUNT(*) FROM fixtures WHERE season=2027").fetchone()[0], 3758)
        con.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
