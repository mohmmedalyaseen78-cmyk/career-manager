# GRAFECO - Spec Amendments (binding, override Master Spec where they conflict)

## A1. Language / UI (2026-11-22)
- Default UI language: Arabic, full RTL on every page/list/table/dialog. All UI strings, news, reports, system messages in Arabic.
- Player/club/competition names keep their known names (Arabic display name when available).
- i18n string table from day one (ar default, en addable later). Code, identifiers, DB columns: English only.

## A2. UI design
- FC-Career-Mode-style navigation: one top nav, one clear home page per section, details in sub-tabs.
- No card walls, no chart clutter, no accounting-software look. Show essentials only.
- Mockups (start, hub, squad, transfer) must be approved before final UI is built.

## A3. League scope (replaces Master Spec 2.1/2.4/2.5)
Top two tiers only, 5 countries = 10 leagues:
- England: Premier League, Championship
- Spain: LaLiga, Segunda Division
- Germany: Bundesliga, 2. Bundesliga
- Italy: Serie A, Serie B
- France: Ligue 1, Ligue 2
- No third tier or lower. Promotion/relegation between tier 1 and tier 2 each season-end (tier 2 has no relegation).
- Domestic cups include clubs of both tiers. European competitions only from qualified clubs of these leagues.
- Expected size: ~198 clubs, ~5,500-6,500 real players (to be verified against the 2026/27 season snapshot).
- No management/gameplay system is removed because of this change.

## A4. Real player data
- Fields: OVR (1-99), 6 main stats (PAC SHO PAS DRI DEF PHY), all sub-stats listed by user, GK stats (Diving Handling Kicking Reflexes Speed Positioning).
- Every value carries a provenance flag: SOURCED / ESTIMATED (+ source id and date). Never present an estimate as official.
- Consistency rules: sub-stats <-> main stats <-> OVR (position-weighted) must agree; automated checks.
- Static snapshot; no online update; game is offline after install.

## A5. Generated youth talents
- Every generated youth gets a unique random Arabic first name + family name (never "Player 001"), never a real player's name, name never changes after creation.
- Nationality chosen independently by generator rules.
- Fields: name, age, nationality, main/secondary positions, foot, OVR, detailed attributes, value, expected wage, height/weight, skills, Potential, Growth Rate (slow/normal/fast/exceptional), fitness, morale.
- Exceptional talents are RARE by design (target distribution to be documented and tested, e.g. elite potential well under ~1% of intake).
- Development depends on age, potential, growth rate, minutes, match ratings, training, coaches, morale, injuries, fitness, squad stability. No automatic rise with time.
- Continuous seasonal intake sized to academy needs (retirements/departures), long-term rating balance (no inflation to 90+ after 5 seasons).
- Everything persisted in the local DB; players are never regenerated on reload (saved seed).
