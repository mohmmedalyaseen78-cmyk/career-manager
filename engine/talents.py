"""Youth talent generation (Arabic names, rare elite talents) and dynamic development."""
import math
import random
from datetime import date

from . import attrs as A
from .names_ar import pick_unique_name, normalize

# (tier, probability, potential range). Elite/exceptional are deliberately very rare.
TIERS = [("ordinary", 0.52, (48, 64)), ("good", 0.30, (64, 72)), ("very_good", 0.13, (72, 79)),
         ("high", 0.045, (79, 85)), ("elite", 0.0045, (85, 90)), ("exceptional", 0.0005, (90, 95))]
GROWTH = [(0, 0.22), (1, 0.56), (2, 0.19), (3, 0.03)]  # slow / normal / fast / exceptional
GROWTH_AR = {0: "بطيء", 1: "طبيعي", 2: "سريع", 3: "استثنائي"}
GROWTH_K = {0: 0.18, 1: 0.28, 2: 0.38, 3: 0.50}
POS_W = [("GK", 9), ("CB", 17), ("LB", 6), ("RB", 6), ("CDM", 8), ("CM", 16), ("CAM", 7), ("LM", 2),
         ("RM", 2), ("LW", 5), ("RW", 5), ("ST", 17)]
AGE_W = [(15, .15), (16, .30), (17, .35), (18, .20)]
DEV_FRAC = {15: .45, 16: .55, 17: .65, 18: .74, 19: .82, 20: .88, 21: .93}
ADJ = {"CB": ["CDM", "LB", "RB"], "LB": ["LM", "CB", "LW"], "RB": ["RM", "CB", "RW"], "CDM": ["CM", "CB"],
       "CM": ["CDM", "CAM"], "CAM": ["CM", "LW", "RW", "ST"], "LM": ["LW", "LB"], "RM": ["RW", "RB"],
       "LW": ["LM", "ST", "CAM"], "RW": ["RM", "ST", "CAM"], "ST": ["CAM", "LW", "RW"], "GK": []}
NATIONS = [("local", .45), ("MA", .10), ("DZ", .07), ("TN", .03), ("EG", .06), ("SA", .04), ("JO", .02), ("LB", .02),
           ("SY", .02), ("IQ", .02), ("FR", .05), ("ES", .03), ("DE", .03), ("IT", .03), ("EN", .03)]
LOCAL = {"England": "EN", "Spain": "ES", "Germany": "DE", "Italy": "IT", "France": "FR"}


def _wchoice(rng, pairs):
    r = rng.random() * sum(p for _, p in pairs)
    for v, p in pairs:
        r -= p
        if r <= 0:
            return v
    return pairs[-1][0]


def sample_tier(rng, academy_quality=1.0):
    """academy_quality ~0.5..1.6 scales the upper tiers' probability."""
    probs = []
    for i, (name, p, rng_) in enumerate(TIERS):
        probs.append((name, p * (academy_quality ** (1.5 if i >= 2 else 0)), rng_))
    tot = sum(p for _, p, _ in probs)
    r = rng.random() * tot
    for name, p, r_ in probs:
        r -= p
        if r <= 0:
            return name, r_
    return probs[-1][0], probs[-1][2]


def dev_fraction(age, growth):
    f = DEV_FRAC.get(age, 0.97 if age > 21 else .45)
    return min(0.99, f + {0: -0.05, 1: 0, 2: 0.05, 3: 0.09}[growth])


def market_value(ovr, pot, age):
    eff = ovr + max(0, pot - ovr) * 0.35 * (1.0 if age <= 19 else 0.7 if age <= 22 else 0.4 if age <= 25 else 0)
    v = 100_000 * math.exp(0.155 * (eff - 40))
    if age > 29:
        v *= max(0.1, 1 - 0.12 * (age - 29))
    return int(max(25_000, round(v, -3)))


def weekly_wage(value):
    return int(max(1_500, round(value * 0.0012, -2)))


def _height_weight(pos, age, rng):
    mu, sd = {"GK": (189, 5), "CB": (186, 5.5), "ST": (182, 6.5), "CDM": (180, 5.5), "LB": (178, 5), "RB": (178, 5),
              "CM": (178, 5.5), "CAM": (177, 5.5)}.get(pos, (176, 5.5))
    h = rng.gauss(mu, sd) - max(0, 18 - age) * 1.5
    bmi = rng.gauss(22.3, 1.1) - max(0, 18 - age) * 0.4
    return int(round(h)), int(round(bmi * (h / 100) ** 2))


