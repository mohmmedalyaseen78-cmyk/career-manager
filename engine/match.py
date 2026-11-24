"""Match engines: detailed (user's club) and fast statistical (rest of the world). Pure functions, seeded."""
import math
import random

from . import attrs as A

FORMATIONS = {
    "4-3-3": ["GK", "LB", "CB", "CB", "RB", "CDM", "CM", "CM", "LW", "ST", "RW"],
    "4-4-2": ["GK", "LB", "CB", "CB", "RB", "LM", "CM", "CM", "RM", "ST", "ST"],
    "4-2-3-1": ["GK", "LB", "CB", "CB", "RB", "CDM", "CDM", "LW", "CAM", "RW", "ST"],
    "3-5-2": ["GK", "CB", "CB", "CB", "LM", "CM", "CDM", "CM", "RM", "ST", "ST"],
    "4-1-4-1": ["GK", "LB", "CB", "CB", "RB", "CDM", "LM", "CM", "CM", "RM", "ST"],
    "3-4-3": ["GK", "CB", "CB", "CB", "LM", "CM", "CM", "RM", "LW", "ST", "RW"],
}
ATT_W = dict(ST=1.0, LW=.85, RW=.85, CAM=.75, LM=.65, RM=.65, CM=.45, CDM=.2, LB=.3, RB=.3, CB=.05, GK=0)
DEF_W = dict(CB=1.0, CDM=.85, LB=.7, RB=.7, CM=.5, LM=.3, RM=.3, CAM=.25, LW=.15, RW=.15, ST=.05, GK=1.4)
MID_W = dict(CM=1.0, CDM=.9, CAM=.9, LM=.6, RM=.6, LW=.3, RW=.3, LB=.2, RB=.2, ST=.15, CB=.1, GK=0)
GROUP = dict(GK="G", CB="D", LB="D", RB="D", CDM="M", CM="M", CAM="M", LM="M", RM="M", LW="F", RW="F", ST="F")
DEFAULT_TACTICS = dict(mentality="balanced", pressing=50, tempo=50)
MAX_SUBS = 5


def poisson(rng, lam):
    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= L:
            return k
        k += 1


def available(p):
    return p["injury_days"] <= 0 and p["status"] == 0


def auto_lineup(squad, formation="4-3-3"):
    """Best available XI for formation: list of (slot_pos, player). Greedy by position-specific OVR."""
    slots = FORMATIONS[formation]
    pool = [p for p in squad if available(p)]
    chosen, used = [], set()
    # fill scarce roles first (GK, then CB, wide, etc.)
    order = sorted(range(len(slots)), key=lambda i: (slots[i] != "GK", slots[i] not in ("CB", "ST")))
    res = [None] * len(slots)
    for i in order:
        sp = slots[i]
        best, bs = None, -1
        for p in pool:
            if p["id"] in used:
                continue
            s = A.ovr_at(p["attrs"], sp) - (25 if (sp == "GK") != (p["pos"] == "GK") else 0) \
                - (0 if p["pos"] == sp or sp in p["pos2"].split(",") else 2) + p["fitness"] / 100.0
            if s > bs:
                best, bs = p, s
        used.add(best["id"])
        res[i] = (sp, best)
    bench = sorted([p for p in pool if p["id"] not in used], key=lambda p: -p["ovr"])[:9]
    return res, bench


def _eff(p, slot):
    return (A.ovr_at(p["attrs"], slot) * (0.92 + 0.08 * p["fitness"] / 100.0)
            + (p["form"] - 70) * 0.04 + (p["morale"] - 70) * 0.02)


