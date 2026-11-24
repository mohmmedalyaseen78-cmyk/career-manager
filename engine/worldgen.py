"""Builds a SYNTHETIC test world (fictional clubs/players, flagged Q_SYNTHETIC) with the real schema.
The real-data pipeline writes the same schema; this one exists for development, tests and benchmarks.
It never contains real players."""
import math
import os
import random
import sqlite3
from datetime import date

from . import attrs as A
from . import talents as T
from .names_ar import normalize, pick_unique_name
from .schema import WORLD_SCHEMA_VERSION, WORLD_SQL, Q_SYNTHETIC

LEAGUES = [
    ("ENG1", "Premier League", "الدوري الإنجليزي الممتاز", "England", 1, 20),
    ("ENG2", "Championship", "دوري الدرجة الأولى الإنجليزي", "England", 2, 24),
    ("ESP1", "LaLiga", "الدوري الإسباني", "Spain", 1, 20),
    ("ESP2", "Segunda División", "الدرجة الثانية الإسبانية", "Spain", 2, 22),
    ("GER1", "Bundesliga", "الدوري الألماني", "Germany", 1, 18),
    ("GER2", "2. Bundesliga", "الدرجة الثانية الألمانية", "Germany", 2, 18),
    ("ITA1", "Serie A", "الدوري الإيطالي", "Italy", 1, 20),
    ("ITA2", "Serie B", "الدرجة الثانية الإيطالية", "Italy", 2, 20),
    ("FRA1", "Ligue 1", "الدوري الفرنسي", "France", 1, 18),
    ("FRA2", "Ligue 2", "الدرجة الثانية الفرنسية", "France", 2, 18),
]
SQUAD_PLAN = (["GK"] * 3 + ["CB"] * 4 + ["LB"] * 2 + ["RB"] * 2 + ["CDM"] * 2 + ["CM"] * 3 + ["CAM"] * 2 +
              ["LW"] * 2 + ["RW"] * 2 + ["ST"] * 4)


def build_world(path, seed=2026, season=2026):
    if os.path.exists(path):
        os.remove(path)
    rng = random.Random(seed)
    con = sqlite3.connect(path)
    con.executescript(WORLD_SQL)
    con.execute("INSERT INTO sources(id,name,url,accessed,license,note) VALUES(1,'GRAFECO synthetic generator',"
                "NULL,'2026-11-22','n/a','Fictional test data. Not real clubs or players.')")
    meta = {"schema_version": str(WORLD_SCHEMA_VERSION), "season": str(season), "world_id": f"synthetic-{seed}",
            "data_cutoff": "synthetic", "kind": "SYNTHETIC_TEST_WORLD"}
    con.executemany("INSERT INTO meta VALUES(?,?)", meta.items())
    used = set()
    club_id = pid = 0
    for lid, (code, name, name_ar, country, tier, n) in enumerate(LEAGUES, 1):
        con.execute("INSERT INTO leagues VALUES(?,?,?,?,?,?,?)", (lid, code, name, name_ar, country, tier, n))
        for k in range(n):
            club_id += 1
            rep = int(rng.uniform(58, 92) if tier == 1 else rng.uniform(32, 60))
            con.execute("INSERT INTO clubs VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (club_id, lid, f"Test FC {club_id:03d}", f"نادي تجريبي {club_id}", f"T{club_id:03d}",
                         f"ملعب {club_id}", rep, rep * 400_000, rep * 60_000, Q_SYNTHETIC))
            mean = 50 + rep * 0.30
            rows = []
            for shirt, pos in enumerate(SQUAD_PLAN, 1):
                pid += 1
                age = int(min(38, max(17, rng.gauss(25.5, 4.2))))
                ovr = int(max(40, min(93, rng.gauss(mean + (2 if shirt <= 14 else -4), 5.5))))
                pot = ovr if age >= 26 else min(97, ovr + max(0, int(rng.gauss((26 - age) * 1.1, 2.5))))
                attrs, _ = A.generate_attrs(pos, ovr, rng)
                sec = [p for p in T.ADJ[pos] if A.ovr_at(attrs, p) >= ovr - 4][:2]
                nm = pick_unique_name(rng, used)
                h, w = T._height_weight(pos, age, rng)
                val = T.market_value(ovr, pot, age)
                rows.append((pid, nm, nm, normalize(nm), date(season - age, rng.randint(1, 12),
                             rng.randint(1, 28)).isoformat(), T.LOCAL[country], pos, ",".join(sec),
                             "L" if rng.random() < .25 else "R", h, w, rng.randint(1, 5), rng.randint(1, 5),
                             club_id, shirt, ovr, pot, rng.choice([0, 1, 1, 1, 2]), A.pack(attrs),
                             T.weekly_wage(val), val, season + rng.randint(0, 4),
                             Q_SYNTHETIC, Q_SYNTHETIC, Q_SYNTHETIC, Q_SYNTHETIC, Q_SYNTHETIC, 1))
            con.executemany("INSERT INTO players(id,name,name_ar,search,birth_date,nationality,pos,pos2,foot,height,"
                            "weight,weak_foot,skill_moves,club_id,shirt,ovr,potential,growth,attrs,wage,value,"
                            "contract_end,q_core,q_ovr,q_attrs,q_pot,q_money,source_id) VALUES("
                            + ",".join("?" * 28) + ")", rows)
    con.commit()
    con.execute("PRAGMA journal_mode=DELETE")
    con.execute("VACUUM")
    con.close()
    return path
