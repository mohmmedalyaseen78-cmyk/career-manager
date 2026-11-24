#!/usr/bin/env python3
"""Build Career Manager's 2026/27 club and player CSVs.

Sources:
- OpenFootballBase-Data release: attested club squads / club-season data.
- EA's public FC 27 Ratings page API: official base-item OVR only, when a safe
  unambiguous player match is possible. This is NOT a live Career Mode rating.
- Internal conservative estimator: fallback for players with no unambiguous EA match.

No PAC/SHO/PAS/DRI/DEF/PHY attributes are exported.
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import tarfile
import tempfile
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests

REPO = "florentfougeres/OpenFootballBase-Data"
RELEASE_TAG = "data-1.24.0"  # published 2026-11-21; verify latest before future rebuilds
SEASON = "2026/27"
SEASON_FILE_PREFIX = "2026-27."
TODAY = date(2026, 11, 23)
OUT = Path("output")
EA_ENDPOINT = "https://drop-api.ea.com/rating/ea-sports-fc"
EA_RATINGS_PAGE = "https://www.ea.com/games/ea-sports-fc/ratings"
EA_PAGE_SIZE = 100
EA_CONCURRENCY = 2
USE_EA = os.environ.get("USE_EA", "1") != "0"   # USE_EA=0 -> skip EA entirely, estimates only


class EAAccessDenied(RuntimeError):
    """EA refused/limited access (401/403/429...). We stop: no retries, no header tricks, no workarounds."""

LEAGUES: dict[str, dict[str, Any]] = {
    "ENG-PL": {"country": "England", "league": "Premier League", "division": 1, "expected_clubs": 20, "base_ovr": 68},
    "ENG-CH": {"country": "England", "league": "Championship", "division": 2, "expected_clubs": 24, "base_ovr": 63},
    "ESP-LL": {"country": "Spain", "league": "LaLiga", "division": 1, "expected_clubs": 20, "base_ovr": 68},
    "ESP-SD": {"country": "Spain", "league": "Segunda División", "division": 2, "expected_clubs": 22, "base_ovr": 63},
    "DEU-BL": {"country": "Germany", "league": "Bundesliga", "division": 1, "expected_clubs": 18, "base_ovr": 68},
    "DEU-B2": {"country": "Germany", "league": "2. Bundesliga", "division": 2, "expected_clubs": 18, "base_ovr": 63},
    "ITA-SA": {"country": "Italy", "league": "Serie A", "division": 1, "expected_clubs": 20, "base_ovr": 68},
    "ITA-SB": {"country": "Italy", "league": "Serie B", "division": 2, "expected_clubs": 20, "base_ovr": 63},
    "FRA-L1": {"country": "France", "league": "Ligue 1", "division": 1, "expected_clubs": 18, "base_ovr": 68},
    "FRA-L2": {"country": "France", "league": "Ligue 2", "division": 2, "expected_clubs": 18, "base_ovr": 63},
}

USER_AGENT = "CareerManagerDataBuilder/1.1 (personal non-commercial project)"


def download_release_archive(target: Path) -> None:
    api = f"https://api.github.com/repos/{REPO}/releases/tags/{RELEASE_TAG}"
    response = requests.get(api, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}, timeout=60)
    response.raise_for_status()
    release = response.json()
    assets = release.get("assets", [])
    asset = next((a for a in assets if a.get("name") == "openfootballbase-data.tar.gz"), None)
    if not asset:
        raise RuntimeError(f"The archive openfootballbase-data.tar.gz was not found in {RELEASE_TAG}.")
    with requests.get(asset["browser_download_url"], headers={"User-Agent": USER_AGENT}, stream=True, timeout=(30, 180)) as r:
        r.raise_for_status()
        with target.open("wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)


def extract_needed_files(archive: Path, folder: Path) -> dict[str, list[Path]]:
    wanted: dict[str, list[Path]] = {"squad": [], "club_season": [], "stat_club": [], "birth": [], "national": [], "award": []}
    with tarfile.open(archive, "r:gz") as tf:
        for member in tf.getmembers():
            if not member.isfile():
                continue
            normalized = member.name.replace("\\", "/").lstrip("./")
            group = normalized.split("/", 1)[0]
            if group not in wanted:
                continue
            file_name = Path(normalized).name
            if group in {"squad", "club_season"} and not file_name.startswith(SEASON_FILE_PREFIX):
                continue
            if group in {"stat_club", "birth", "national", "award"} and not file_name.endswith(".parquet"):
                continue
            dest = folder / group / file_name
            dest.parent.mkdir(parents=True, exist_ok=True)
            src = tf.extractfile(member)
            if src is None:
                continue
            dest.write_bytes(src.read())
            wanted[group].append(dest)
    for group in ("squad", "club_season"):
        if not wanted[group]:
            raise RuntimeError(f"Missing required {group}/2026-27 parquet file in release archive.")
    return wanted


def read_many(files: list[Path]) -> pd.DataFrame:
    if not files:
        return pd.DataFrame()
    return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)


def norm_player_key(row: pd.Series) -> str:
    qid = str(row.get("player_qid", "") or "").strip()
    if qid and qid.lower() != "nan":
        return qid
    return "name:" + str(row.get("player", "")).strip().casefold()


def normalize_name(value: Any) -> str:
    value = unicodedata.normalize("NFKD", str(value or "").casefold())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def normalize_club(value: Any) -> str:
    name = normalize_name(value)
    remove = {"fc", "f c", "cf", "c f", "afc", "sc", "s c", "ac", "a c", "club", "football", "calcio", "sad", "ud"}
    parts = [p for p in name.split() if p not in remove]
    return " ".join(parts)


def parse_season_start(value: Any) -> int | None:
    matches = re.findall(r"20\d{2}", str(value or ""))
    return int(matches[0]) if matches else None


def age_on(date_string: Any) -> int | None:
    if not date_string or pd.isna(date_string):
        return None
    try:
        born = datetime.strptime(str(date_string)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    return TODAY.year - born.year - ((TODAY.month, TODAY.day) < (born.month, born.day))


def age_adjustment(age: int | None) -> int:
    if age is None:
        return 0
    if age <= 16:
        return -4
    if age <= 19:
        return -2
    if age <= 23:
        return 0
    if age <= 28:
        return 2
    if age <= 31:
        return 1
    if age <= 34:
        return -2
    return -4


def build_player_metrics(stat_club: pd.DataFrame, national: pd.DataFrame, award: pd.DataFrame) -> pd.DataFrame:
    records: dict[str, dict[str, float]] = {}
    if not stat_club.empty and {"player", "season", "apps", "goals"}.issubset(stat_club.columns):
        sc = stat_club.copy()
        sc["_key"] = sc.apply(norm_player_key, axis=1)
        sc["_start_year"] = sc["season"].apply(parse_season_start)
        sc = sc[sc["_start_year"].fillna(0).between(2025, 2026)]
        if "competition_group" in sc.columns:
            sc = sc[sc["competition_group"].fillna("League").isin(["League", "Continental", "Europe"])]
        for key, group in sc.groupby("_key"):
            apps = pd.to_numeric(group["apps"], errors="coerce").fillna(0).sum()
            goals = pd.to_numeric(group["goals"], errors="coerce").fillna(0).sum()
            assists = pd.to_numeric(group.get("assists", pd.Series(index=group.index, dtype=float)), errors="coerce").fillna(0).sum()
            records[key] = {"recent_apps": float(apps), "recent_goals": float(goals), "recent_assists": float(assists)}

    caps_map: dict[str, float] = {}
    if not national.empty and {"player", "team_name", "caps"}.issubset(national.columns):
        nat = national.copy()
        nat["_key"] = nat.apply(norm_player_key, axis=1)
        youth = nat["team_name"].astype(str).str.contains(r"U\s?\d{2}|Under[- ]?\d{2}|Youth", case=False, regex=True)
        nat = nat[~youth]
        nat["caps"] = pd.to_numeric(nat["caps"], errors="coerce").fillna(0)
        caps_map = nat.groupby("_key")["caps"].max().to_dict()

    award_map: dict[str, float] = {}
    if not award.empty and {"player_name", "rank"}.issubset(award.columns):
        aw = award.copy()
        aw["rank"] = pd.to_numeric(aw["rank"], errors="coerce")
        if "year" in aw.columns:
            aw = aw[pd.to_numeric(aw["year"], errors="coerce").fillna(0) >= 2015]
        for _, row in aw.dropna(subset=["rank"]).iterrows():
            key = str(row.get("player_qid", "") or "").strip()
            if not key or key.lower() == "nan":
                key = "name:" + str(row.get("player_name", "")).strip().casefold()
            rank = float(row["rank"])
            bonus = 2.0 if rank == 1 else 1.0 if rank <= 10 else 0.5 if rank <= 30 else 0.0
            award_map[key] = max(award_map.get(key, 0.0), bonus)

    all_keys = set(records) | set(caps_map) | set(award_map)
    return pd.DataFrame([{
        "_key": key,
        "recent_apps": records.get(key, {}).get("recent_apps", 0.0),
        "recent_goals": records.get(key, {}).get("recent_goals", 0.0),
        "recent_assists": records.get(key, {}).get("recent_assists", 0.0),
        "senior_caps": caps_map.get(key, 0.0),
        "award_bonus": award_map.get(key, 0.0),
        "has_recent_stats": key in records,
    } for key in all_keys])


def fetch_ea_page(offset: int) -> dict[str, Any]:
    params = {"locale": "en", "limit": str(EA_PAGE_SIZE), "offset": str(offset)}
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "drop-referrer": EA_RATINGS_PAGE,
    }
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            response = requests.get(EA_ENDPOINT, params=params, headers=headers, timeout=35)
            if response.status_code in (401, 403, 404, 405, 429) or response.status_code >= 500 and attempt == 3:
                raise EAAccessDenied(f"HTTP {response.status_code} from EA ratings endpoint - access not available, stopping")
            response.raise_for_status()
            data = response.json()
            if not isinstance(data.get("items"), list):
                raise ValueError("EA API response does not contain an items array")
            return data
        except EAAccessDenied:
            raise
        except Exception as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(0.75 * (2 ** attempt))
    raise RuntimeError(f"EA ratings page offset {offset} failed: {last_error}")


def fetch_ea_official_ovrs() -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Fetch public EA base ratings; return normalized name -> candidate records."""
    first = fetch_ea_page(0)
    total = int(first.get("totalItems") or len(first["items"]))
    items = list(first["items"])
    offsets = list(range(EA_PAGE_SIZE, total, EA_PAGE_SIZE))
    print(f"EA public ratings database reports {total:,} items; fetching pages...")
    with ThreadPoolExecutor(max_workers=EA_CONCURRENCY) as pool:
        futures = {pool.submit(fetch_ea_page, offset): offset for offset in offsets}
        for future in as_completed(futures):
            page = future.result()
            items.extend(page["items"])
    by_id: dict[str, dict[str, Any]] = {}
    for item in items:
        if item.get("id") is None:
            continue
        # Current Career Manager scope is men's club football, not women's teams.
        gender_id = (item.get("gender") or {}).get("id")
        if gender_id == 1:
            continue
        try:
            ovr = int(item.get("overallRating"))
        except (TypeError, ValueError):
            continue
        if not 1 <= ovr <= 99:
            continue
        first_name = str(item.get("firstName") or "").strip()
        last_name = str(item.get("lastName") or "").strip()
        full_name = " ".join(x for x in (first_name, last_name) if x)
        common_name = str(item.get("commonName") or "").strip()
        names = {normalize_name(full_name), normalize_name(common_name)} - {""}
        record = {
            "id": str(item["id"]),
            "ovr": ovr,
            "full_name": full_name,
            "common_name": common_name,
            "team": str((item.get("team") or {}).get("label") or ""),
            "team_norm": normalize_club((item.get("team") or {}).get("label") or ""),
            "source_url": EA_RATINGS_PAGE,
        }
        by_id[str(item["id"])] = {**record, "name_keys": names}
    index: dict[str, list[dict[str, Any]]] = {}
    for rec in by_id.values():
        for key in rec["name_keys"]:
            index.setdefault(key, []).append(rec)
    meta = {
        "endpoint": EA_ENDPOINT,
        "official_page": EA_RATINGS_PAGE,
        "reported_total_items": total,
        "unique_male_player_items": len(by_id),
        "snapshot_fetched_at_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "important_limit": "EA states that the public table reflects Gold/Silver/Bronze Ultimate Team base items at launch; it does not equal dynamic Career Mode form updates.",
    }
    return index, meta