def ratings(on_pitch, tactics):
    """on_pitch: list of dict(slot, eff, [am, dm]). Returns att, mid, dfn, gk.
    am/dm are per-player attack/defence multipliers set by player instructions."""
    def wavg(W, key=None):
        ws = [W[x["slot"]] * (x.get(key, 1.0) if key else 1.0) for x in on_pitch]
        tw = sum(ws) or 1
        return sum(x["eff"] * w for x, w in zip(on_pitch, ws)) / tw
    att, mid, dfn = wavg(ATT_W, "am"), wavg(MID_W), wavg(DEF_W, "dm")
    m = tactics.get("mentality", "balanced")
    adj = {"attacking": (2.5, -2.5), "defensive": (-2.5, 2.5)}.get(m, (0, 0))
    att += adj[0]
    dfn += adj[1]
    mid += (tactics.get("pressing", 50) - 50) * 0.03 + (tactics.get("tempo", 50) - 50) * 0.01
    gk = next((x["eff"] for x in on_pitch if x["slot"] == "GK"), 40)
    return att, mid, dfn, gk


INSTRUCTIONS = {"balanced": (1.0, 1.0), "forward": (1.3, 0.8), "back": (0.7, 1.25)}


class _Side:
    def __init__(self, club_id, lineup, bench, tactics):
        self.club_id = club_id
        self.tactics = {**DEFAULT_TACTICS, **(tactics or {})}
        self.on = [dict(slot=s, p=p, eff=_eff(p, s), on=0, off=None) for s, p in lineup]
        self.bench = list(bench)
        self.all = {x["p"]["id"]: x for x in self.on}
        self.subs = 0
        self.yellow = {}
        self.stats = dict(shots=0, on_target=0, corners=0, fouls=0, offsides=0, yc=0, rc=0, saves=0, xg=0.0)
        self.goals = 0
        self.dirty = True
        self._r = None

    def r(self):
        if self.dirty:
            self._r = ratings(self.on, self.tactics)
            self.dirty = False
        return self._r

    def remove(self, x, minute):
        x["off"] = minute
        self.on.remove(x)
        self.dirty = True

    def add(self, p, slot, minute):
        x = dict(slot=slot, p=p, eff=_eff(p, slot), on=minute, off=None)
        self.on.append(x)
        self.all[p["id"]] = x
        self.bench = [b for b in self.bench if b["id"] != p["id"]]
        self.dirty = True
        return x


def _pick(rng, items, weights):
    tot = sum(weights)
    if tot <= 0:
        return rng.choice(items)
    r = rng.random() * tot
    for it, w in zip(items, weights):
        r -= w
        if r <= 0:
            return it
    return items[-1]


