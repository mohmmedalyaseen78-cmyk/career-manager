"""Import the generator output (players_2026-27_BASE.csv) into world.db with the game's schema.

What is SOURCED vs ESTIMATED (stored per player in q_* columns, never hidden):
- name, club, league, age/birth date (when present) .......... SOURCED (open data)
- OVR ........................................................ SOURCED if the CSV says EA_OFFICIAL_BASE_ITEM / MANUAL_SOURCE_OVERRIDE,
                                                               otherwise ESTIMATED
- detailed position (GK/DF/MF/FW -> 12 positions), 35 sub-attributes, potential, growth, height/weight, wage, value,
  contract length ........................................... ESTIMATED (generated consistently from OVR + position)
Nothing here is presented as an official EA rating; the UI shows the q_* label.
"""
import csv
import hashlib
import os
import random
import sqlite3
import unicodedata
from datetime import date

from . import attrs as A
from . import talents as T
from .names_ar import normalize, pick_unique_name
from .schema import WORLD_SCHEMA_VERSION, WORLD_SQL, Q_SOURCED, Q_ESTIMATED, Q_SYNTHETIC, Q_UNKNOWN
from .worldgen import LEAGUES

SEASON = 2026
MIN_SQUAD = 20  # clubs with fewer real players are topped up with flagged SYNTHETIC fillers (and reported)
SOURCED_OVR = {"EA_OFFICIAL_BASE_ITEM", "MANUAL_SOURCE_OVERRIDE"}

# (group, [(position, share)])
SPLIT = {"DF": [("CB", .56), ("LB", .22), ("RB", .22)],
         "MF": [("CDM", .25), ("CM", .40), ("CAM", .22), ("LM", .065), ("RM", .065)],
         "FW": [("ST", .50), ("LW", .25), ("RW", .25)], "GK": [("GK", 1.0)]}
MIN_PER_CLUB = {"CB": 3, "LB": 1, "RB": 1, "ST": 1}


def _h(*parts):
    return int(hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:12], 16)


def _quota(n, shares):
    raw = [n * s for _, s in shares]
    base = [int(x) for x in raw]
    left = n - sum(base)
    for i in sorted(range(len(raw)), key=lambda i: raw[i] - base[i], reverse=True)[:left]:
        base[i] += 1
    return {p: c for (p, _), c in zip(shares, base)}


def assign_positions(group, players, club, seed):
    """Deterministic detailed positions for one club's players of a group."""
    shares = SPLIT.get(group, SPLIT["MF"])
    q = _quota(len(players), shares)
    for p, m in MIN_PER_CLUB.items():
        if p in q and len(players) >= 5 and q[p] < m:
            donor = max(q, key=lambda k: q[k])
            if donor != p and q[donor] > m:
                q[donor] -= 1
                q[p] += 1
    order = sorted(players, key=lambda r: _h(seed, club, r["player_name"], r.get("player_qid", "")))
    out, i = {}, 0
    for pos, c in q.items():
        for _ in range(c):
            out[id(order[i])] = pos
            i += 1
    return out


def _birth(row, rng, season):
    """-> (birth_iso, quality). Real birth date when present, else an age-based estimate."""
    bd = (row.get("birth_date") or "").strip()[:10]
    try:
        if len(bd) == 10 and 1950 < int(bd[:4]) < 2012:
            date.fromisoformat(bd)
            return bd, Q_SOURCED
    except ValueError:
        pass
    try:
        age = int(float(row.get("age")))
    except (TypeError, ValueError):
        age = None
    if age is None or not 15 <= age <= 45:
        age, q = int(min(37, max(18, rng.gauss(26, 4)))), Q_ESTIMATED
    else:
        q = Q_ESTIMATED
    return date(season - age, rng.randint(1, 12), rng.randint(1, 28)).isoformat(), q


def _clean(x):
    return unicodedata.normalize("NFC", (x or "").strip())


