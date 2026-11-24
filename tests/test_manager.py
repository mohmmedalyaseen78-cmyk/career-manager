import io
import os
import re
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PIL import Image

from engine import manager as M
from engine.career import CareerManager
from engine.worldgen import build_world

TMP = tempfile.mkdtemp(prefix="grafeco_mgr_")
WORLD = os.path.join(TMP, "world.db")
ENGINE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine")


def setUpModule():
    build_world(WORLD, seed=7)


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def img_bytes(fmt, color=(200, 30, 30), size=(300, 200), mode="RGB", exif=False):
    im = Image.new(mode, size, color)
    buf = io.BytesIO()
    kw = {}
    if exif and fmt == "JPEG":
        e = Image.Exif()
        e[0x010F] = "SecretCameraMaker"
        kw["exif"] = e
    im.save(buf, fmt, **kw)
    return buf.getvalue()


class TestName(unittest.TestCase):
    def test_valid_names_kept_intact(self):
        for n in ["أحمد الشريف", "John O'Neil-Smith", "Marco أحمد", "José María", "  spaced   out  name "]:
            out = M.validate_name(n)
            self.assertEqual(out, " ".join(n.split()))

    def test_rejects(self):
        bad = ["", "   ", "a" * 41, "ab‮cd", "x\x00y", "A1", "<b>", "{manager}", "ab‏cd", "😀", "...", "a\nb"]
        for b in bad:
            with self.assertRaises(M.ManagerError, msg=repr(b)):
                M.validate_name(b)
        with self.assertRaises(M.ManagerError):
            M.validate_name(None)

    def test_mtext(self):
        cm = CareerManager(os.path.join(TMP, "s_mt"), WORLD)
        con = cm.open(cm.create(1, "x", seed=1))
        M.set_name(con, "ليث المدرب")
        self.assertEqual(M.mtext(con, "{manager} يقود الفريق. المدرب المنافس بقي كما هو {rival}", rival="Rossi"),
                         "ليث المدرب يقود الفريق. المدرب المنافس بقي كما هو Rossi")
        self.assertNotIn("{manager}", M.mtext(con, "{manager}{manager}"))
        con.close()


class TestIdentityPerCareer(unittest.TestCase):
    def test_two_careers_do_not_mix_and_persist(self):
        saves = os.path.join(TMP, "s_two")
        cm = CareerManager(saves, WORLD)
        a, b = cm.create(1, "tmp", seed=1), cm.create(30, "tmp", seed=2)
        ca, cb = cm.open(a), cm.open(b)
        M.set_name(ca, "أحمد الشريف")
        M.set_name(cb, "Marco Rossi")
        ra, rb = (200, 20, 20), (20, 20, 200)
        M.set_photo(ca, saves, img_bytes("PNG", ra), declared_name="a.png")
        M.set_photo(cb, saves, img_bytes("JPEG", rb), declared_name="b.jpg")
        pa, pb = M.photo_paths(ca, saves), M.photo_paths(cb, saves)
        self.assertTrue(pa["has_photo"] and pb["has_photo"])
        self.assertNotEqual(os.path.dirname(pa["photo"]), os.path.dirname(pb["photo"]))
        ca.close(); cb.close()
        # reopen = "after closing and reopening the game"
        ca, cb = cm.open(a), cm.open(b)
        self.assertEqual(M.get_name(ca), "أحمد الشريف")
        self.assertEqual(M.get_name(cb), "Marco Rossi")
        pa, pb = M.photo_paths(ca, saves), M.photo_paths(cb, saves)
        ia, ib = Image.open(pa["photo"]).getpixel((10, 10)), Image.open(pb["photo"]).getpixel((10, 10))
        self.assertGreater(ia[0], 150)   # career A photo is the red one
        self.assertGreater(ib[2], 150)   # career B photo is the blue one
        # deleting A's assets leaves B untouched
        M.delete_assets(saves, a)
        self.assertFalse(os.path.exists(M.assets_dir(saves, a)))
        self.assertTrue(M.photo_paths(cb, saves)["has_photo"])
        self.assertEqual(M.photo_paths(ca, saves)["has_photo"], False)  # files gone -> safe fallback to default
        ca.close(); cb.close()

    def test_no_photo_works_and_remove(self):
        saves = os.path.join(TMP, "s_nop")
        cm = CareerManager(saves, WORLD)
        con = cm.open(cm.create(2, "n", seed=3))
        self.assertFalse(M.photo_paths(con, saves)["has_photo"])
        self.assertEqual(M.get_profile(con)["has_photo"], 0)
        v0 = M.get_profile(con)["photo_version"]
        M.set_photo(con, saves, img_bytes("PNG"), declared_name="p.png")
        self.assertTrue(M.photo_paths(con, saves)["has_photo"])
        M.remove_photo(con, saves)
        pp = M.photo_paths(con, saves)
        self.assertFalse(pp["has_photo"])
        self.assertIsNone(pp["photo"])
        self.assertGreater(pp["version"], v0)  # UI knows to refresh
        con.close()

    def test_replace_updates_version(self):
        saves = os.path.join(TMP, "s_rep")
        cm = CareerManager(saves, WORLD)
        con = cm.open(cm.create(2, "n", seed=3))
        M.set_photo(con, saves, img_bytes("PNG", (255, 0, 0)), declared_name="1.png")
        v1 = M.photo_paths(con, saves)["version"]
        M.set_photo(con, saves, img_bytes("PNG", (0, 255, 0)), declared_name="2.png")
        pp = M.photo_paths(con, saves)
        self.assertGreater(pp["version"], v1)
        self.assertGreater(Image.open(pp["thumb"]).getpixel((5, 5))[1], 200)
        con.close()


