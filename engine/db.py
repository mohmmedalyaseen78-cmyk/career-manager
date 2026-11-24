"""Connections: world (read-only, shared) attached to a career file (read/write, small)."""
import sqlite3
from pathlib import Path

from .names_ar import normalize

_COLS = ("id,name,name_ar,search,birth_date,nationality,pos,pos2,foot,height,weight,weak_foot,skill_moves,"
         "shirt,growth").split(",")


def _uri(path, mode):
    u = Path(path).resolve().as_uri()
    return f"{u}?mode={mode}" + ("&immutable=1" if mode == "ro" else "")


def open_world(world_path):
    con = sqlite3.connect(_uri(world_path, "ro"), uri=True)
    con.row_factory = sqlite3.Row
    return con


_VIEW = """
CREATE TEMP VIEW v_player AS
SELECT p.id, p.name, p.name_ar, p.search, p.birth_date, p.nationality, p.pos, p.pos2, p.foot, p.height, p.weight,
  NULLIF(COALESCE(s.club_id, p.club_id), 0) AS club_id, COALESCE(s.ovr, p.ovr) AS ovr,
  COALESCE(s.potential, p.potential) AS potential, p.growth, COALESCE(s.attrs, p.attrs) AS attrs,
  COALESCE(s.wage, p.wage) AS wage, COALESCE(s.value, p.value) AS value,
  COALESCE(s.contract_end, p.contract_end) AS contract_end, COALESCE(s.form, 70) AS form,
  COALESCE(s.fitness, 100) AS fitness, COALESCE(s.morale, 70) AS morale, COALESCE(s.injury_days, 0) AS injury_days,
  COALESCE(s.status, 0) AS status, 0 AS generated
FROM world.players p LEFT JOIN main.player_state s ON s.player_id = p.id
UNION ALL
SELECT g.id, g.name, g.name_ar, g.search, g.birth_date, g.nationality, g.pos, g.pos2, g.foot, g.height, g.weight,
  NULLIF(COALESCE(s.club_id, g.club_id), 0), COALESCE(s.ovr, g.ovr), COALESCE(s.potential, g.potential), g.growth,
  COALESCE(s.attrs, g.attrs), COALESCE(s.wage, g.wage), COALESCE(s.value, g.value),
  COALESCE(s.contract_end, g.contract_end), COALESCE(s.form, 70), COALESCE(s.fitness, g.fitness),
  COALESCE(s.morale, g.morale), COALESCE(s.injury_days, 0), COALESCE(s.status, 0), 1
FROM main.gen_players g LEFT JOIN main.player_state s ON s.player_id = g.id
"""


def open_career_db(career_path, world_path, create=False):
    con = sqlite3.connect(_uri(career_path, "rwc" if create else "rw"), uri=True)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA cache_size=-6144")  # 6 MB page cache
    con.execute("PRAGMA temp_store=MEMORY")
    con.execute("ATTACH DATABASE ? AS world", (_uri(world_path, "ro"),))
    con.execute(_VIEW)
    return con


def search_players(con, text, pos=None, limit=50, offset=0):
    """Prefix search on normalised name using the index (no full scan)."""
    t = normalize(text)
    sql = ("SELECT id,name_ar,pos,ovr,potential,club_id,birth_date FROM v_player "
           "WHERE search >= ? AND search < ?")
    args = [t, t + "￿"]
    if pos:
        sql += " AND pos = ?"
        args.append(pos)
    sql += " ORDER BY ovr DESC LIMIT ? OFFSET ?"
    return con.execute(sql, args + [limit, offset]).fetchall()


_SQUAD_COLS = ("{a}.id,{a}.name,{a}.name_ar,{a}.birth_date,{a}.nationality,{a}.pos,{a}.pos2,{a}.foot,{a}.height,"
               "{a}.weight,{a}.shirt")


def squad(con, club_id):
    """Players of a club using indexes only: base roster minus moved-away, plus moved-in, plus generated."""
    base = """
SELECT p.id,p.name_ar,p.birth_date,p.pos,p.pos2,COALESCE(s.ovr,p.ovr) ovr,COALESCE(s.potential,p.potential) potential,
 COALESCE(s.attrs,p.attrs) attrs,COALESCE(s.fitness,100) fitness,COALESCE(s.form,70) form,COALESCE(s.morale,70) morale,
 COALESCE(s.injury_days,0) injury_days,COALESCE(s.status,0) status,COALESCE(s.wage,p.wage) wage,
 COALESCE(s.value,p.value) value,COALESCE(s.contract_end,p.contract_end) contract_end
FROM world.players p LEFT JOIN main.player_state s ON s.player_id=p.id
WHERE p.club_id=:c AND (s.club_id IS NULL OR s.club_id=:c)
UNION ALL
SELECT p.id,p.name_ar,p.birth_date,p.pos,p.pos2,COALESCE(s.ovr,p.ovr),COALESCE(s.potential,p.potential),
 COALESCE(s.attrs,p.attrs),COALESCE(s.fitness,100),COALESCE(s.form,70),COALESCE(s.morale,70),
 COALESCE(s.injury_days,0),COALESCE(s.status,0),COALESCE(s.wage,p.wage),COALESCE(s.value,p.value),
 COALESCE(s.contract_end,p.contract_end)
FROM main.player_state s JOIN world.players p ON p.id=s.player_id WHERE s.club_id=:c AND p.club_id<>:c
UNION ALL
SELECT g.id,g.name_ar,g.birth_date,g.pos,g.pos2,COALESCE(s.ovr,g.ovr),COALESCE(s.potential,g.potential),
 COALESCE(s.attrs,g.attrs),COALESCE(s.fitness,g.fitness),COALESCE(s.form,70),COALESCE(s.morale,g.morale),
 COALESCE(s.injury_days,0),COALESCE(s.status,0),COALESCE(s.wage,g.wage),COALESCE(s.value,g.value),
 COALESCE(s.contract_end,g.contract_end)
FROM main.gen_players g LEFT JOIN main.player_state s ON s.player_id=g.id
WHERE g.club_id=:c AND (s.club_id IS NULL OR s.club_id=:c)
"""
    return [dict(r) for r in con.execute(base, {"c": club_id})]
