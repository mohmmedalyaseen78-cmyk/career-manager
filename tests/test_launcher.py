import os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestLauncherWorld(unittest.TestCase):
    def test_prepare_synthetic_then_real(self):
        tmp = tempfile.mkdtemp()
        os.environ["LOCALAPPDATA"] = tmp
        import importlib
        from app import launcher
        importlib.reload(launcher)
        self.assertTrue(launcher.APPDATA.startswith(tmp))
        w, kind = launcher.prepare_world()
        self.assertEqual(kind, "synthetic")
        self.assertTrue(os.path.getsize(w) > 100_000)
        # real import path: a tiny generator-format CSV in data/
        data = os.path.join(tmp, "CareerManager", "data")
        os.makedirs(data)
        import csv
        rows = [dict(country="England", league="Premier League", division="Premier League", club="Test United", player_name=f"Player {i}",
                     position=["GK", "DF", "MF", "FW"][i % 4], OVR=60 + i % 20, OVR_Status="ESTIMATED", ovr_collected_at="2026-11-24") for i in range(25)]
        with open(os.path.join(data, "players_2026-27_BASE.csv"), "w", newline="", encoding="utf-8-sig") as f:
            wr = csv.DictWriter(f, fieldnames=list(rows[0])); wr.writeheader(); wr.writerows(rows)
        try:
            w2, kind2 = launcher.prepare_world()
            self.assertEqual(kind2, "real")
        except Exception as e:  # column names of the real generator may differ; surface it
            self.fail(f"importer rejected generator-format CSV: {e}")


if __name__ == "__main__":
    unittest.main()