class TestPhotoValidation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.saves = os.path.join(TMP, "s_val")
        cm = CareerManager(cls.saves, WORLD)
        cls.con = cm.open(cm.create(3, "v", seed=5))

    def rejects(self, data, **kw):
        before = M.photo_paths(self.con, self.saves)
        with self.assertRaises(M.ManagerError):
            M.set_photo(self.con, self.saves, data, **kw)
        self.assertEqual(M.photo_paths(self.con, self.saves), before)  # a rejected file changes nothing

    def test_not_an_image(self):
        self.rejects(b"hello world, definitely not an image", declared_name="me.jpg")
        self.rejects(b"", declared_name="me.jpg")

    def test_truncated_corrupt(self):
        good = img_bytes("JPEG")
        self.rejects(good[:60] + b"\x00" * 40, declared_name="me.jpg")

    def test_misleading_extension(self):
        self.rejects(img_bytes("PNG"), declared_name="me.jpg")
        self.rejects(img_bytes("PNG"), declared_name="me.exe")
        self.rejects(img_bytes("PNG"), declared_name="me")

    def test_too_large_and_pixels(self):
        self.rejects(img_bytes("PNG"), declared_name="a.png", max_bytes=100)
        self.rejects(img_bytes("PNG", size=(200, 200)), declared_name="a.png", max_pixels=5000)

    def test_path_input_checks_size_and_missing(self):
        p = os.path.join(TMP, "big.png")
        open(p, "wb").write(img_bytes("PNG"))
        with self.assertRaises(M.ManagerError):
            M.set_photo(self.con, self.saves, p, max_bytes=50)
        with self.assertRaises(M.ManagerError):
            M.set_photo(self.con, self.saves, os.path.join(TMP, "nope.png"))
        M.set_photo(self.con, self.saves, p)  # fine, name taken from path
        self.assertTrue(M.photo_paths(self.con, self.saves)["has_photo"])
        M.remove_photo(self.con, self.saves)

    def test_exif_stripped_webp_png_alpha_and_crop_ratio(self):
        M.set_photo(self.con, self.saves, img_bytes("JPEG", exif=True, size=(500, 300)), declared_name="x.jpg")
        pp = M.photo_paths(self.con, self.saves)
        im = Image.open(pp["photo"])
        self.assertEqual(len(im.getexif()), 0)
        self.assertAlmostEqual(im.size[0] / im.size[1], 0.8, delta=0.01)
        self.assertEqual(Image.open(pp["thumb"]).size, M.THUMB_SIZE)
        M.set_photo(self.con, self.saves, img_bytes("WEBP"), declared_name="x.webp")
        M.set_photo(self.con, self.saves, img_bytes("PNG", (255, 0, 0, 0), mode="RGBA"), declared_name="x.png")
        # fully transparent -> flattened onto the dark surface colour, not black/garbage
        px = Image.open(M.photo_paths(self.con, self.saves)["photo"]).getpixel((5, 5))
        self.assertLess(abs(px[0] - M.BG[0]), 12)
        # explicit crop box, forced to 4:5
        M.set_photo(self.con, self.saves, img_bytes("PNG", size=(400, 400)), crop=(0.1, 0.1, 0.9, 0.5), declared_name="c.png")
        im = Image.open(M.photo_paths(self.con, self.saves)["photo"])
        self.assertAlmostEqual(im.size[0] / im.size[1], 0.8, delta=0.01)
        with self.assertRaises(M.ManagerError):
            M.set_photo(self.con, self.saves, img_bytes("PNG"), crop=(0.9, 0.1, 0.1, 0.5), declared_name="c.png")

    def test_assets_path_safety(self):
        for bad in ("../x", "a/b", "", "a" * 70):
            with self.assertRaises(M.ManagerError):
                M.assets_dir(self.saves, bad)
            with self.assertRaises(M.ManagerError):
                M.delete_assets(self.saves, bad)

    def test_only_inside_career_assets_folder(self):
        M.set_photo(self.con, self.saves, img_bytes("PNG"), declared_name="z.png")
        cid = M._career_id(self.con)
        files = [os.path.join(r, f) for r, _, fs in os.walk(self.saves) for f in fs if f.endswith((".jpg", ".tmp"))]
        self.assertTrue(files)
        for f in files:
            self.assertEqual(os.path.basename(os.path.dirname(f)), f"{cid}_assets")


