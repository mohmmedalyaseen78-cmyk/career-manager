"""Attributes, position-weighted OVR, and consistent attribute generation.

All numbers here are GRAFECO internal ratings (1-99). They are NOT EA ratings.
"""
import math
import random

ATTRS = [
    "acceleration", "sprint_speed",
    "finishing", "shot_power", "long_shots", "volleys", "penalties", "positioning",
    "vision", "crossing", "short_passing", "long_passing", "fk_accuracy", "curve",
    "agility", "balance", "reactions", "ball_control", "dribbling", "composure",
    "interceptions", "heading_accuracy", "def_awareness", "standing_tackle", "sliding_tackle",
    "jumping", "stamina", "strength", "aggression",
    "gk_diving", "gk_handling", "gk_kicking", "gk_reflexes", "gk_speed", "gk_positioning",
]
IDX = {a: i for i, a in enumerate(ATTRS)}
N_ATTRS = len(ATTRS)  # 35
GK_ATTRS = [a for a in ATTRS if a.startswith("gk_")]
OUT_IDX = [i for i, a in enumerate(ATTRS) if not a.startswith("gk_")]
GK_IDX = [IDX[a] for a in GK_ATTRS]

POSITIONS = ["GK", "CB", "LB", "RB", "CDM", "CM", "CAM", "LM", "RM", "LW", "RW", "ST"]

_W = {
    "ST": dict(finishing=5, positioning=4, shot_power=2, volleys=1, composure=2, ball_control=2.5, dribbling=1.5,
               sprint_speed=2, acceleration=2, strength=1, heading_accuracy=1.5, reactions=2, penalties=.5,
               short_passing=1, agility=1, long_shots=1, vision=.5, jumping=.5, stamina=.5, aggression=.5),
    "CB": dict(def_awareness=5, standing_tackle=4.5, interceptions=4, heading_accuracy=4, strength=3.5,
               sliding_tackle=2.5, aggression=2, jumping=2, short_passing=1.5, composure=1.5, reactions=1.5,
               sprint_speed=1.5, acceleration=1, long_passing=1, ball_control=1, stamina=1),
    "LB": dict(stamina=3, sprint_speed=3, acceleration=3, def_awareness=3, standing_tackle=3, interceptions=2.5,
               crossing=2.5, short_passing=2, dribbling=2, ball_control=2, agility=1.5, sliding_tackle=1.5,
               reactions=1.5, strength=1, aggression=1.5, long_passing=1),
    "CDM": dict(def_awareness=4, interceptions=4, standing_tackle=4, short_passing=3.5, long_passing=3, stamina=3,
                strength=2.5, aggression=2.5, ball_control=2, vision=2, reactions=2, composure=2,
                sliding_tackle=1.5, heading_accuracy=1),
    "CM": dict(short_passing=4.5, vision=3.5, ball_control=3.5, long_passing=3, stamina=3, dribbling=2.5,
               reactions=2, composure=2, interceptions=1.5, def_awareness=1.5, standing_tackle=1.5,
               long_shots=1.5, agility=1.5, balance=1, acceleration=1, strength=1),
    "CAM": dict(vision=4.5, short_passing=4.5, ball_control=4, dribbling=4, agility=2.5, long_shots=2.5,
                finishing=2, positioning=3, reactions=2.5, composure=2.5, curve=1, long_passing=1.5,
                acceleration=1.5, balance=1.5, shot_power=1),
    "LM": dict(crossing=3, dribbling=3.5, acceleration=3.5, sprint_speed=3, short_passing=3, ball_control=3.5,
               agility=2.5, vision=2, stamina=2, balance=1.5, long_shots=1.5, finishing=1.5, reactions=1.5, curve=1),
    "LW": dict(acceleration=4, sprint_speed=3.5, dribbling=4.5, agility=3, ball_control=4, crossing=2.5,
               finishing=2.5, short_passing=2.5, positioning=2.5, balance=2, reactions=2, vision=1.5, curve=1,
               composure=1.5, long_shots=1.5),
    "GK": dict(gk_diving=5, gk_handling=4.5, gk_reflexes=5, gk_positioning=4.5, gk_kicking=2, gk_speed=1),
}
_W["RB"], _W["RM"], _W["RW"] = _W["LB"], _W["LM"], _W["LW"]