class MatchSession:
    """Steppable detailed match. ONE engine for every viewing mode:
    - instant / skip: MatchSession(...).finish()
    - live: advance(until=minute) or advance(stop_on_event=True), pause = just stop calling, resume = call again
    - interventions: substitute(), set_tactics(), set_formation(), set_instruction()
    Without interventions the result depends only on the seed, regardless of how it was chunked."""

    def __init__(self, home, away, seed, settings=None, auto=(True, True)):
        self.cfg = dict(injury_rate=1.0, home_adv=1.07, max_subs=MAX_SUBS)
        self.cfg.update(settings or {})
        self.rng = random.Random(seed)
        self.seed = seed
        self.S = [_Side(home["club_id"], home["lineup"], home["bench"], home.get("tactics")),
                  _Side(away["club_id"], away["lineup"], away["bench"], away.get("tactics"))]
        self.events, self.log = [], []
        self.h1, self.h2 = 45 + self.rng.randint(1, 4), 90 + self.rng.randint(2, 7)
        self.total, self.idx = self.h2, 0
        self.auto = list(auto)  # AI-controlled sides make planned subs / tactical shifts
        self._start = {p["id"] for _, p in home["lineup"]} | {p["id"] for _, p in away["lineup"]}
        self._res = None

    # ---- state
    def shown(self, idx):
        return min(idx, 45) if idx <= self.h1 else min(90, idx - (self.h1 - 45))

    @property
    def minute(self):
        return self.shown(self.idx) if self.idx else 0

    @property
    def finished(self):
        return self.idx >= self.total

    @property
    def at_half_time(self):
        return self.idx == self.h1

    def score(self):
        return (self.S[0].goals, self.S[1].goals)

    def _ev(self, minute, typ, side, p1=None, p2=None):
        self.events.append(dict(minute=minute, type=typ, club_id=self.S[side].club_id,
                                player_id=p1["id"] if p1 else None, player2_id=p2["id"] if p2 else None))

    # ---- simulation
    def _shot(self, minute, i, forced_pen=False):
        rng, a, o = self.rng, self.S[i], self.S[1 - i]
        att, mid, dfn, gk = a.r()
        oatt, omid, odfn, ogk = o.r()
        outfield = [x for x in a.on if x["slot"] != "GK"]
        if not outfield:
            return
        shooter = _pick(rng, outfield, [ATT_W[x["slot"]] ** 1.5 * x.get("am", 1.0) + 0.02 for x in outfield])
        fin = shooter["p"]["attrs"][A.IDX["finishing"]]
        a.stats["shots"] += 1
        if forced_pen:
            p_goal = min(0.9, max(0.6, 0.78 + (shooter["p"]["attrs"][A.IDX["penalties"]] - 65) / 300))
            scored = rng.random() < p_goal
            self._ev(minute, "pen_goal" if scored else "pen_miss", i, shooter["p"])
            if scored:
                a.goals += 1
                a.stats["on_target"] += 1
            return
        p_ot = min(0.5, max(0.2, 0.34 + (fin - 60) / 400))
        p_goal_ot = 0.30 * math.exp((shooter["eff"] - ogk) / 55) * math.exp((att - odfn) / 120)
        p_goal_ot = min(0.7, max(0.08, p_goal_ot))
        a.stats["xg"] += p_ot * p_goal_ot
        if rng.random() < p_ot:
            a.stats["on_target"] += 1
            if rng.random() < p_goal_ot:
                a.goals += 1
                self._ev(minute, "goal", i, shooter["p"])
                if rng.random() < 0.78:
                    cands = [x for x in a.on if x is not shooter and x["slot"] != "GK"]
                    if cands:
                        ass = _pick(rng, cands, [(x["p"]["attrs"][A.IDX["vision"]] +
                                                  x["p"]["attrs"][A.IDX["short_passing"]]) * (ATT_W[x["slot"]] + .2)
                                                 for x in cands])
                        self.events[-1]["player2_id"] = ass["p"]["id"]
            else:
                o.stats["saves"] += 1
                gkx = next((x for x in o.on if x["slot"] == "GK"), None)
                if gkx:
                    gkx["saves"] = gkx.get("saves", 0) + 1
                if rng.random() < 0.25:
                    a.stats["corners"] += 1
        elif rng.random() < 0.3:
            a.stats["corners"] += 1

    def _auto_sub(self, i, minute, out_x):
        s = self.S[i]
        if s.subs >= self.cfg["max_subs"] or not s.bench:
            return False
        g = GROUP[out_x["slot"]]
        cands = [b for b in s.bench if available(b) and GROUP.get(b["pos"]) == g] or \
                ([b for b in s.bench if available(b) and b["pos"] != "GK"] if g != "G" else [])
        if not cands:
            return False
        inn = max(cands, key=lambda b: A.ovr_at(b["attrs"], out_x["slot"]))
        return self._do_sub(i, minute, out_x, inn)

    def _do_sub(self, i, minute, out_x, inn):
        s = self.S[i]
        slot = out_x["slot"]
        s.remove(out_x, minute)
        s.add(inn, slot, minute)
        s.subs += 1
        self._ev(minute, "sub", i, out_x["p"], inn)
        return True

    def step(self):
        """Simulate one minute-tick."""
        rng, cfg = self.rng, self.cfg
        self.idx += 1
        minute, shown, S = self.idx, self.shown(self.idx), self.S
        for i in (0, 1):
            a, o = S[i], S[1 - i]
            if not a.on or not o.on:
                continue
            att, mid, dfn, gk = a.r()
            oatt, omid, odfn, ogk = o.r()
            lam = 15.0 * math.exp((att - odfn) / 38 + (mid - omid) / 60) * (cfg["home_adv"] if i == 0 else 1.0)
            deficit = o.goals - a.goals
            if minute > 60 and deficit > 0:
                lam *= 1 + 0.06 * min(deficit, 3)
            if rng.random() < lam / self.total:
                self._shot(shown, i)
        for i in (0, 1):
            a = S[i]
            if not a.on:
                continue
            if rng.random() < 0.13:
                a.stats["fouls"] += 1
                defs = [x for x in a.on if x["slot"] != "GK"]
                if defs:
                    cm = _pick(rng, defs, [x["p"]["attrs"][A.IDX["aggression"]] + DEF_W[x["slot"]] * 30
                                           for x in defs])
                    r = rng.random()
                    if r < 0.004:
                        a.stats["rc"] += 1
                        self._ev(shown, "rc", i, cm["p"])
                        a.remove(cm, shown)
                    elif r < 0.004 + 0.14 * (cm["p"]["attrs"][A.IDX["aggression"]] / 60):
                        pid = cm["p"]["id"]
                        a.yellow[pid] = a.yellow.get(pid, 0) + 1
                        a.stats["yc"] += 1
                        self._ev(shown, "yc", i, cm["p"])
                        if a.yellow[pid] == 2:
                            a.stats["rc"] += 1
                            self._ev(shown, "rc", i, cm["p"])
                            a.remove(cm, shown)
                    if rng.random() < 0.012 and S[1 - i].on:
                        self._shot(shown, 1 - i, forced_pen=True)
            if rng.random() < 2.0 / self.total:
                a.stats["offsides"] += 1
            for x in list(a.on):
                if rng.random() < 0.00004 * cfg["injury_rate"]:
                    self._ev(shown, "injury", i, x["p"])
                    if not (self.auto[i] and self._auto_sub(i, shown, x)):
                        # user side: injured player must leave; user can bring a sub in via substitute()
                        a.remove(x, shown)
                        a.vacant = getattr(a, "vacant", []) + [x["slot"]]
        if minute in (58, 68, 78, self.h1 + 14):
            for i in (0, 1):
                if not self.auto[i]:
                    continue
                a = S[i]
                tired = sorted([x for x in a.on if x["slot"] != "GK"], key=lambda x: x["p"]["fitness"])
                if tired and a.subs < cfg["max_subs"] and rng.random() < 0.85:
                    self._auto_sub(i, shown, tired[0])
        # AI tactical adaptation (same rules the user's interventions compete against)
        if minute in (self.h1 + 25, self.h1 + 35):
            for i in (0, 1):
                if self.auto[i]:
                    d = S[1 - i].goals - S[i].goals
                    S[i].tactics["mentality"] = "attacking" if d > 0 else "defensive" if d < -0 and d <= -1 \
                        else S[i].tactics["mentality"]
                    S[i].dirty = True

    def advance(self, until=None, stop_on_event=False):
        """Run forward. until = displayed minute to stop AFTER (45 = half-time, 90 = full time).
        stop_on_event=True returns right after the first new event. Returns the new events."""
        n0 = len(self.events)
        while not self.finished:
            if until is not None and self.shown(self.idx + 1) > until:
                break
            self.step()
            if stop_on_event and len(self.events) > n0:
                break
        return self.events[n0:]

    def finish(self):
        self.advance()
        return self.result()

    # ---- interventions (take effect on the very next tick; recorded in self.log)
    def substitute(self, side, out_id, in_id):
        s, m = self.S[side], self.minute
        x = s.all.get(out_id)
        inn = next((b for b in s.bench if b["id"] == in_id), None)
        if x is None or x not in s.on:
            return "out_player_not_on_pitch"
        if inn is None:
            return "in_player_not_on_bench"
        if not available(inn):
            return "in_player_unavailable"
        if s.subs >= self.cfg["max_subs"]:
            return "no_substitutions_left"
        if (x["slot"] == "GK") != (inn["pos"] == "GK"):
            return "goalkeeper_swap_needs_goalkeeper"
        self._do_sub(side, m, x, inn)
        self.log.append((m, side, "sub", out_id, in_id))
        return "ok"

    def fill_vacancy(self, side, in_id):
        """After an injury with no auto-sub, bring a bench player into the vacated slot."""
        s, m = self.S[side], self.minute
        inn = next((b for b in s.bench if b["id"] == in_id), None)
        if not getattr(s, "vacant", []) or inn is None or not available(inn) or s.subs >= self.cfg["max_subs"]:
            return "not_possible"
        slot = s.vacant.pop(0)
        s.add(inn, slot, m)
        s.subs += 1
        self._ev(m, "sub", side, None, inn)
        return "ok"

    def set_tactics(self, side, mentality=None, pressing=None, tempo=None):
        t = self.S[side].tactics
        if mentality in ("defensive", "balanced", "attacking"):
            t["mentality"] = mentality
        if pressing is not None:
            t["pressing"] = max(0, min(100, pressing))
        if tempo is not None:
            t["tempo"] = max(0, min(100, tempo))
        self.S[side].dirty = True
        self.log.append((self.minute, side, "tactics", dict(t)))

    def set_instruction(self, side, player_id, instr):
        x = self.S[side].all.get(player_id)
        if x is None or x not in self.S[side].on or instr not in INSTRUCTIONS:
            return "invalid"
        x["am"], x["dm"] = INSTRUCTIONS[instr]
        self.S[side].dirty = True
        self.log.append((self.minute, side, "instruction", player_id, instr))
        return "ok"

    def set_formation(self, side, formation):
        s = self.S[side]
        if formation not in FORMATIONS or len(s.on) != 11:
            return "not_possible"
        slots = FORMATIONS[formation]
        free, new = list(s.on), {}
        for slot in sorted(range(11), key=lambda k: slots[k] != "GK"):
            sp = slots[slot]
            pool = [x for x in free if (sp == "GK") == (x["p"]["pos"] == "GK" or x["slot"] == "GK")] or free
            best = max(pool, key=lambda x: A.ovr_at(x["p"]["attrs"], sp))
            new[id(best)] = sp
            free.remove(best)
        for x in s.on:
            x["slot"] = new[id(x)]
            x["eff"] = _eff(x["p"], x["slot"])
        s.dirty = True
        self.log.append((self.minute, side, "formation", formation))
        return "ok"

    # ---- final package
    def result(self):
        if self._res is not None:
            return self._res
        rng, S, events = self.rng, self.S, self.events
        gh, ga = S[0].goals, S[1].goals
        players = {}
        for i, s in enumerate(S):
            won = (gh > ga) if i == 0 else (ga > gh)
            lost = (gh < ga) if i == 0 else (ga < gh)
            conceded = S[1 - i].goals
            team_ovr = sum(x["p"]["ovr"] for x in s.all.values()) / len(s.all)
            for pid, x in s.all.items():
                end = x["off"] if x["off"] is not None else 90
                mins = max(0, min(90, end) - x["on"])
                g = sum(1 for e in events if e["type"] in ("goal", "pen_goal") and e["player_id"] == pid)
                asst = sum(1 for e in events if e["type"] == "goal" and e["player2_id"] == pid)
                yc = sum(1 for e in events if e["type"] == "yc" and e["player_id"] == pid)
                rc = sum(1 for e in events if e["type"] == "rc" and e["player_id"] == pid)
                pm = sum(1 for e in events if e["type"] == "pen_miss" and e["player_id"] == pid)
                grp = GROUP[x["slot"]]
                rt = 6.0 + (0.25 if won else -0.25 if lost else 0)
                rt += 0.9 * g * (1.0 if grp == "F" else 1.15) + 0.6 * asst - 0.5 * pm - 0.25 * yc - 1.6 * rc
                rt += (x["p"]["ovr"] - team_ovr) / 70.0
                if grp in ("D", "G"):
                    rt += 0.4 if conceded == 0 else -0.12 * conceded
                if grp == "G":
                    rt += 0.12 * x.get("saves", 0)
                rt += rng.gauss(0, 0.28)
                if mins < 15:
                    rt = 6.0 + (rt - 6.0) * mins / 15.0
                players[pid] = dict(player_id=pid, club_id=s.club_id, slot=x["slot"], minutes=mins,
                                    rating=round(max(3.0, min(10.0, rt)), 1), goals=g, assists=asst, yc=yc, rc=rc,
                                    saves=x.get("saves", 0) if grp == "G" else 0)
        top = max(players.values(), key=lambda p: (p["rating"], p["goals"]))
        poss = max(30, min(70, 50 + (S[0].r()[1] - S[1].r()[1]) * 1.4 + rng.gauss(0, 2)))
        team_stats = []
        for i, s in enumerate(S):
            st = dict(s.stats)
            st["xg"] = round(st["xg"], 2)
            st["possession"] = round(poss if i == 0 else 100 - poss)
            st["pass_accuracy"] = max(60, min(93, round(76 + (s.r()[1] - 70) * 0.4 + rng.gauss(0, 2))))
            team_stats.append(dict(club_id=s.club_id, **st))
        self._res = dict(seed=self.seed, score=(gh, ga), events=events, team_stats=team_stats,
                         players=list(players.values()), motm=top["player_id"],
                         added=(self.h1 - 45, self.h2 - 90), interventions=list(self.log))
        return self._res