def match_ea_ovr(player_name: str, club_name: str, index: dict[str, list[dict[str, Any]]]) -> dict[str, Any] | None:
    key = normalize_name(player_name)
    candidates = index.get(key, [])
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    club_key = normalize_club(club_name)
    same_club = [c for c in candidates if c.get("team_norm") and c["team_norm"] == club_key]
    if len(same_club) == 1:
        return same_club[0]
    # A common name may be duplicated across players/teams. Do not guess.
    return None


def impact_score(row: pd.Series) -> float:
    role = str(row.get("position_group") or "MF")
    weights = {"GK": (0.03, 0.05), "DF": (0.35, 0.50), "MF": (0.85, 1.0), "FW": (1.45, 0.75)}
    goal_w, assist_w = weights.get(role, (0.8, 0.9))
    apps = max(0.0, float(row.get("recent_apps", 0) or 0))
    goals = max(0.0, float(row.get("recent_goals", 0) or 0))
    assists = max(0.0, float(row.get("recent_assists", 0) or 0))
    caps = max(0.0, float(row.get("senior_caps", 0) or 0))
    award = max(0.0, float(row.get("award_bonus", 0) or 0))
    # Playing time signals availability/importance; output weights depend on role.
    return math.log1p(apps) * 1.15 + math.log1p(goals) * goal_w + math.log1p(assists) * assist_w + min(caps, 80) / 80 * 2.0 + award