def import_world(base_csv, out_path, seed=2026, season=SEASON, fill_gaps=True, source_note="", ea_status=""):
    rng_root = random.Random(seed)
    rows = list(csv.DictReader(open(base_csv, encoding="utf-8-sig")))
    if not rows:
        raise ValueError("empty players file")
    if os.path.exists(out_path):
        os.remove(out_path)
    con = sqlite3.connect(out_path)
    con.executescript(WORLD_SQL)
    collected = max((r.get("ovr_collected_at") or "" for r in rows), default="")
    con.execute("INSERT INTO sources VALUES(1,'OpenFootballBase-Data (Wikipedia CC BY-SA 4.0 / Wikidata CC0)',"
                "'https://github.com/florentfougeres/OpenFootballBase-Data','', 'CC BY-SA 4.0 / CC0', ?)", (source_note,))
    con.execute("INSERT INTO sources VALUES(2,'EA SPORTS FC public ratings (base item OVR only)',"
                "'https://www.ea.com/games/ea-sports-fc/ratings',?,'unofficial endpoint; personal non-commercial use',?)",
                (collected, f"status: {ea_status}. Not a Career Mode dynamic rating."))
    con.execute("INSERT INTO sources VALUES(3,'Career Manager internal estimator/generator',NULL,?,'n/a',"
                "'Estimated values; never shown as official')", (collected,))
    lg_ids, club_ids = {}, {}
    for lid, (code, name, name_ar, country, tier, n) in enumerate(LEAGUES, 1):
        con.execute("INSERT INTO leagues VALUES(?,?,?,?,?,?,?)", (lid, code, name, name_ar, country, tier, n))
        lg_ids[(country, name)] = lid
    by_club = {}
    skipped = 0
    for r in rows:
        key = (_clean(r["country"]), _clean(r["league"]))
        if key not in lg_ids:
            skipped += 1
            continue
        by_club.setdefault((key, _clean(r["club"])), []).append(r)
    # club level numbers (estimated): reputation from the strength of the squad inside its tier
    used_names = set()
    report = dict(players=0, clubs=0, sourced_ovr=0, estimated_ovr=0, filled=0, skipped_rows=skipped, clubs_filled=[],
                  per_league={}, ovr_min=99, ovr_max=1)
    pid = 0
    for (key, club), plist in sorted(by_club.items(), key=lambda kv: (lg_ids[kv[0][0]], kv[0][1])):
        lid = lg_ids[key]
        tier = LEAGUES[lid - 1][4]
        ovrs = sorted((int(float(r["OVR"])) for r in plist), reverse=True)
        top = ovrs[:14] or [60]
        avg = sum(top) / len(top)
        rep = int(max(25, min(95, (avg - 50) * 2.2 + (8 if tier == 1 else -4))))
        cid = len(club_ids) + 1
        club_ids[(key, club)] = cid
        short = "".join(ch for ch in club if ch.isalpha())[:3].upper()
        con.execute("INSERT INTO clubs VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (cid, lid, club, None, short, None, rep, rep * 400_000, rep * 60_000, Q_ESTIMATED))
        report["clubs"] += 1
        report["per_league"][LEAGUES[lid - 1][1]] = report["per_league"].get(LEAGUES[lid - 1][1], 0) + 1
        groups = {}
        for r in plist:
            g = (r.get("position_group") or "MF").strip().upper()
            groups.setdefault(g if g in SPLIT else "MF", []).append(r)
        pos_of = {}
        for g, lst in groups.items():
            pos_of.update(assign_positions(g, lst, club, seed))
        shirts = set()
        for r in sorted(plist, key=lambda r: (-int(float(r["OVR"])), r["player_name"])):
            pid += 1
            prng = random.Random(_h(seed, club, r["player_name"], r.get("player_qid", "")))
            ovr = max(30, min(99, int(float(r["OVR"]))))
            pos = pos_of[id(r)]
            birth, bq = _birth(r, prng, season)
            age = season - int(birth[:4])
            gap = max(0, int(round((27 - age) * 0.9 + prng.gauss(0, 2)))) if age < 27 else 0
            pot = min(99, ovr + gap)
            attrs, _ = A.generate_attrs(pos, ovr, prng)
            sec = [p for p in T.ADJ[pos] if A.ovr_at(attrs, p) >= ovr - 4][:2]
            h, w = T._height_weight(pos, age, prng)
            val = T.market_value(ovr, pot, age)
            status = (r.get("OVR_Status") or "").strip()
            q_ovr = Q_SOURCED if status in SOURCED_OVR else Q_ESTIMATED
            report["sourced_ovr" if q_ovr == Q_SOURCED else "estimated_ovr"] += 1
            nat = _clean(r.get("nationality") or r.get("country_of_citizenship") or r.get("citizenship")) or "?"
            foot = (r.get("foot") or "").strip()[:1].upper()
            foot = foot if foot in ("L", "R") else ("L" if prng.random() < (0.7 if pos in ("LB", "LW", "LM") else 0.2) else "R")
            shirt = None
            try:
                s = int(float(r.get("shirt_number") or r.get("jersey_number") or ""))
                if 1 <= s <= 99 and s not in shirts:
                    shirt = s
                    shirts.add(s)
            except ValueError:
                pass
            name = _clean(r["player_name"])
            con.execute("INSERT INTO players(id,name,name_ar,search,birth_date,nationality,pos,pos2,foot,height,weight,"
                        "weak_foot,skill_moves,club_id,shirt,ovr,potential,growth,attrs,wage,value,contract_end,q_core,"
                        "q_ovr,q_attrs,q_pot,q_money,source_id,ext_id) VALUES(" + ",".join("?" * 29) + ")",
                        (pid, name, name, normalize(name), birth, nat, pos, ",".join(sec), foot, h, w,
                         min(5, max(1, int(prng.gauss(3, .9)))), min(5, max(1, int(prng.gauss(2.6, .9)))), cid, shirt,
                         ovr, pot, prng.choice([0, 1, 1, 1, 2]), A.pack(attrs), T.weekly_wage(val), val,
                         season + prng.randint(0, 4), bq, q_ovr, Q_ESTIMATED, Q_ESTIMATED, Q_ESTIMATED,
                         1 if q_ovr == Q_SOURCED and status == "EA_OFFICIAL_BASE_ITEM" else (2 if q_ovr == Q_SOURCED else 3),
                         (r.get("player_qid") or "").strip() or None))
            report["players"] += 1
            report["ovr_min"], report["ovr_max"] = min(report["ovr_min"], ovr), max(report["ovr_max"], ovr)
        if fill_gaps and len(plist) < MIN_SQUAD:
            need = MIN_SQUAD - len(plist)
            report["clubs_filled"].append((club, len(plist), need))
            for k in range(need):
                pid += 1
                prng = random.Random(_h(seed, club, "fill", k))
                pos = ["GK", "CB", "CM", "ST", "LB", "RB", "CDM", "LW", "RW", "CAM"][k % 10]
                ovr = max(40, int(avg - 8 + prng.gauss(0, 3)))
                nm = pick_unique_name(prng, used_names)
                attrs, _ = A.generate_attrs(pos, ovr, prng)
                age = prng.randint(18, 24)
                h, w = T._height_weight(pos, age, prng)
                val = T.market_value(ovr, ovr + 4, age)
                con.execute("INSERT INTO players(id,name,name_ar,search,birth_date,nationality,pos,pos2,foot,height,weight,"
                            "weak_foot,skill_moves,club_id,shirt,ovr,potential,growth,attrs,wage,value,contract_end,q_core,"
                            "q_ovr,q_attrs,q_pot,q_money,source_id,ext_id) VALUES(" + ",".join("?" * 29) + ")",
                            (pid, nm, nm, normalize(nm), date(season - age, 6, 15).isoformat(), "?", pos, "", "R", h, w,
                             3, 2, cid, None, ovr, ovr + 4, 1, A.pack(attrs), T.weekly_wage(val), val, season + 2,
                             Q_SYNTHETIC, Q_SYNTHETIC, Q_SYNTHETIC, Q_SYNTHETIC, Q_SYNTHETIC, 3, None))
                report["players"] += 1
                report["filled"] += 1
    meta = {"schema_version": str(WORLD_SCHEMA_VERSION), "season": str(season), "world_id": f"real-{season}-{seed}",
            "data_cutoff": collected or "unknown", "kind": "REAL_ROSTERS_ESTIMATED_ATTRIBUTES", "ea_status": ea_status}
    con.executemany("INSERT INTO meta VALUES(?,?)", meta.items())
    for lid, (code, *_rest, n) in enumerate(LEAGUES, 1):
        cnt = con.execute("SELECT COUNT(*) FROM clubs WHERE league_id=?", (lid,)).fetchone()[0]
        con.execute("UPDATE leagues SET n_clubs=? WHERE id=?", (cnt, lid))
    con.commit()
    con.execute("PRAGMA journal_mode=DELETE")
    con.execute("VACUUM")
    con.close()
    return report


if __name__ == "__main__":
    import json
    import sys
    rep = import_world(sys.argv[1], sys.argv[2])
    print(json.dumps(rep, ensure_ascii=False, indent=1))
