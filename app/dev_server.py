"""Developer helper: run the game server on a synthetic world (used for UI tests and screenshots)."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.server import serve
from engine.worldgen import build_world
port = int(sys.argv[1]) if len(sys.argv) > 1 else 8766
tmp = tempfile.mkdtemp(); w = os.path.join(tmp, "w.db"); build_world(w, seed=7)
srv, g = serve(os.path.join(tmp, "s"), w, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ui"), port)
print("ready", port, flush=True)
srv.serve_forever()