def estimate_ovr(row: pd.Series) -> int:
    base = int(row["base_ovr"])
    age = row.get("age")
    apps = float(row.get("recent_apps", 0) or 0)
    caps = float(row.get("senior_caps", 0) or 0)
    award_bonus = float(row.get("award_bonus", 0) or 0)
    pct = float(row.get("impact_percentile", 50) or 50)
    age_adj = age_adjustment(age if pd.notna(age) else None)
    caps_adj = round((math.log1p(min(caps, 120)) / math.log1p(120)) * 3.0)
    performance_adj = round((pct - 50.0) * 0.13) if bool(row.get("has_recent_stats", False)) else 0
    playing_time_adj = 1 if apps >= 25 else 0 if apps >= 8 else -1 if apps > 0 else -2
    # Conservative cap: this is an internal estimate, never presented as EA's value.
    return int(max(48, min(89, base + age_adj + caps_adj + performance_adj + playing_time_adj + round(award_bonus))))


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    ea_index: dict[str, list[dict[str, Any]]] = {}
    ea_meta: dict[str, Any] = {"status": "UNAVAILABLE", "note": "Fallback estimates will be used."}
    try:
        if not USE_EA:
            raise RuntimeError("EA fetch disabled (USE_EA=0)")
        ea_index, ea_meta = fetch_ea_official_ovrs()
        ea_meta["status"] = "FETCHED"
    except EAAccessDenied as exc:
        print(f"NOTE: EA ratings not accessible, using internal estimates only: {exc}", file=sys.stderr)
        ea_meta["status"] = "ACCESS_DENIED"
        ea_meta["error"] = str(exc)
    except Exception as exc:
        print(f"WARNING: EA official ratings fetch failed; estimates will be used: {exc}", file=sys.stderr)
        ea_meta["status"] = "FETCH_FAILED"
        ea_meta["error"] = str(exc)

    with tempfile.TemporaryDirectory(prefix="career_manager_rosters_") as temp:
        tempdir = Path(temp)
        archive = tempdir / "openfootballbase-data.tar.gz"
        print(f"Downloading OpenFootballBase {RELEASE_TAG}...")
        download_release_archive(archive)
        files = extract_needed_files(archive, tempdir / "data")

        squad = read_many(files["squad"])
        print("squad columns:", list(squad.columns))
        if "competition" in squad.columns:
            comps = sorted(map(str, squad["competition"].dropna().unique()))
            print(f"competition codes in squad data ({len(comps)}):", comps[:60])
            if not set(LEAGUES) & set(comps):
                raise RuntimeError("None of the expected league codes " + str(list(LEAGUES)) + " exist in the source; "
                                   "the schema changed. Check the printed competition codes and update LEAGUES.")
        else:
            raise RuntimeError("squad data has no 'competition' column; schema changed. Columns: " + str(list(squad.columns)))
        club_season = read_many(files["club_season"])
        stats = read_many(files["stat_club"])
        births = read_many(files["birth"])
        national = read_many(files["national"])
        awards = read_many(files["award"])

        squad = squad[(squad["season"].astype(str).isin([SEASON, "2026-27"])) & squad["competition"].isin(LEAGUES)].copy()
        if "stint" in squad.columns:
            squad = squad[~squad["stint"].astype(str).isin(["left_mid", "loan_out"])].copy()
        squad["_key"] = squad.apply(norm_player_key, axis=1)
        squad = squad.drop_duplicates(subset=["competition", "club", "_key"], keep="last").copy()

        if not births.empty and {"player_qid", "birth_date", "precision"}.issubset(births.columns):
            births = births[births["precision"].astype(str).eq("11")].drop_duplicates("player_qid", keep="last")
            birth_map = births.set_index("player_qid")["birth_date"].to_dict()
        else:
            birth_map = {}

        metrics = build_player_metrics(stats, national, awards)
        if not metrics.empty:
            squad = squad.merge(metrics, on="_key", how="left")
        for col in ["recent_apps", "recent_goals", "recent_assists", "senior_caps", "award_bonus"]:
            if col not in squad.columns:
                squad[col] = 0.0
            squad[col] = pd.to_numeric(squad[col], errors="coerce").fillna(0.0)
        if "has_recent_stats" not in squad.columns:
            squad["has_recent_stats"] = False
        squad["has_recent_stats"] = squad["has_recent_stats"].fillna(False).astype(bool)
        squad["age"] = squad.apply(lambda r: age_on(birth_map.get(str(r.get("player_qid", "")))) if str(r.get("player_qid", "")).strip() else None, axis=1)
        squad["position_group"] = squad.get("position", pd.Series(index=squad.index, dtype=object)).fillna("MF")
        squad.loc[~squad["position_group"].isin(["GK", "DF", "MF", "FW"]), "position_group"] = "MF"
        squad["country"] = squad["competition"].map(lambda c: LEAGUES[c]["country"])
        squad["league"] = squad["competition"].map(lambda c: LEAGUES[c]["league"])
        squad["division"] = squad["competition"].map(lambda c: LEAGUES[c]["division"])
        squad["base_ovr"] = squad["competition"].map(lambda c: LEAGUES[c]["base_ovr"])

        squad["impact_score"] = squad.apply(impact_score, axis=1)
        squad["impact_percentile"] = squad.groupby(["competition", "position_group"])["impact_score"].rank(pct=True, method="average") * 100
        squad["impact_percentile"] = squad["impact_percentile"].fillna(50)
        squad["has_recent_stats"] = squad["has_recent_stats"].astype(bool)
        squad["Estimated_OVR"] = squad.apply(estimate_ovr, axis=1)
        squad["OVR"] = squad["Estimated_OVR"]
        squad["OVR_Status"] = "ESTIMATED"
        squad["OVR_Source"] = "Internal estimate: tier + age + recent public stats + senior caps + award signal"

        ea_matches = 0
        if ea_index:
            matches = squad.apply(lambda r: match_ea_ovr(r.get("player", ""), r.get("club", ""), ea_index), axis=1)
            squad["EA_Official_OVR"] = matches.apply(lambda x: x.get("ovr") if x else None)
            squad["EA_Source_URL"] = matches.apply(lambda x: x.get("source_url") if x else "")
            valid = pd.to_numeric(squad["EA_Official_OVR"], errors="coerce").between(1, 99)
            ea_matches = int(valid.sum())
            squad.loc[valid, "OVR"] = pd.to_numeric(squad.loc[valid, "EA_Official_OVR"]).astype(int)
            squad.loc[valid, "OVR_Status"] = "EA_OFFICIAL_BASE_ITEM"
            squad.loc[valid, "OVR_Source"] = EA_RATINGS_PAGE

        # Optional manual correction/override: only use a value with an explicit source URL.
        override_path = Path("official_ovr_overrides.csv")
        if override_path.exists():
            overrides = pd.read_csv(override_path)
            required = {"player", "club", "OVR", "source_url"}
            if required.issubset(overrides.columns):
                overrides["_player_norm"] = overrides["player"].map(normalize_name)
                overrides["_club_norm"] = overrides["club"].map(normalize_club)
                squad["_player_norm"] = squad["player"].map(normalize_name)
                squad["_club_norm"] = squad["club"].map(normalize_club)
                ov = overrides.drop_duplicates(["_player_norm", "_club_norm"], keep="last")[["_player_norm", "_club_norm", "OVR", "source_url"]]
                squad = squad.merge(ov, on=["_player_norm", "_club_norm"], how="left", suffixes=("", "_override"))
                has_override = pd.to_numeric(squad.get("OVR_override"), errors="coerce").between(1, 99) & squad.get("source_url", pd.Series(index=squad.index, dtype=object)).fillna("").astype(str).str.startswith("http")
                squad.loc[has_override, "OVR"] = pd.to_numeric(squad.loc[has_override, "OVR_override"]).astype(int)
                squad.loc[has_override, "OVR_Status"] = "MANUAL_SOURCE_OVERRIDE"
                squad.loc[has_override, "OVR_Source"] = squad.loc[has_override, "source_url"]

        # Player-facing file: one OVR only; no PAC/SHO/PAS/DRI/DEF/PHY columns.
        player_cols = ["country", "league", "division", "club", "player", "position_group", "OVR"]
        players = squad[player_cols].rename(columns={"player": "player_name", "position_group": "position", "OVR": "OVR"})
        players = players.sort_values(["country", "division", "league", "club", "OVR", "player_name"], ascending=[True, True, True, True, False, True])
        players.to_csv(OUT / "players_2026-27_OVR.csv", index=False, encoding="utf-8-sig")

        collected = datetime.utcnow().strftime("%Y-%m-%d")
        squad["ovr_collected_at"] = collected
        squad["birth_date"] = squad["player_qid"].map(lambda q: str(birth_map.get(str(q), ""))[:10]) if "player_qid" in squad.columns else ""
        for extra in ("nationality", "citizenship", "country_of_citizenship", "jersey_number", "shirt_number", "foot", "height"):
            if extra not in squad.columns:
                squad[extra] = ""
        base_cols = ["country", "league", "division", "club", "player", "player_qid", "position_group", "position", "age",
                     "birth_date", "nationality", "citizenship", "country_of_citizenship", "jersey_number", "shirt_number",
                     "foot", "height", "OVR", "OVR_Status", "OVR_Source", "ovr_collected_at"]
        for col in base_cols:
            if col not in squad.columns:
                squad[col] = ""
        squad[base_cols].rename(columns={"player": "player_name"}).to_csv(OUT / "players_2026-27_BASE.csv", index=False, encoding="utf-8-sig")

        audit_cols = ["country", "league", "division", "club", "player", "position_group", "OVR", "OVR_Status", "OVR_Source", "ovr_collected_at", "Estimated_OVR", "EA_Official_OVR", "source_title", "source_revid", "listed_in"]
        for col in audit_cols:
            if col not in squad.columns:
                squad[col] = ""
        squad[audit_cols].rename(columns={"player": "player_name", "position_group": "position"}).to_csv(OUT / "players_2026-27_OVR_AUDIT.csv", index=False, encoding="utf-8-sig")

        if not club_season.empty:
            clubs = club_season[(club_season["season"].astype(str).isin([SEASON, "2026-27"])) & club_season["competition"].isin(LEAGUES)].copy()
            clubs["country"] = clubs["competition"].map(lambda c: LEAGUES[c]["country"])
            clubs["league"] = clubs["competition"].map(lambda c: LEAGUES[c]["league"])
            clubs["division"] = clubs["competition"].map(lambda c: LEAGUES[c]["division"])
            if "players" in clubs.columns:
                clubs["player_count_in_source"] = pd.to_numeric(clubs["players"], errors="coerce").fillna(0).astype(int)
            else:
                clubs["player_count_in_source"] = 0
            club_cols = ["country", "league", "division", "club", "player_count_in_source", "source_title", "source_revid", "known_gap_reason"]
            for col in club_cols:
                if col not in clubs.columns:
                    clubs[col] = ""
            clubs = clubs.drop_duplicates(subset=["competition", "club"])
            clubs[club_cols].sort_values(["country", "division", "league", "club"]).to_csv(OUT / "clubs_2026-27.csv", index=False, encoding="utf-8-sig")
            actual_counts = clubs.groupby("competition")["club"].nunique().to_dict()
        else:
            actual_counts = {}

        roster_counts = squad.groupby("competition")["club"].nunique().to_dict()
        coverage_rows = []
        for code, meta in LEAGUES.items():
            competition_clubs = int(actual_counts.get(code, 0))
            roster_clubs = int(roster_counts.get(code, 0))
            coverage_rows.append({
                "league_code": code,
                "country": meta["country"],
                "league": meta["league"],
                "expected_clubs": meta["expected_clubs"],
                "clubs_in_source": competition_clubs,
                "clubs_with_rosters": roster_clubs,
                "player_rows": int((squad["competition"] == code).sum()),
                "competition_list_complete": competition_clubs == meta["expected_clubs"],
                "roster_list_complete": roster_clubs == meta["expected_clubs"],
                "coverage_status": "COMPLETE" if competition_clubs == meta["expected_clubs"] and roster_clubs == meta["expected_clubs"] else "REVIEW_REQUIRED",
            })
        coverage = pd.DataFrame(coverage_rows)
        coverage.to_csv(OUT / "coverage_2026-27.csv", index=False, encoding="utf-8-sig")

        metadata = {
            "product": "Career Manager",
            "season": SEASON,
            "generated_at_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "roster_source": f"OpenFootballBase-Data {RELEASE_TAG}",
            "roster_source_url": f"https://github.com/{REPO}/releases/tag/{RELEASE_TAG}",
            "roster_source_basis": "Wikipedia CC BY-SA 4.0 and Wikidata CC0; attribution and share-alike terms must be checked before redistribution.",
            "ea_ratings": ea_meta,
            "ea_matched_players": ea_matches,
            "estimated_players": int((squad["OVR_Status"] == "ESTIMATED").sum()),
            "manual_override_players": int((squad["OVR_Status"] == "MANUAL_SOURCE_OVERRIDE").sum()),
            "total_player_rows": int(len(squad)),
            "total_clubs_in_source": int(len(clubs)) if not club_season.empty else 0,
            "expected_clubs": int(sum(v["expected_clubs"] for v in LEAGUES.values())),
            "ovr_policy": "Use matched EA public base-item OVR where unambiguous; otherwise internal estimated OVR. Never describe estimates as official.",
            "ea_caveat": "EA says its public ratings table reflects Gold/Silver/Bronze Ultimate Team base items at launch, not live form updates in other modes; it is not a promise of identical Career Mode dynamic ratings.",
            "player_output_columns": player_cols,
        }
        (OUT / "DATA_METADATA.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

        print(f"Created {len(players):,} player rows, {len(clubs) if not club_season.empty else 0:,} clubs, and {len(coverage)} league coverage rows.")
        print(f"Official EA OVR matches: {ea_matches:,}; estimated OVRs: {int((squad['OVR_Status'] == 'ESTIMATED').sum()):,}.")
        print("Review coverage_2026-27.csv and DATA_METADATA.json before importing the CSVs into the game.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