class TestReputationAndPrivacy(unittest.TestCase):
    def test_reputation_bounds_and_no_history_table(self):
        cm = CareerManager(os.path.join(TMP, "s_rep2"), WORLD)
        con = cm.open(cm.create(1, "r", seed=9))
        p = M.ensure_profile(con)
        self.assertTrue(1 <= p["reputation"] <= 100)
        self.assertEqual(M.set_reputation(con, 500), 100)
        self.assertEqual(M.set_reputation(con, -5), 1)
        self.assertEqual(M.add_reputation(con, 7), 8)
        tables = [r[0].lower() for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        self.assertFalse([t for t in tables if "manager_hist" in t or "coach_hist" in t or "career_hist" in t])
        self.assertEqual(con.execute("SELECT COUNT(*) FROM manager_profile").fetchone()[0], 1)
        con.close()

    def test_no_network_code_in_engine_modules(self):
        banned = re.compile(r"\b(import|from)\s+(socket|requests|urllib|http|httpx|aiohttp|ftplib|smtplib|websocket)", re.I)
        for f in ("manager.py", "negotiation.py", "jobs.py"):
            src = open(os.path.join(ENGINE_DIR, f), encoding="utf-8").read()
            self.assertIsNone(banned.search(src), f)
            for token in ("urlopen", "socket.", "requests."):
                self.assertNotIn(token, src, f)

    def test_photo_flow_works_with_network_disabled(self):
        import socket
        real = socket.socket

        class Boom:
            def __init__(self, *a, **k):
                raise AssertionError("network access attempted")
        socket.socket = Boom
        try:
            saves = os.path.join(TMP, "s_off")
            cm = CareerManager(saves, WORLD)
            con = cm.open(cm.create(1, "o", seed=1))
            M.set_photo(con, saves, img_bytes("PNG"), declared_name="o.png")
            M.set_name(con, "Offline Coach")
            con.close()
        finally:
            socket.socket = real


if __name__ == "__main__":
    unittest.main(verbosity=2)
