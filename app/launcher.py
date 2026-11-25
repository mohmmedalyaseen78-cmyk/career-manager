"""Career Manager launcher (Windows): prepares the world database, starts the local server, opens the game window."""
import ctypes
import glob
import os
import shutil
import subprocess
import sys
import threading
import time
import traceback

FROZEN = getattr(sys, "frozen", False)
EXE_DIR = os.path.dirname(sys.executable) if FROZEN else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES_DIR = getattr(sys, "_MEIPASS", EXE_DIR)
sys.path.insert(0, RES_DIR)

APPDATA = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "CareerManager")
LOG = os.path.join(APPDATA, "launcher.log")


def log(msg):
    try:
        os.makedirs(APPDATA, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except OSError:
        pass


def fatal(msg):
    log("FATAL " + msg)
    try:
        ctypes.windll.user32.MessageBoxW(0, msg + f"\n\nسجل الأخطاء: {LOG}", "Career Manager", 0x10)
    except Exception:
        print(msg, file=sys.stderr)
    sys.exit(1)


def find_players_csv():
    for base in (os.path.join(EXE_DIR, "data"), os.path.join(APPDATA, "data")):
        hits = glob.glob(os.path.join(base, "**", "players_2026-27_BASE.csv"), recursive=True)
        if hits:
            return sorted(hits)[0]
    return None


def prepare_world():
    """Real world from the generator CSV when present, else the clearly-labelled synthetic test world."""
    from engine import importer
    from engine.worldgen import build_world
    csv_path = find_players_csv()
    os.makedirs(APPDATA, exist_ok=True)
    if csv_path:
        stamp = f"{os.path.getsize(csv_path)}_{int(os.path.getmtime(csv_path))}"
        world = os.path.join(APPDATA, f"world_real_{stamp}.db")
        if not os.path.exists(world):
            log(f"importing {csv_path}")
            for old in glob.glob(os.path.join(APPDATA, "world_real_*.db")):
                pass  # keep older worlds: careers created on them keep their own file
            rep = importer.import_world(csv_path, world, source_note=f"imported from {os.path.basename(csv_path)}")
            log(f"import report: {rep}")
        return world, "real"
    world = os.path.join(APPDATA, "world_synthetic.db")
    if not os.path.exists(world):
        build_world(world, seed=2026)
    return world, "synthetic"


def find_edge():
    for root in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if root:
            p = os.path.join(root, "Microsoft", "Edge", "Application", "msedge.exe")
            if os.path.exists(p):
                return p
    return shutil.which("msedge")


def selftest():
    """Headless check used by CI on the frozen exe: serve, create a career, play a live match and a quick day, then exit 0/1."""
    import json
    import urllib.request
    from app.server import serve
    world, kind = prepare_world()
    srv, game = serve(os.path.join(APPDATA, "selftest_saves"), world, os.path.join(RES_DIR, "ui"), 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def call(ep, body=None):
        req = urllib.request.Request(f"{base}/api/{ep}", data=json.dumps(body or {}).encode() if body is not None else None)
        return json.loads(urllib.request.urlopen(req, timeout=60).read())
    boot = call("boot")
    assert boot["clubs"], "no clubs"
    h = call("career/new", dict(club_id=boot["clubs"][0]["id"], name="اختبار آلي"))
    assert "error" not in h, h
    m = call("match/start", {})
    assert "error" not in m, m
    call("match/advance", dict(mode="end"))
    out = call("match/commit", {})
    assert "error" not in out, out
    assert "error" not in call("day/quick", {})
    html = urllib.request.urlopen(base + "/", timeout=30).read().decode()
    assert "Career Manager" in html
    game.close()
    log(f"SELFTEST OK world={kind} clubs={len(boot['clubs'])}")
    return 0


def main():
    if "--selftest" in sys.argv:
        try:
            code = selftest()
        except Exception:
            log("SELFTEST FAILED\n" + traceback.format_exc())
            code = 1
        sys.stdout.flush()
        os._exit(code)
    try:
        from app.server import serve
        world, kind = prepare_world()
        saves = os.path.join(APPDATA, "saves")
        ui = os.path.join(RES_DIR, "ui")
        srv, game = serve(saves, world, ui, 0)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{port}/"
        log(f"serving {kind} world on {url}")
        edge = find_edge()
        if edge:
            prof = os.path.join(APPDATA, "edge-profile")
            args = [edge, f"--app={url}", "--window-size=1366,768", f"--user-data-dir={prof}", "--no-first-run",
                    "--disable-extensions", "--disable-sync", "--disable-background-networking",
                    "--disable-features=Translate,msEdgeSidebarV2", "--lang=ar"]
            if os.environ.get("CM_GPU") != "1":
                args.append("--disable-gpu")  # target hardware has an old integrated GPU: software rendering is steadier
            proc = subprocess.Popen(args)
            proc.wait()
            time.sleep(1.5)  # a second window/instance may hand over; the beacon on page close also quits
            with game.lock:
                game.close()
            os._exit(0)
        else:
            import webbrowser
            log("Edge not found: using default browser")
            webbrowser.open(url)
            while True:  # /api/bye (page close) terminates the process
                time.sleep(3600)
    except SystemExit:
        raise
    except Exception:
        fatal("تعذّر تشغيل اللعبة:\n" + traceback.format_exc()[-900:])


if __name__ == "__main__":
    main()
