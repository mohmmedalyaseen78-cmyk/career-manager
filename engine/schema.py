"""SQLite schemas.

world.db   : shared, immutable base world (clubs, real players, base attributes). Opened read-only.
career.db  : one small file per career; holds ONLY that career's changes (sparse overrides,
             generated youth, fixtures, results, transfers, history). Never copies the world.
"""

WORLD_SCHEMA_VERSION = 1
CAREER_SCHEMA_VERSION = 1

# data-quality / provenance codes (stored per field-group on every player)
Q_UNKNOWN, Q_SOURCED, Q_ESTIMATED, Q_SYNTHETIC = 0, 1, 2, 3
Q_LABELS_AR = {0: "غير معروف", 1: "موثّق", 2: "تقديري", 3: "تجريبي"}

WORLD_SQL = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE sources(id INTEGER PRIMARY KEY, name TEXT NOT NULL, url TEXT, accessed TEXT, license TEXT, note TEXT);
CREATE TABLE leagues(
  id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL, name_ar TEXT,
  country TEXT NOT NULL, tier INTEGER NOT NULL CHECK(tier IN (1,2)), n_clubs INTEGER NOT NULL);
CREATE TABLE clubs(
  id INTEGER PRIMARY KEY, league_id INTEGER NOT NULL REFERENCES leagues(id),
  name TEXT NOT NULL, name_ar TEXT, short TEXT, stadium TEXT,
  reputation INTEGER NOT NULL, transfer_budget INTEGER NOT NULL, wage_budget INTEGER NOT NULL,
  data_quality INTEGER NOT NULL DEFAULT 0);
CREATE INDEX ix_clubs_league ON clubs(league_id);
CREATE TABLE players(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, name_ar TEXT, search TEXT NOT NULL,
  birth_date TEXT NOT NULL, nationality TEXT NOT NULL,
  pos TEXT NOT NULL, pos2 TEXT NOT NULL DEFAULT '', foot TEXT NOT NULL,
  height INTEGER, weight INTEGER, weak_foot INTEGER, skill_moves INTEGER,
  club_id INTEGER NOT NULL REFERENCES clubs(id), shirt INTEGER,
  ovr INTEGER NOT NULL, potential INTEGER NOT NULL, growth INTEGER NOT NULL DEFAULT 1,
  attrs BLOB NOT NULL,
  wage INTEGER, value INTEGER, contract_end INTEGER,
  q_core INTEGER NOT NULL DEFAULT 0, q_ovr INTEGER NOT NULL DEFAULT 0, q_attrs INTEGER NOT NULL DEFAULT 0,
  q_pot INTEGER NOT NULL DEFAULT 0, q_money INTEGER NOT NULL DEFAULT 0,
  source_id INTEGER REFERENCES sources(id), ext_id TEXT);
