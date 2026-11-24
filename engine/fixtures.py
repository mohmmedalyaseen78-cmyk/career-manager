from datetime import date, timedelta


def round_robin(teams):
    """Double round robin (circle method). Returns list of rounds of (home, away)."""
    t = list(teams)
    if len(t) % 2:
        t.append(None)
    n = len(t)
    first = []
    for r in range(n - 1):
        pairs = []
        for i in range(n // 2):
            a, b = t[i], t[n - 1 - i]
            if a is None or b is None:
                continue
            pairs.append((a, b) if (r + i) % 2 == 0 else (b, a))
        first.append(pairs)
        t = [t[0]] + [t[-1]] + t[1:-1]
    second = [[(b, a) for a, b in rnd] for rnd in first]
    return first + second


def season_start(season):
    """First Saturday on/after 12 Aug of the season's start year."""
    d = date(season, 8, 12)
    return d + timedelta(days=(5 - d.weekday()) % 7)


def round_date(season, rnd):
    return (season_start(season) + timedelta(weeks=rnd)).isoformat()
