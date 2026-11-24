"""Multi-career save management. Each career = its own small file; the world DB is shared and read-only."""
import json
import os
import shutil
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from .db import open_career_db, open_world
from .fixtures import round_robin, round_date, season_start
from .schema import CAREER_SQL, CAREER_SCHEMA_VERSION

EXT = ".gcareer"
MAX_BACKUPS = 3


class ConfirmRequired(Exception):
    pass


class WorldMismatch(Exception):
    pass


def _now():
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


class CareerManager:
    def __init__(self, saves_dir, world_path):
        self.dir = Path(saves_dir)
        self.bak = self.dir / "backups"
        self.world_path = Path(world_path)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.bak.mkdir(exist_ok=True)

    def path(self, cid):
        return self.dir / f"{cid}{EXT}"

    def _world_meta(self):
        w = open_world(self.world_path)
        try:
            return {r["key"]: r["value"] for r in w.execute("SELECT key,value FROM meta")}
        finally:
            w.close()

    # ---------- list ----------
    def list_careers(self):
        out = []
        for f in sorted(self.dir.glob(f"*{EXT}")):
            try:
                c = sqlite3.connect(f"{f.resolve().as_uri()}?mode=ro", uri=True)
                r = c.execute("SELECT career_id,club_name,manager_name,season,cur_date,last_saved FROM career_info"
                              ).fetchone()
                c.close()
                if r:
                    out.append(dict(id=r[0], club=r[1], manager=r[2], season=f"{r[3]}/{(r[3] + 1) % 100:02d}",
                                    date=r[4], last_saved=r[5], size_kb=f.stat().st_size // 1024))
            except sqlite3.Error:
                out.append(dict(id=f.stem, club="?", manager="?", season="?", date="", last_saved="",
                                size_kb=f.stat().st_size // 1024, damaged=True))
        out.sort(key=lambda d: d["last_saved"], reverse=True)
        return out

    # ---------- create ----------
    def create(self, club_id, manager_name="المدرب", seed=None, settings=None):
        cid = uuid.uuid4().hex[:12]
        p = self.path(cid)
        if p.exists():  # never overwrite another career
            raise FileExistsError(p)
        wm = self._world_meta()
        season = int(wm["season"])
        seed = seed if seed is not None else uuid.uuid4().int & 0x7FFFFFFF
        w = open_world(self.world_path)
        club = w.execute("SELECT id,name_ar,name FROM clubs WHERE id=?", (club_id,)).fetchone()
        if not club:
            raise ValueError("unknown club")
        clubs = w.execute("SELECT id,league_id FROM clubs ORDER BY id").fetchall()
        w.close()
        con = open_career_db(p, self.world_path, create=True)
        try:
            with con:
                con.executescript(CAREER_SQL)
                con.execute("INSERT INTO meta VALUES('schema_version',?)", (str(CAREER_SCHEMA_VERSION),))
                con.execute("INSERT INTO career_info VALUES(1,?,?,?,?,?,?,?,?,?,?,?)",
                            (cid, wm["world_id"], club_id, club["name_ar"] or club["name"], manager_name, season,
                             season_start(season).isoformat(), seed, _now(), _now(), json.dumps(settings or {})))
                con.executemany("INSERT INTO club_season VALUES(?,?,?)", [(c["id"], season, c["league_id"])
                                                                          for c in clubs])
                self._make_fixtures(con, season, clubs)
        finally:
            con.close()
        return cid

    @staticmethod
    def _make_fixtures(con, season, clubs):
        by_league = {}
        for c in clubs:
            by_league.setdefault(c["league_id"], []).append(c["id"])
        rows, st = [], []
        for lid, ids in by_league.items():
            for r, rnd in enumerate(round_robin(ids)):
                d = round_date(season, r)
                rows += [(season, lid, "league", r + 1, d, h, a) for h, a in rnd]
            st += [(season, lid, c) for c in ids]
        con.executemany("INSERT INTO fixtures(season,league_id,comp,round,date,home_id,away_id) VALUES(?,?,?,?,?,?,?)",
                        rows)
        con.executemany("INSERT INTO standings(season,league_id,club_id) VALUES(?,?,?)", st)

    # ---------- open / save ----------
    def open(self, cid):
        p = self.path(cid)
        if not p.exists():
            raise FileNotFoundError(cid)
        if not self._quick_ok(p):
            self.restore_latest_backup(cid)
        con = open_career_db(p, self.world_path)
        info = con.execute("SELECT world_id FROM career_info").fetchone()
        if info["world_id"] != self._world_meta()["world_id"]:
            con.close()
            raise WorldMismatch("career was created with another world database")
        return con

    @staticmethod
    def _quick_ok(p):
        try:
            c = sqlite3.connect(f"{p.resolve().as_uri()}?mode=ro", uri=True)
            ok = c.execute("PRAGMA quick_check").fetchone()[0] == "ok"
            c.close()
            return ok
        except sqlite3.Error:
            return False

    def autosave(self, con, backup=False):
        """Safe-point save: stamp, checkpoint WAL, optional rotating backup."""
        with con:
            con.execute("UPDATE career_info SET last_saved=?", (_now(),))
        con.execute("PRAGMA wal_checkpoint(PASSIVE)")
        if backup:
            self.backup_now(con)

    def backup_now(self, con):
        cid = con.execute("SELECT career_id FROM career_info").fetchone()[0]
        for i in range(MAX_BACKUPS - 1, 0, -1):
            a, b = self.bak / f"{cid}.{i}.bak", self.bak / f"{cid}.{i + 1}.bak"
            if a.exists():
                os.replace(a, b)
        dst = sqlite3.connect(self.bak / f"{cid}.1.bak")
        con.execute("PRAGMA wal_checkpoint(FULL)")
        con.backup(dst, pages=256)  # includes main schema only (attached world is not copied)
        dst.close()

    def restore_latest_backup(self, cid):
        for i in range(1, MAX_BACKUPS + 1):
            b = self.bak / f"{cid}.{i}.bak"
            if b.exists() and self._quick_ok(b):
                for ext in ("-wal", "-shm"):
                    try:
                        os.remove(str(self.path(cid)) + ext)
                    except FileNotFoundError:
                        pass
                shutil.copyfile(b, self.path(cid))
                return i
        raise RuntimeError("no valid backup")

    # ---------- delete ----------
    def delete(self, cid, confirmed=False):
        if not confirmed:
            raise ConfirmRequired("deleting a career needs explicit confirmation")
        for f in [self.path(cid), Path(str(self.path(cid)) + "-wal"), Path(str(self.path(cid)) + "-shm")] + \
                 list(self.bak.glob(f"{cid}.*.bak")):
            try:
                f.unlink()
            except FileNotFoundError:
                pass
