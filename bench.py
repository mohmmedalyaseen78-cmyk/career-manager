"""Benchmark for the target laptop. Writes bench_report.txt next to the program.
Builds a synthetic 198-club world, then measures the things the spec lists. Safe: writes only inside its own folder."""
import os
import sys
import tempfile
import time
import statistics

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import db, season as S, resources
from engine.career import CareerManager
from engine.match import auto_lineup, simulate_detailed
from engine.worldgen import build_world


def ms(f, n=1):
    t = []
    for _ in range(n):
        a = time.perf_counter()
        f()
        t.append((time.perf_counter() - a) * 1000)
    return statistics.median(t), max(t)


def main():
    base = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
    work = tempfile.mkdtemp(prefix="grafeco_bench_", dir=base)
    lines = []
    out = lambda s: (print(s), lines.append(s))
    out(f"python {sys.version.split()[0]} | cpus {resources.logical_cpus()} | free RAM MB {resources.available_ram_mb()}")
    out(f"RSS at start: {resources.process_rss_mb()} MB")
    t = time.perf_counter()
    wp = os.path.join(work, "world.db")
    build_world(wp, seed=1)
    out(f"build synthetic world (198 clubs, 4,950 players): {time.perf_counter() - t:.2f}s, "
        f"{os.path.getsize(wp) // 1024} KB")
    cm = CareerManager(os.path.join(work, "saves"), wp)
    t = time.perf_counter()
    cid = cm.create(1, "bench", seed=5)
    out(f"create career: {(time.perf_counter() - t) * 1000:.0f} ms, file {cm.list_careers()[0]['size_kb']} KB")
    con = cm.open(cid)
    out(f"RSS after open career (idle): {resources.process_rss_mb()} MB")
    m, mx = ms(lambda: db.squad(con, 1), 30)
    out(f"open squad (25 players): median {m:.1f} ms, max {mx:.1f} ms")
    m, mx = ms(lambda: db.search_players(con, "محمد"), 30)
    out(f"player search by name prefix: median {m:.1f} ms, max {mx:.1f} ms")
    m, mx = ms(lambda: con.execute("SELECT id,name_ar,pos,ovr,potential FROM v_player ORDER BY ovr DESC LIMIT 50 "
                                   "OFFSET 1000").fetchall(), 10)
    out(f"sorted page of 50 players from ~5k: median {m:.1f} ms, max {mx:.1f} ms")
    m, mx = ms(lambda: S.table(con, 2026, 1), 30)
    out(f"league table: median {m:.1f} ms")
    sq = db.squad(con, 1)
    sq2 = db.squad(con, 2)
    hl, hb = auto_lineup(sq)
    al, ab = auto_lineup(sq2)
    m, mx = ms(lambda: simulate_detailed(dict(club_id=1, lineup=hl, bench=hb), dict(club_id=2, lineup=al, bench=ab),
                                        9), 20)
    out(f"detailed match simulation: median {m:.1f} ms, max {mx:.1f} ms")
    times = []
    for _ in range(10):
        a = time.perf_counter()
        S.advance_matchday(con)
        times.append((time.perf_counter() - a) * 1000)
    out(f"advance one matchday (~100 matches, 10 leagues): median {statistics.median(times):.0f} ms, max {max(times):.0f} ms")
    out(f"RSS peak-ish after matchdays: {resources.process_rss_mb()} MB")
    a = time.perf_counter()
    cm.autosave(con, backup=True)
    out(f"autosave + backup: {(time.perf_counter() - a) * 1000:.0f} ms")
    a = time.perf_counter()
    n = 0
    while S.advance_matchday(con):
        n += 1
    out(f"rest of season ({n} more matchdays): {time.perf_counter() - a:.1f}s total")
    out(f"RSS after full season: {resources.process_rss_mb()} MB")
    con.close()
    rpt = os.path.join(base, "bench_report.txt")
    with open(rpt, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\nSaved:", rpt)


if __name__ == "__main__":
    main()
    if getattr(sys, "frozen", False):
        input("\nPress Enter to close...")