def simulate_detailed(home, away, seed, settings=None, auto=(True, True)):
    """One-shot wrapper (instant result / skip). Same engine as the live session."""
    return MatchSession(home, away, seed, settings, auto).finish()


def team_strength(squad, formation="4-3-3"):
    lineup, _ = auto_lineup(squad, formation)
    on = [dict(slot=s, eff=_eff(p, s)) for s, p in lineup]
    att, mid, dfn, gk = ratings(on, DEFAULT_TACTICS)
    return dict(att=att, mid=mid, dfn=dfn, gk=gk, ovr=sum(x["eff"] for x in on) / 11)


def simulate_fast(sh, sa, rng, home_adv=1.07):
    """Poisson goals from strengths (dicts from team_strength). Cheap; no events."""
    lh = 1.30 * home_adv * math.exp(((sh["att"] - sa["dfn"]) + (sh["mid"] - sa["mid"]) * 0.5) / 38.0)
    la = 1.30 * math.exp(((sa["att"] - sh["dfn"]) + (sa["mid"] - sh["mid"]) * 0.5) / 38.0)
    return poisson(rng, min(lh, 6)), poisson(rng, min(la, 6))


def validate_match(res, home, away):
    """Consistency checks required by the spec. Returns list of problems."""
    probs = []
    ev = res["events"]
    gh, ga = res["score"]
    ids = {0: {p["id"] for _, p in home["lineup"]} | {p["id"] for p in home["bench"]},
           1: {p["id"] for _, p in away["lineup"]} | {p["id"] for p in away["bench"]}}
    cid = {home["club_id"]: 0, away["club_id"]: 1}
    cnt = [0, 0]
    sent_off, subbed_out, subbed_in = set(), set(), set()
    subs = [0, 0]
    start = {p["id"] for _, p in home["lineup"]} | {p["id"] for _, p in away["lineup"]}
    for e in ev:
        side = cid[e["club_id"]]
        if e["type"] in ("goal", "pen_goal"):
            cnt[side] += 1
            if e["player_id"] in sent_off:
                probs.append("sent-off player scored")
            if e["player_id"] in subbed_out:
                probs.append("subbed-out player scored")
            if e["player_id"] not in ids[side]:
                probs.append("scorer not in squad")
            if e["type"] == "goal" and e["player2_id"] == e["player_id"]:
                probs.append("self assist")
            if e["player_id"] not in start and e["player_id"] not in subbed_in:
                probs.append("scorer never entered")
        if e["type"] == "rc":
            sent_off.add(e["player_id"])
        if e["type"] == "sub":
            subs[side] += 1
            if e["player2_id"] in subbed_in or e["player2_id"] in subbed_out or e["player2_id"] in start:
                probs.append("illegal sub-in")
            if e["player_id"] is not None:
                subbed_out.add(e["player_id"])
            subbed_in.add(e["player2_id"])
    if tuple(cnt) != (gh, ga):
        probs.append(f"events {cnt} != score {(gh, ga)}")
    if max(subs) > MAX_SUBS:
        probs.append("too many subs")
    played = {p["player_id"] for p in res["players"]}
    for p in res["players"]:
        if p["minutes"] <= 0 and (p["goals"] or p["assists"]):
            probs.append("zero-minute contributor")
    if res["motm"] not in played:
        probs.append("motm not a participant")
    return probs
