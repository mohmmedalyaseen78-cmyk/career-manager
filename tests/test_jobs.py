import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine import jobs as J, manager as M, season as S
from engine.career import CareerManager
from engine.worldgen import build_world

TMP = tempfile.mkdtemp(prefix="grafeco_jobs_")
WORLD = os.path.join(TMP, "world.db")


def setUpModule():
    build_world(WORLD, seed=7)


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def fresh(name, club=1, seed=5):
    cm = CareerManager(os.path.join(TMP, name), WORLD)
    con = cm.open(cm.create(club, "مدرب", seed=seed))
    J.ensure_schema(con)
    return cm, con


class TestOffers(unittest.TestCase):
    def test_offers_scale_with_reputation(self):
        def count(rep):
            tot = 0
            for seed in range(25):
                _, con = fresh(f"s{rep}_{seed}", club=30, seed=seed)
                M.ensure_profile(con)
                M.set_reputation(con, rep)
                tot += len(J.generate_offers(con))
                con.close()
            return tot
        low, high = count(15), count(85)
        print(f"\n  offers over 25 careers: reputation 15 -> {low}, reputation 85 -> {high}")
        self.assertGreater(high, low)

    def test_offer_clubs_match_reputation_and_cover_all_clubs_over_a_career(self):
        _, con = fresh("reach")
        reach_low = set(J.eligible_clubs(con, 10))
        reach_high = set(J.eligible_clubs(con, 100))
        everything = set()
        for rep in range(1, 101, 3):
            everything |= set(J.eligible_clubs(con, rep))
        self.assertEqual(len(everything), 198)  # every club is reachable at some point of a career
        reps = {r[0]: r[1] for r in con.execute("SELECT id,reputation FROM world.clubs")}
        self.assertLess(max(reps[c] for c in reach_low), max(reps[c] for c in reach_high) + 1)
        con.close()

    def test_idempotent_same_day_and_deterministic(self):
        _, a = fresh("d1", seed=9)
        _, b = fresh("d2", seed=9)
        M.ensure_profile(a)
        M.ensure_profile(b)
        M.set_reputation(a, 80)
        M.set_reputation(b, 80)
        first = J.generate_offers(a)
        self.assertEqual(J.generate_offers(a), [])
        self.assertEqual([o["club_id"] for o in J.pending_offers(a)] if first else [],
                         [o["club_id"] for o in (J.generate_offers(b) and J.pending_offers(b))] if first else [])
        a.close(); b.close()


class TestAcceptDecline(unittest.TestCase):
    def _with_offer(self, name):
        cm, con = fresh(name, club=1, seed=3)
        M.ensure_profile(con)
        M.set_reputation(con, 90)
        for d in range(60):
            ids = J.generate_offers(con)
            if ids:
                return cm, con, J.pending_offers(con)[0]
            S.advance_matchday(con)
        self.fail("no offer generated")

    def test_compare_shows_both_clubs(self):
        _, con, o = self._with_offer("cmp")
        c = J.compare(con, o["id"])
        self.assertEqual(c["current"]["club_id"], 1)
        self.assertEqual(c["offered"]["club_id"], o["club_id"])
        for k in ("reputation", "transfer_budget", "strength"):
            self.assertIn(k, c["deltas"])
        self.assertIn("key", c["objective_offered"])
        con.close()

    def test_decline_then_cannot_accept(self):
        _, con, o = self._with_offer("dec")
        J.decline_offer(con, o["id"])
        with self.assertRaises(ValueError):
            J.accept_offer(con, o["id"])
        con.close()

    def test_accept_moves_club_same_career_and_appoints_replacement(self):
        cm, con, o = self._with_offer("acc")
        cid = con.execute("SELECT career_id FROM career_info").fetchone()[0]
        old_mgr = J.get_club_manager(con, 1)["name"]
        rep = M.get_profile(con)["reputation"]
        res = J.accept_offer(con, o["id"])
        info = con.execute("SELECT career_id,club_id,manager_name FROM career_info").fetchone()
        self.assertEqual(info["career_id"], cid)            # SAME career
        self.assertEqual(info["club_id"], o["club_id"])
        self.assertEqual(info["manager_name"], "مدرب")      # identity kept
        self.assertEqual(M.get_profile(con)["reputation"], rep)
        self.assertNotEqual(J.get_club_manager(con, 1)["name"], old_mgr)   # replacement appointed at the old club
        self.assertIsNone(con.execute("SELECT 1 FROM club_manager WHERE club_id=?", (o["club_id"],)).fetchone())
        self.assertEqual(res["new_club"], o["club_id"])
        con.close()

    def test_world_keeps_running_after_move(self):
        cm, con, o = self._with_offer("run")
        J.accept_offer(con, o["id"])
        before = con.execute("SELECT COUNT(*) FROM results").fetchone()[0]
        for _ in range(3):
            S.advance_matchday(con)
        self.assertGreater(con.execute("SELECT COUNT(*) FROM results").fetchone()[0], before)
        con.close()
        con2 = cm.open(cm.list_careers()[0]["id"])  # reopen: still the new club
        self.assertEqual(con2.execute("SELECT club_id FROM career_info").fetchone()[0], o["club_id"])
        con2.close()

    def test_two_moves_between_any_clubs_possible(self):
        cm, con, o = self._with_offer("two")
        J.accept_offer(con, o["id"])
        M.set_reputation(con, 95)
        for _ in range(60):
            if J.generate_offers(con):
                break
            S.advance_matchday(con)
        offers = J.pending_offers(con)
        if offers:
            J.accept_offer(con, offers[0]["id"])
            self.assertEqual(con.execute("SELECT club_id FROM career_info").fetchone()[0], offers[0]["club_id"])
        con.close()


class TestNoSacking(unittest.TestCase):
    def test_no_dismissal_mechanic_exists(self):
        import engine.jobs as j, engine.manager as m, engine.negotiation as n
        words = ("sack", "dismiss", "fire_manager", "fired", "terminate_manager")
        for mod in (j, m, n):
            for name in dir(mod):
                self.assertFalse(any(w in name.lower() for w in words), f"{mod.__name__}.{name}")
        src = open(os.path.join(os.path.dirname(j.__file__), "jobs.py"), encoding="utf-8").read().lower()
        self.assertNotIn("def sack", src)

    def test_confidence_is_indicator_only_levels(self):
        _, con = fresh("conf")
        c = J.board_confidence(con)
        self.assertIn(c["level"], J.LEVELS)
        self.assertEqual(con.execute("SELECT club_id FROM career_info").fetchone()[0], 1)  # nothing happened to the user
        con.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
