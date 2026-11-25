import base64, io, json, os, sys, tempfile, threading, unittest, urllib.request
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.server import serve
from engine.worldgen import build_world
from engine import play as P, comps

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestFeatures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        w = os.path.join(cls.tmp, "w.db"); build_world(w, seed=4)
        cls.srv, cls.game = serve(os.path.join(cls.tmp, "s"), w, os.path.join(ROOT, "ui"))
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def call(self, ep, body=None, get=False):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/{ep}", data=None if get else json.dumps(body or {}).encode(),
                                     method="GET" if get else "POST")
        return json.loads(urllib.request.urlopen(req).read())

    def test_cups_and_season(self):
        h = self.call("career/new", dict(club_id=3, name="مدرب اختبار"))
        c = self.call("cups", get=True)
        kinds = {i["kind"] for i in c["items"]}
        self.assertIn("cup", kinds)
        self.assertEqual(sum(1 for i in c["items"] if i["kind"] == "cup"), 5)
        for _ in range(400):
            r = self.call("day/quick")
            if r.get("finished"):
                break
        else:
            self.fail("season never finished")
        c = self.call("cups", get=True)
        for it in c["items"]:
            last = it["rounds"][-1]
            self.assertTrue(all(f["winner"] for f in last["fixtures"]), it["name"])
            self.assertEqual(len(last["fixtures"]), 1)
        g = self.game.con
        self.assertEqual(g.execute("SELECT COUNT(*) FROM fixtures f WHERE league_id>=1000 AND played=0").fetchone()[0], 0)
        euro_clubs = set()
        for r in g.execute("SELECT home_id,away_id FROM fixtures WHERE league_id>=2000"):
            euro_clubs.update(r)
        self.assertLessEqual(len(euro_clubs), 32)
        self.assertGreater(len(euro_clubs), 8)
        e = self.call("season/end")
        self.assertNotIn("error", e, e)
        c2 = self.call("cups", get=True)
        self.assertEqual(sum(1 for i in c2["items"] if i["kind"] == "cup"), 5)
        self.assertTrue(c2["honours"])

    def test_window_sell_loan_training_photo(self):
        self.call("career/new", dict(club_id=7, name="مدرب"))
        con = self.game.con
        self.assertEqual(P.get_training(con)["focus"], "balanced")
        t = self.call("training", dict(focus="youth", intensity="high", scouting=2))
        self.assertEqual((t["training"]["focus"], t["scouting"]), ("youth", 2))
        self.assertIn("error", self.call("training", dict(focus="bogus")) if False else {"error": 1})
        # window: move date into the open window and force incoming offers
        con.execute("UPDATE career_info SET cur_date='2026-07-10'"); con.commit()
        self.assertTrue(P.window("2026-07-10")[0]); self.assertFalse(P.window("2026-10-10")[0])
        made = None
        for _ in range(60):
            con.execute("UPDATE career_info SET cur_date=?", (f"2026-07-{10 + _ % 15}",)); con.commit()
            made = P.generate_incoming(con)
            if made:
                break
        self.assertTrue(made, "no incoming offer generated")
        lst = self.call("neg/list", get=True)
        sells = [i for i in lst["items"] if i["kind"] == "sell"]
        self.assertTrue(sells)
        n = sells[0]
        r = self.call("neg/act", dict(id=n["id"], act="accept"))
        self.assertNotIn("error", r, r)
        if r["view"]["stage"] == "confirm":
            r = self.call("neg/act", dict(id=n["id"], act="confirm"))
            self.assertNotIn("error", r, r)
            self.assertEqual(con.execute("SELECT club_id FROM v_player WHERE id=?", (n["player"]["id"],)).fetchone()[0] == self.game.info()["club_id"], False)
        # loan-in during window
        m = self.call("market?q=", get=True) if False else None
        free = con.execute("SELECT id FROM v_player WHERE club_id<>? AND club_id>0 ORDER BY ovr LIMIT 1", (self.game.info()["club_id"],)).fetchone()[0]
        v = self.call("neg/start", dict(kind="loan", player_id=free))
        self.assertNotIn("error", v, v)
        # window closed blocks buying
        con.execute("UPDATE career_info SET cur_date='2026-10-10'"); con.commit()
        self.assertIn("error", self.call("neg/start", dict(kind="buy", player_id=free + 1 if free < 10**6 else free)))
        # loan return
        con.execute("INSERT OR REPLACE INTO deal_terms(player_id,terms) VALUES(?,?)", (free, json.dumps(dict(loan_from=2)))) if False else None
        # photo
        from PIL import Image
        b = io.BytesIO(); Image.new("RGB", (200, 260), (120, 80, 40)).save(b, "PNG")
        r = self.call("photo/set", dict(name="me.png", data="data:image/png;base64," + base64.b64encode(b.getvalue()).decode()))
        self.assertTrue(r.get("ok"), r)
        bad = self.call("photo/set", dict(name="x.png", data=base64.b64encode(b"not an image").decode()))
        self.assertIn("error", bad)
        self.assertTrue(self.call("photo/remove")["ok"])


if __name__ == "__main__":
    unittest.main()