WEIGHTS = {}
for _pos, _d in _W.items():
    _v = [0.0] * N_ATTRS
    if _pos == "GK":
        for k, w in _d.items():
            _v[IDX[k]] = w
    else:
        for i in OUT_IDX:
            _v[i] = 0.3
        for k, w in _d.items():
            _v[IDX[k]] = w
    WEIGHTS[_pos] = _v
_WSUM = {p: sum(v) for p, v in WEIGHTS.items()}

# player archetypes: attribute bonuses (points) that make players of one position differ
ARCHETYPES = {
    "ST": [("poacher", dict(finishing=8, positioning=8, strength=-8, heading_accuracy=-4, stamina=-4)),
           ("target_man", dict(strength=12, jumping=10, heading_accuracy=14, sprint_speed=-12, acceleration=-12,
                               agility=-8, dribbling=-6)),
           ("pacy_forward", dict(sprint_speed=10, acceleration=10, strength=-6, heading_accuracy=-6)),
           ("complete", dict())],
    "CB": [("stopper", dict(aggression=8, standing_tackle=5, strength=6, sprint_speed=-4)),
           ("ball_playing", dict(short_passing=10, long_passing=10, vision=8, composure=6, aggression=-6)),
           ("pacy_cb", dict(sprint_speed=10, acceleration=8, strength=-6)), ("standard", dict())],
    "FB": [("attacking_fb", dict(crossing=8, dribbling=6, stamina=6, def_awareness=-6)),
           ("defensive_fb", dict(def_awareness=6, standing_tackle=6, crossing=-6)), ("standard", dict())],
    "CDM": [("destroyer", dict(aggression=8, standing_tackle=6, strength=6, short_passing=-5)),
            ("regista", dict(long_passing=10, vision=8, short_passing=6, aggression=-6, strength=-4)),
            ("standard", dict())],
    "CM": [("box_to_box", dict(stamina=10, strength=4, finishing=3)),
           ("playmaker", dict(vision=8, short_passing=6, long_passing=6, stamina=-4)), ("standard", dict())],
    "CAM": [("playmaker", dict(vision=8, short_passing=6, long_passing=4)),
            ("shadow_striker", dict(finishing=8, positioning=6, long_shots=4)), ("standard", dict())],
    "W": [("inside_forward", dict(finishing=6, positioning=5, crossing=-6)),
          ("classic_winger", dict(crossing=9, sprint_speed=5, finishing=-5)), ("standard", dict())],
    "GK": [("shot_stopper", dict(gk_reflexes=5, gk_diving=4, gk_kicking=-4)),
           ("sweeper_keeper", dict(gk_kicking=8, gk_speed=8, gk_handling=-3)), ("standard", dict())],
}
_ARCH_KEY = {"ST": "ST", "CB": "CB", "LB": "FB", "RB": "FB", "CDM": "CDM", "CM": "CM", "CAM": "CAM",
             "LM": "W", "RM": "W", "LW": "W", "RW": "W", "GK": "GK"}


def pack(values):
    return bytes(max(1, min(99, int(round(v)))) for v in values)


def unpack(blob):
    return list(blob)


def ovr_at(attrs, pos):
    """OVR of an attribute vector (list or bytes) when played at `pos`."""
    w = WEIGHTS[pos]
    return int(round(sum(a * x for a, x in zip(w, attrs)) / _WSUM[pos]))


def main_stats(attrs):
    """Six face stats (outfield) derived from sub-attributes."""
    g = lambda n: attrs[IDX[n]]
    return {
        "PAC": round(.45 * g("acceleration") + .55 * g("sprint_speed")),
        "SHO": round(.45 * g("finishing") + .2 * g("long_shots") + .2 * g("shot_power") + .05 * g("positioning")
                     + .05 * g("penalties") + .05 * g("volleys")),
        "PAS": round(.2 * g("vision") + .2 * g("crossing") + .05 * g("fk_accuracy") + .35 * g("short_passing")
                     + .15 * g("long_passing") + .05 * g("curve")),
        "DRI": round(.1 * g("agility") + .05 * g("balance") + .05 * g("reactions") + .35 * g("ball_control")
                     + .5 * g("dribbling")),
        "DEF": round(.2 * g("interceptions") + .1 * g("heading_accuracy") + .3 * g("def_awareness")
                     + .3 * g("standing_tackle") + .1 * g("sliding_tackle")),
        "PHY": round(.05 * g("jumping") + .25 * g("stamina") + .5 * g("strength") + .2 * g("aggression")),
    }