def generate_youth(rng, used_names, season, club_id, club_country, academy_quality=1.0, next_id=None):
    """Return dict ready for gen_players. Name is a unique random Arabic first+family name."""
    tier, (plo, phi) = sample_tier(rng, academy_quality)
    t = rng.triangular(0, 1, 0.25)  # skewed to the low end of the tier
    pot = int(round(plo + t * (phi - plo)))
    age = _wchoice(rng, AGE_W)
    growth = _wchoice(rng, GROWTH)
    pos = _wchoice(rng, POS_W)
    frac = dev_fraction(age, growth)
    ovr = int(round(25 + (pot - 25) * frac + rng.gauss(0, 2.0)))
    ovr = max(28, min(ovr, pot - 1 if pot > 30 else pot))
    attrs, arch = A.generate_attrs(pos, ovr, rng)
    sec = []
    for p2 in ADJ[pos]:
        if A.ovr_at(attrs, p2) >= ovr - 4 and len(sec) < (3 if rng.random() < 0.1 else 2):
            sec.append(p2)
    nat_pick = _wchoice(rng, NATIONS)
    nat = LOCAL.get(club_country, "EN") if nat_pick == "local" else nat_pick
    foot = "L" if (rng.random() < (0.7 if pos in ("LB", "LW", "LM") else 0.08 if pos in ("RB", "RW", "RM")
                                   else 0.24)) else "R"
    h, w = _height_weight(pos, age, rng)
    name = pick_unique_name(rng, used_names)
    birth = date(season - age, rng.randint(1, 12), rng.randint(1, 28)).isoformat()
    value = market_value(ovr, pot, age)
    d = dict(name=name, name_ar=name, search=normalize(name), birth_date=birth, nationality=nat, pos=pos,
             pos2=",".join(sec), foot=foot, height=h, weight=w, weak_foot=min(5, max(1, int(rng.gauss(2.9, .9)))),
             skill_moves=min(5, max(1, int(rng.gauss(2.6, .9)))), club_id=club_id, shirt=None, ovr=ovr,
             potential=pot, growth=growth, attrs=A.pack(attrs), wage=weekly_wage(value), value=value,
             contract_end=season + rng.randint(2, 4), fitness=rng.randint(88, 100), morale=rng.randint(60, 85),
             gen_season=season, origin_club_id=club_id, tier=tier)
    if next_id is not None:
        d["id"] = next_id
    return d


def season_development(ovr, pot, age, growth, minutes_share, avg_rating, coach_q, morale, injured_days, stability,
                       rng):
    """One-season OVR change. Not automatic with time: depends on playing time, form, coaching, morale,
    injuries and stability. Bounded; may fall short of / exceed potential."""
    if age <= 28:
        gap = pot - ovr
        k = GROWTH_K[growth] * {**{a: 1.0 for a in range(14, 20)}, 20: .9, 21: .8, 22: .65, 23: .5, 24: .4,
                                 25: .3, 26: .25, 27: .2, 28: .15}.get(age, .15)
        play = 0.55 + 0.9 * max(0.0, min(1.0, minutes_share))
        perf = 1 + (avg_rating - 6.5) * 0.12 if avg_rating else 1.0
        coach = 0.85 + 0.3 * max(0.0, min(1.0, coach_q))
        mor = 0.9 + 0.2 * morale / 100
        inj = 1 - min(0.5, injured_days / 300)
        stab = 0.95 + 0.1 * max(0.0, min(1.0, stability))
        delta = max(gap, 0) * k * play * perf * coach * mor * inj * stab + rng.gauss(0, 0.7)
        if gap < 0:
            delta = rng.gauss(0.2, 0.8)
    else:
        decline = {29: .3, 30: .8, 31: 1.2, 32: 1.6, 33: 2.0, 34: 2.4}.get(age, 2.8 if age > 34 else 0)
        keep = (0.75 + 0.5 * max(0.0, min(1.0, coach_q))) * (0.8 + 0.4 * morale / 100)
        delta = -decline / keep + rng.gauss(0, 0.6)
    return int(round(max(-4, min(8, delta)))) + ovr


def update_potential(ovr, pot, age, minutes_share, rng):
    if age <= 23 and ovr >= pot - 2:
        return ovr + rng.randint(1, 4)
    if age >= 19 and minutes_share < 0.1 and pot > ovr + 3:
        return max(ovr + 2, pot - rng.randint(1, 2))
    return pot if age <= 28 else ovr