CREATE INDEX ix_players_club ON players(club_id);
CREATE INDEX ix_players_search ON players(search);
CREATE INDEX ix_players_pos_ovr ON players(pos, ovr DESC);
"""

CAREER_SQL = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE career_info(
  id INTEGER PRIMARY KEY CHECK(id=1), career_id TEXT NOT NULL, world_id TEXT NOT NULL,
  club_id INTEGER NOT NULL, club_name TEXT NOT NULL, manager_name TEXT NOT NULL,
  season INTEGER NOT NULL, cur_date TEXT NOT NULL, seed INTEGER NOT NULL,
  created TEXT NOT NULL, last_saved TEXT NOT NULL, settings TEXT NOT NULL DEFAULT '{}');
-- sparse per-career overrides of base players (row exists only after first change)
CREATE TABLE player_state(
  player_id INTEGER PRIMARY KEY, club_id INTEGER, ovr INTEGER, potential INTEGER, attrs BLOB,
  wage INTEGER, value INTEGER, contract_end INTEGER,
  form INTEGER, fitness INTEGER, morale INTEGER, injury_days INTEGER, status INTEGER);
CREATE INDEX ix_state_club ON player_state(club_id);
-- talents generated inside this career only (ids start at 10,000,000)
CREATE TABLE gen_players(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, name_ar TEXT, search TEXT NOT NULL,
  birth_date TEXT NOT NULL, nationality TEXT NOT NULL, pos TEXT NOT NULL, pos2 TEXT NOT NULL DEFAULT '',
  foot TEXT NOT NULL, height INTEGER, weight INTEGER, weak_foot INTEGER, skill_moves INTEGER,
  club_id INTEGER NOT NULL, shirt INTEGER, ovr INTEGER NOT NULL, potential INTEGER NOT NULL,
  growth INTEGER NOT NULL, attrs BLOB NOT NULL, wage INTEGER, value INTEGER, contract_end INTEGER,
  fitness INTEGER NOT NULL DEFAULT 100, morale INTEGER NOT NULL DEFAULT 70,
  gen_season INTEGER NOT NULL, origin_club_id INTEGER NOT NULL, tier TEXT NOT NULL);
CREATE INDEX ix_gen_club ON gen_players(club_id);
CREATE INDEX ix_gen_search ON gen_players(search);
CREATE TABLE club_season(club_id INTEGER NOT NULL, season INTEGER NOT NULL, league_id INTEGER NOT NULL,
  PRIMARY KEY(club_id, season));
CREATE INDEX ix_cs_league ON club_season(season, league_id);
CREATE TABLE fixtures(
  id INTEGER PRIMARY KEY, season INTEGER NOT NULL, league_id INTEGER NOT NULL, comp TEXT NOT NULL DEFAULT 'league',
  round INTEGER NOT NULL, date TEXT NOT NULL, home_id INTEGER NOT NULL, away_id INTEGER NOT NULL,
  played INTEGER NOT NULL DEFAULT 0);
CREATE INDEX ix_fx_date ON fixtures(date, played);
CREATE INDEX ix_fx_league ON fixtures(season, league_id, round);
CREATE TABLE results(fixture_id INTEGER PRIMARY KEY REFERENCES fixtures(id), hg INTEGER NOT NULL, ag INTEGER NOT NULL,
  seed INTEGER NOT NULL, detailed INTEGER NOT NULL DEFAULT 0);
CREATE TABLE standings(season INTEGER NOT NULL, league_id INTEGER NOT NULL, club_id INTEGER NOT NULL,
  p INTEGER NOT NULL DEFAULT 0, w INTEGER NOT NULL DEFAULT 0, d INTEGER NOT NULL DEFAULT 0, l INTEGER NOT NULL DEFAULT 0,
  gf INTEGER NOT NULL DEFAULT 0, ga INTEGER NOT NULL DEFAULT 0, pts INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(season, league_id, club_id));
CREATE INDEX ix_st_rank ON standings(season, league_id, pts DESC);
CREATE TABLE match_events(fixture_id INTEGER NOT NULL, minute INTEGER NOT NULL, type TEXT NOT NULL,
  club_id INTEGER NOT NULL, player_id INTEGER, player2_id INTEGER);
CREATE INDEX ix_ev_fx ON match_events(fixture_id);
CREATE TABLE match_player_stats(fixture_id INTEGER NOT NULL, player_id INTEGER NOT NULL, club_id INTEGER NOT NULL,
  minutes INTEGER NOT NULL, rating REAL, goals INTEGER NOT NULL DEFAULT 0, assists INTEGER NOT NULL DEFAULT 0,
  yc INTEGER NOT NULL DEFAULT 0, rc INTEGER NOT NULL DEFAULT 0, saves INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(fixture_id, player_id));
CREATE TABLE match_team_stats(fixture_id INTEGER NOT NULL, club_id INTEGER NOT NULL, stats TEXT NOT NULL,
  PRIMARY KEY(fixture_id, club_id));
CREATE TABLE player_season_stats(season INTEGER NOT NULL, player_id INTEGER NOT NULL, club_id INTEGER NOT NULL,
  apps INTEGER NOT NULL DEFAULT 0, minutes INTEGER NOT NULL DEFAULT 0, goals INTEGER NOT NULL DEFAULT 0,
  assists INTEGER NOT NULL DEFAULT 0, yc INTEGER NOT NULL DEFAULT 0, rc INTEGER NOT NULL DEFAULT 0,
  rating_sum REAL NOT NULL DEFAULT 0, rated INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(season, player_id));
CREATE INDEX ix_pss_goals ON player_season_stats(season, goals DESC);
CREATE TABLE lineup(slot INTEGER PRIMARY KEY, player_id INTEGER NOT NULL);
CREATE TABLE news(id INTEGER PRIMARY KEY, date TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL);
-- club season archive (club level only; names stored as text so purging player stats never loses it)
CREATE TABLE club_history(season INTEGER NOT NULL, club_id INTEGER NOT NULL, club_name TEXT NOT NULL,
  league_id INTEGER NOT NULL, league_name TEXT NOT NULL, position INTEGER NOT NULL, league_size INTEGER NOT NULL,
  p INTEGER NOT NULL, w INTEGER NOT NULL, d INTEGER NOT NULL, l INTEGER NOT NULL, gf INTEGER NOT NULL, ga INTEGER NOT NULL,
  pts INTEGER NOT NULL, champion INTEGER NOT NULL, promoted INTEGER NOT NULL, relegated INTEGER NOT NULL,
  top_scorer TEXT, top_scorer_goals INTEGER, top_assister TEXT, top_assists INTEGER,
  best_rated TEXT, best_rating REAL, most_apps TEXT, most_apps_n INTEGER, manager_name TEXT NOT NULL,
  PRIMARY KEY(season, club_id));
CREATE TABLE season_history(season INTEGER NOT NULL, league_id INTEGER NOT NULL, champion_id INTEGER NOT NULL,
  promoted TEXT NOT NULL DEFAULT '', relegated TEXT NOT NULL DEFAULT '', PRIMARY KEY(season, league_id));
"""
