# GRAFECO - Spec Amendments, part 2 (binding)

## A6. Resource etiquette (the game is not the only program running)
- Background work: low OS priority, small batches, yields between batches, max 1-2 workers (never > half logical CPUs).
- Inactive/minimised window: background work paused or slowed heavily. No timers, no polling.
- Memory pressure from other programs: defer non-urgent work, shrink caches.
- "Low Resource Mode" setting. It must NOT reduce simulation logic, UI responsiveness or fun.
- Long sessions: monitor RSS, no gradual growth. (engine/resources.py)

## A7. Multiple careers
- End career any time -> main menu; new career with any club; unlimited independent careers; one file each.
- Never auto-delete, never overwrite another career without warning; delete only with explicit confirmation.
- Saved-careers page: club, season, last-saved date; actions: continue / new / delete.

## A8. Shared world vs per-career data (DECIDED)
- world.db (shared, read-only, immutable): clubs, real players, base attributes, provenance.
- <career>.gcareer (small): ONLY that career's sparse overrides, generated youths, fixtures, results, transfers.
- Five careers = one world DB + five small files. (Implemented and tested.)

## A9. Interactive match simulation
- Three viewing modes, ONE engine: (1) quick: final score + report, (2) detailed live: minute-by-minute events,
  pause/resume any time, (3) skip straight to result. Detailed is never mandatory.
- During a live match: substitutions, formation change, mentality (defensive/balanced/attacking), pressing/tempo,
  player instructions, half-time changes, continue to the end. Decisions MUST change probabilities.
- Same seed + no interventions => identical result in every mode. (Implemented: engine/match.py MatchSession.)

## A10. Calendar & Task Center
- Calendar: league, domestic cups, European, transfer windows, contract expiries, admin events, off-weeks.
- Advance: 1 day / to next match / to a chosen event / fast-forward quiet days.
- Task Center before advancing: offers awaiting reply, renewal requests, negotiations, injured players, contracts
  expiring, coaching offers, board decisions. Sorted by importance, each opens its page. Never blocks advancing for
  minor items; no notification spam. (Pending implementation.)

## A11. Manager career progression
- Job offers from other clubs depending on manager reputation/results; offer details (club, budget, board objectives,
  squad strength); accept/decline; moving to a new club; all leagues keep running. (Pending implementation.)
- NOTE: the received attachment was cut off in the middle of this section ("تولّي"). Remaining points not received.

## A12. NO player/manager history (decision 2026-11-22) - REMOVES earlier items
- Removed: player past-season stats/history, player OVR/potential history, player awards/transfer history on the profile,
  manager personal history/statistics. The player profile shows CURRENT season only.
- Kept (needed for gameplay): current-season stats, current contract, club-level champions record, transfer window
  activity of the current season, internal manager reputation number (drives job offers, not shown as history).
- Implementation: previous seasons' per-player stats and match details are purged at season rollover
  (after being handed to the development step). Tested.
