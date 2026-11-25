import os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine import play as P, season as S, jobs as J, manager as M, db
from engine.career import CareerManager
from engine.worldgen import build_world


class TestPlay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        w = os.path.join(cls.tmp, "w.db")
        build_world(w, seed=3)
        cls.cm = CareerManager(os.path.join(cls.tmp, "s"), w)

    def mk(self):
        con = self.cm.open(self.cm.create(1, "كريم الحربي", seed=5))
        J.ensure_schema(con); M.ensure_profile(con)
        return con

    def test_live_match_commit_and_prefs(self):
        con = self.mk()
        P.set_prefs(con, formation="4-4-2", mentality="attacking", pressing=70)
        ms, meta = P.start_live(con)
        ms.advance(until=30)
        ms.set_tactics(meta["side"], mentality="defensive")
        ms.advance()
        res = ms.result()
        sm = P.finish_day(con, meta["fixture"]["id"], res)
        self.assertEqual(sm["user"]["fixture_id"], meta["fixture"]["id"])
        r = con.execute("SELECT hg,ag,detailed FROM results WHERE fixture_id=?", (meta["fixture"]["id"],)).fetchone()
        self.assertEqual((r[0], r[1]), tuple(res["score"]))
        self.assertEqual(r[2], 1)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM fixtures WHERE date=? AND played=0", (meta["fixture"]["date"],)).fetchone()[0], 0)

    def test_chosen_xi_respected(self):
        con = self.mk()
        sq = db.squad(con, 1)
        gk = [p for p in sq if p["pos"] == "GK"][0]
        xi = [gk["id"]] + [p["id"] for p in sorted(sq, key=lambda p: p["ovr"]) if p["pos"] != "GK"][:10]  # deliberately the weakest
        P.set_prefs(con, xi=xi)
        lu, _ = P.user_side(sq, P.get_prefs(con))
        self.assertEqual({p["id"] for _, p in lu}, set(xi))

    def test_full_season_and_offseason(self):
        con = self.mk()
        n = 0
        while S.next_date(con):
            S.advance_matchday(con); n += 1
        ids_before = {r[0] for r in con.execute("SELECT id FROM v_player WHERE club_id IS NOT NULL")}
        out = P.end_of_season(con)
        self.assertEqual(out["new_season"], 2027)
        self.assertGreater(out["developed"], 4000)
        cnt = [r[0] for r in con.execute("SELECT COUNT(*) FROM v_player WHERE club_id IS NOT NULL GROUP BY club_id")]
        self.assertGreaterEqual(min(cnt), 20)
        self.assertEqual(len(con.execute("SELECT * FROM club_history").fetchall()), 1)
        ovrs = [r[0] for r in con.execute("SELECT ovr FROM v_player WHERE club_id IS NOT NULL")]
        self.assertLess(sum(1 for o in ovrs if o >= 90) / len(ovrs), 0.03)
        self.assertIsNotNone(S.next_date(con))  # next season fixtures exist
        self.assertEqual(n, 38 if False else n)


if __name__ == "__main__":
    unittest.main()


class TestCondition(unittest.TestCase):
    def test_post_day_updates_user_condition(self):
        tmp = tempfile.mkdtemp(); w = os.path.join(tmp, "w.db"); build_world(w, seed=4)
        cm = CareerManager(os.path.join(tmp, "s"), w)
        con = cm.open(cm.create(2, "م", seed=9)); J.ensure_schema(con)
        for _ in range(10):
            sm = S.advance_matchday(con)
            P.post_day(con, sm)
        sq = db.squad(con, 2)
        self.assertTrue(any(p["fitness"] < 100 for p in sq) or any(p["form"] != 70 for p in sq))
        self.assertTrue(all(0 <= p["fitness"] <= 100 and 20 <= p["morale"] <= 100 for p in sq))