def gk_stats(attrs):
    g = lambda n: attrs[IDX[n]]
    return {"DIV": g("gk_diving"), "HAN": g("gk_handling"), "KIC": g("gk_kicking"),
            "REF": g("gk_reflexes"), "SPE": g("gk_speed"), "POS": g("gk_positioning")}


def _clamp(x):
    return max(1.0, min(99.0, x))


def generate_attrs(pos, target_ovr, rng, archetype=None):
    """Attribute vector whose position-weighted OVR equals target_ovr exactly.
    Shape follows position weights + archetype + individual physical traits + noise."""
    w = WEIGHTS[pos]
    target_ovr = max(20, min(97, int(target_ovr)))
    if archetype is None:
        archetype = rng.choice(ARCHETYPES[_ARCH_KEY[pos]])
    bonus = {IDX[k]: v for k, v in archetype[1].items()}
    pace_bias = rng.gauss(0, 6)
    power_bias = rng.gauss(0, 6)
    noise = [rng.gauss(0, 4) for _ in range(N_ATTRS)]
    for k in ("acceleration", "sprint_speed"):
        bonus[IDX[k]] = bonus.get(IDX[k], 0) + pace_bias
    for k in ("strength", "jumping", "aggression"):
        bonus[IDX[k]] = bonus.get(IDX[k], 0) + power_bias
    for k in ("agility", "balance"):
        bonus[IDX[k]] = bonus.get(IDX[k], 0) - power_bias * 0.5

    keys = GK_IDX if pos == "GK" else OUT_IDX
    wm = sum(w[i] for i in keys) / len(keys)
    emph = {i: max(-1.0, min(2.2, w[i] / wm - 1)) for i in keys}
    spread = 11.0

    def build(base):
        v = [0.0] * N_ATTRS
        for i in keys:
            v[i] = _clamp(base + spread * emph[i] + bonus.get(i, 0) + noise[i])
        return v

    lo, hi = -40.0, 140.0
    for _ in range(40):
        mid = (lo + hi) / 2
        v = build(mid)
        o = sum(a * x for a, x in zip(w, v)) / _WSUM[pos]
        lo, hi = (mid, hi) if o < target_ovr else (lo, mid)
    v = build((lo + hi) / 2)

    if pos == "GK":
        for i in OUT_IDX:
            v[i] = _clamp(18 + 0.22 * target_ovr + rng.gauss(0, 6) + bonus.get(i, 0) * 0.3)
        v[IDX["reactions"]] = _clamp(v[IDX["gk_reflexes"]] - 6 + rng.gauss(0, 3))
        v[IDX["jumping"]] = _clamp(45 + 0.2 * target_ovr + rng.gauss(0, 6))
        v[IDX["strength"]] = _clamp(45 + 0.2 * target_ovr + rng.gauss(0, 6))
    else:
        for i in GK_IDX:
            v[i] = _clamp(rng.uniform(6, 15))
    out = [int(round(x)) for x in v]
    # exact-match polish: nudge the most influential attributes by +-1
    order = sorted(keys, key=lambda i: -w[i])
    for _ in range(80):
        cur = ovr_at(out, pos)
        if cur == target_ovr:
            break
        d = 1 if cur < target_ovr else -1
        for i in order:
            if 1 <= out[i] + d <= 99:
                out[i] += d
                break
        else:
            break
    return out, archetype[0]


def check_consistency(attrs, pos, ovr):
    """Return list of problems (empty = consistent)."""
    problems = []
    if len(attrs) != N_ATTRS:
        return ["bad length"]
    if any(not (1 <= a <= 99) for a in attrs):
        problems.append("attribute out of 1..99")
    if ovr_at(attrs, pos) != ovr:
        problems.append(f"ovr mismatch {ovr_at(attrs, pos)} != {ovr}")
    if pos != "GK":
        if abs(attrs[IDX["acceleration"]] - attrs[IDX["sprint_speed"]]) > 30:
            problems.append("acceleration/sprint too far apart")
        if max(attrs[i] for i in GK_IDX) > 20:
            problems.append("outfield player with GK skills")
    else:
        if max(attrs[IDX["finishing"]], attrs[IDX["dribbling"]]) > attrs[IDX["gk_reflexes"]]:
            problems.append("goalkeeper better outfield than GK skill")
    return problems
