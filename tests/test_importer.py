import csv
import os
import random
import shutil
import sys
import tempfile
import unittest
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine import attrs as A, db
from engine.importer import import_world
from engine.worldgen import LEAGUES

TMP = tempfile.mkdtemp(prefix="grafeco_imp_")
CSV = os.path.join(TMP, "base.csv")
OUT = os.path.join(TMP, "world.db")
HEAD = ["country", "league", "division", "club", "player_name", "player_qid", "position_group", "position", "age",
        "birth_date", "nationality", "citizenship", "country_of_citizenship", "jersey_number", "shirt_number", "foot",
        "height", "OVR", "OVR_Status", "OVR_Source", "ovr_collected_at"]


def make_csv():
    """TEST FIXTURE ONLY: fictional clubs/players in the generator's output format."""
    rng = random.Random(3)
    rows = []
    for code, name, _ar, country, tier, n in LEAGUES:
        for c in range(n):
            club = f"Fixture {name} Club {c:02d}"
            size = 9 if (c == 0 and tier == 2) else rng.randint(23, 30)   # one short club per 2nd tier
            groups = ["GK"] * 3 + ["DF"] * 8 + ["MF"] * 9 + ["FW"] * 6
            for k in range(size):
                g = groups[k % len(groups)]
                est = rng.random() < 0.7
                ovr = int(rng.gauss(72 if tier == 1 else 64, 6))
                rows.append(dict(country=country, league=name, division=tier, club=club, player_name=f"Fx {club[-2:]} Éric{k}",
                                 player_qid=f"Q{rng.randint(1, 10**8)}", position_group=g, position=g,
                                 age=rng.randint(17, 36), birth_date="" if k % 5 else f"{2026 - rng.randint(18, 35)}-04-12",
                                 OVR=ovr, OVR_Status="ESTIMATED" if est else "EA_OFFICIAL_BASE_ITEM",
                                 OVR_Source="x", ovr_collected_at="2026-11-23"))
    with open(CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=HEAD, restval="")
        w.writeheader()
        w.writerows(rows)


def setUpModule():
    make_csv()


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


class TestImporter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rep = import_world(CSV, OUT, ea_status="TEST")
        cls.w = db.open_world(OUT)

    def test_structure_and_counts(self):
        self.assertEqual(self.rep["clubs"], 198)
        self.assertEqual(self.w.execute("SELECT COUNT(*) FROM clubs").fetchone()[0], 198)
        for lid, (_c, name, _a, _co, _t, n) in enumerate(LEAGUES, 1):
            self.assertEqual(self.w.execute("SELECT n_clubs FROM leagues WHERE id=?", (lid,)).fetchone()[0], n)
        self.assertEqual(self.w.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_every_player_consistent_and_positions_valid(self):
        n = 0
        for r in self.w.execute("SELECT pos,ovr,attrs,potential FROM players"):
            self.assertIn(r["pos"], A.POSITIONS)
            self.assertEqual(A.check_consistency(list(r["attrs"]), r["pos"], r["ovr"]), [])
            self.assertGreaterEqual(r["potential"], r["ovr"])
            n += 1
        self.assertEqual(n, self.rep["players"])

    def test_provenance_flags_not_hidden(self):
        c = Counter(r[0] for r in self.w.execute("SELECT q_ovr FROM players WHERE source_id<>3"))
        self.assertEqual(c[1], self.rep["sourced_ovr"] - 0)
        self.assertEqual(self.w.execute("SELECT COUNT(*) FROM players WHERE q_attrs=1").fetchone()[0], 0)  # attrs never 'sourced'
        self.assertEqual(self.w.execute("SELECT COUNT(*) FROM players WHERE q_pot=1").fetchone()[0], 0)
        self.assertGreater(self.rep["estimated_ovr"], 0)
        self.assertGreater(self.rep["sourced_ovr"], 0)

    def test_short_clubs_are_topped_up_and_flagged(self):
        self.assertEqual(len(self.rep["clubs_filled"]), 5)
        self.assertGreater(self.rep["filled"], 0)
        self.assertEqual(self.w.execute("SELECT COUNT(*) FROM players WHERE q_core=3").fetchone()[0], self.rep["filled"])
        for (cid, cnt) in self.w.execute("SELECT club_id, COUNT(*) FROM players GROUP BY club_id"):
            self.assertGreaterEqual(cnt, 20)

    def test_squads_have_playable_position_coverage(self):
        for (cid,) in self.w.execute("SELECT id FROM clubs"):
            pos = Counter(r[0] for r in self.w.execute("SELECT pos FROM players WHERE club_id=?", (cid,)))
            self.assertGreaterEqual(pos["GK"], 2)
            self.assertGreaterEqual(pos["CB"], 2)
            self.assertGreaterEqual(pos["ST"] + pos["LW"] + pos["RW"], 3)

    def test_deterministic_and_accent_search(self):
        out2 = os.path.join(TMP, "w2.db")
        import_world(CSV, out2, ea_status="TEST")
        a = self.w.execute("SELECT SUM(ovr*id), SUM(LENGTH(attrs)) FROM players").fetchone()[:]
        b = db.open_world(out2).execute("SELECT SUM(ovr*id), SUM(LENGTH(attrs)) FROM players").fetchone()[:]
        self.assertEqual(tuple(a), tuple(b))
        from engine.names_ar import normalize
        self.assertEqual(normalize("Éric5"), "eric5")
        self.assertGreater(self.w.execute("SELECT COUNT(*) FROM players WHERE search >= ? AND search < ?",
                                          ("fx", "fx￿")).fetchone()[0], 100)

    def test_world_works_with_game_engine(self):
        from engine.career import CareerManager
        from engine import season as S
        cm = CareerManager(os.path.join(TMP, "saves"), OUT)
        con = cm.open(cm.create(1, "م", seed=1))
        self.assertTrue(S.advance_matchday(con)["played"] > 0)
        con.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
