import json, os, sys, tempfile, threading, unittest, urllib.request
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.server import serve
from engine.worldgen import build_world

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        w = os.path.join(cls.tmp, "w.db"); build_world(w, seed=3)
        cls.srv, cls.game = serve(os.path.join(cls.tmp, "s"), w, os.path.join(ROOT, "ui"))
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def call(self, ep, body=None, get=False):
        url = f"http://127.0.0.1:{self.port}/api/{ep}"
        req = urllib.request.Request(url, data=None if get else json.dumps(body or {}).encode(), method="GET" if get else "POST")
        return json.loads(urllib.request.urlopen(req).read())

    def test_full_flow(self):
        boot = self.call("boot", get=True)
        self.assertEqual(len(boot["clubs"]), 198)
        h = self.call("career/new", dict(club_id=5, name="سامي القحطاني"))
        self.assertNotIn("error", h, h)
        self.assertEqual(h["manager"]["name"], "سامي القحطاني")
        sq = self.call("squad", get=True)
        self.assertGreaterEqual(len(sq["players"]), 22)
        self.assertEqual(self.call("prefs", dict(formation="4-2-3-1", mentality="attacking"))["formation"], "4-2-3-1")
        # live match
        m = self.call("match/start")
        self.assertNotIn("error", m, m)
        m = self.call("match/advance", dict(mode="half"))
        self.assertGreaterEqual(m["minute"], 45)
        s0 = m["sides"][m["side"]]
        r = self.call("match/act", dict(act="sub", out=[x for x in s0["on"] if x["pos"] != "GK"][0]["id"], **{"in": s0["bench"][0]["id"]}) if s0["bench"] else dict(act="tactics", mentality="balanced"))
        self.assertNotIn("error", r, r)
        out = self.call("match/commit")
        self.assertNotIn("error", out, out)
        self.assertEqual(out["home"]["last"]["round"], 1)
        # quick days and market / negotiation
        for _ in range(3):
            self.assertNotIn("error", self.call("day/quick"))
        mk = self.call("market?grp=FW&age=30&ovr=60", get=True)
        self.assertTrue(mk["players"])
        p = mk["players"][0]
        nv = self.call("neg/start", dict(kind="buy", player_id=p["id"]))
        self.assertNotIn("error", nv, nv)
        self.assertIn("stated_ask", nv)
        r = self.call("neg/act", dict(id=nv["id"], act="club", offer=dict(immediate=min(int(nv["stated_ask"] * 1.3), nv["budget"]))))
        self.assertIn(r["resp"]["response"], ("accept", "counter", "reject", "collapse", "invalid"))
        for ep in ("league", "calendar", "offers", "archive", "neg/list"):
            self.assertNotIn("error", self.call(ep, get=True) if ep in ("league", "calendar", "offers", "archive") else self.call(ep), ep)

    def test_full_season_via_api(self):
        self.call("career/new", dict(club_id=7, name="خالد المطيري"))
        n = 0
        while True:
            r = self.call("day/quick")
            self.assertNotIn("error", r, r)
            if r.get("finished"):
                break
            n += 1
            self.assertLess(n, 60)
        self.assertGreaterEqual(n, 30)
        h = self.call("home", get=True)
        self.assertTrue(h["finished"])
        self.assertTrue(any(t["kind"] == "season" for t in h["tasks"]))
        e = self.call("season/end")
        self.assertNotIn("error", e, e)
        self.assertEqual(e["home"]["season_year"], 2027)
        self.assertFalse(e["home"]["finished"])
        arch = self.call("archive", get=True)
        self.assertEqual(len(arch["items"]), 1)
        sq = self.call("squad", get=True)
        self.assertGreaterEqual(len(sq["players"]), 20)
        for _ in range(5):
            self.assertNotIn("error", self.call("day/quick"))

    def test_ui_served(self):
        html = urllib.request.urlopen(f"http://127.0.0.1:{self.port}/").read().decode()
        self.assertIn("Career Manager", html)
        css = urllib.request.urlopen(f"http://127.0.0.1:{self.port}/css/app.css")
        self.assertIn("text/css", css.headers["Content-Type"])


if __name__ == "__main__":
    unittest.main()
