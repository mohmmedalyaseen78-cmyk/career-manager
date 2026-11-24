"""Realistic AI negotiation (spec ch.44): a pure, seeded, local rule/weight decision engine.

No network, no LLM, no background work: every number is computed only when the user submits something.
A negotiation is ONE JSON-serialisable dict (`state`); functions take and return it, so a negotiation in
progress can be saved in the career DB and resumed.

Stages:  inquiry -> club (fee talks) -> contract (player/agent talks) -> confirm -> done
Kinds:   buy | loan | renewal | free_agent | sell (offer received for the user's player)
         free_agent skips the club stage, renewal starts at the contract stage, loan has a simplified contract stage.

Hard guarantees (tested): negotiation difficulty only changes the OTHER SIDE'S flexibility/patience/information.
It never touches OVR, attributes, budgets or match code. Losing a deal has no global side effect.
"""
import copy
import json
import math
import random

from . import talents as T

ROLES = ("limited", "rotation", "important", "key")
ROLE_RANK = {r: i for i, r in enumerate(ROLES)}
STYLES = ("cooperative", "firm", "hard", "opportunistic")
KINDS = ("buy", "loan", "renewal", "free_agent", "sell")
REASONS = ("value_too_low", "club_unwilling_to_sell", "better_alternatives", "payment_structure",
           "role_unsuitable", "wage_below_expectation", "contract_length_unsuitable", "release_clause_issue",
           "offer_regressed", "negotiation_collapsed", "window_closed", "over_budget", "over_wage_budget",
           "player_unwilling", "price_too_high", "walked_away")

DIFFICULTIES = {
    # flex: how fast the other side concedes; tension: patience cost multiplier; patience: tolerance;
    # hints: 0 none / 1 'close or far' / 2 shows where the other side would settle; info: scouting confidence shift
    # min_mult / wage_mult: tilt on the club's reservation price / the player's wage demand.
    "easy": dict(flex=1.25, tension=0.7, patience=130, hints=2, info=0.15, min_mult=0.97, wage_mult=0.96),
    "normal": dict(flex=1.0, tension=1.0, patience=100, hints=1, info=0.0, min_mult=1.0, wage_mult=1.0),
    "hard": dict(flex=0.8, tension=1.3, patience=100, hints=0, info=-0.10, min_mult=1.04, wage_mult=1.06),
    # realistic: no artificial easing/toughening - numbers come from context only, no hints.
    "realistic": dict(flex=1.0, tension=1.0, patience=100, hints=0, info=0.0, min_mult=1.0, wage_mult=1.0),
}
STYLE_PARAMS = {  # stubbornness (slower concessions), price multiplier, reservation ratio
    "cooperative": dict(stub=0.00, price=0.96, minr=0.88),
    "firm": dict(stub=0.25, price=1.08, minr=0.93),
    "hard": dict(stub=0.45, price=1.20, minr=0.96),
    "opportunistic": dict(stub=0.15, price=1.10, minr=0.91),
}
ROLE_PRICE = {"key": 1.25, "important": 1.10, "rotation": 0.95, "limited": 0.80}
ROLE_APPS_SHARE = {"key": 0.9, "important": 0.75, "rotation": 0.45, "limited": 0.15}
GOALS_BY_POS = {"ST": 14, "LW": 9, "RW": 9, "CAM": 7, "LM": 6, "RM": 6, "CM": 4, "CDM": 2, "LB": 2, "RB": 2,
                "CB": 2, "GK": 0}
MAX_HISTORY = 8


class NegotiationError(ValueError):
    pass


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def _r(*parts):
    return random.Random(":".join(str(p) for p in parts))


# ===================================================================== valuation
def intrinsic_value(p):
    return p.get("value") or T.market_value(p["ovr"], p["potential"], p["age"])


def info_confidence(ctx):
    d = DIFFICULTIES[ctx["difficulty"]]
    return _clamp(0.35 + 0.2 * ctx.get("scouting", 0) + d["info"], 0.1, 0.95)


def market_estimate(ctx):
    """What the USER sees before/without full scouting: a RANGE with a confidence, not the true value.
    The range is deliberately not centred exactly on the true value when confidence is low."""
    p = ctx["player"]
    v = intrinsic_value(p)
    conf = info_confidence(ctx)
    r = _r(ctx["seed"], p["id"], "estimate")
    bias = (r.random() - 0.5) * 0.5 * (1 - conf)
    centre = v * (1 + bias)
    half = v * 0.5 * (1 - conf)
    return dict(low=int(max(10_000, centre - half)), high=int(centre + half), confidence=round(conf, 2),
                midpoint=int(centre))


def club_valuation(ctx):
    """Hidden numbers of the selling club (asking price, reservation price, flexibility)."""
    p, s = ctx["player"], ctx["seller"]
    d = DIFFICULTIES[ctx["difficulty"]]
    st = STYLE_PARAMS[s["style"]]
    v = intrinsic_value(p)
    left = int(p["contract_years_left"])
    cf = {0: 0.35, 1: 0.75, 2: 0.95, 3: 1.05}.get(left, 1.15 if left >= 4 else 1.0)
    need = _clamp(s["finance_need"], 0, 1)
    rq = _clamp(s["replacement_quality"], 0, 1)
    rivals = min(int(s["rival_interest"]), 3)
    ask = v * cf * ROLE_PRICE[p["role"]] * (1 - 0.18 * need) * (1.08 - 0.16 * rq) * (1 + 0.04 * rivals) * st["price"]
    days = ctx.get("window", {}).get("days_left", 30)
    if days <= 7:
        ask *= 0.94 if need >= 0.5 else 1.04
    if s["style"] == "opportunistic":
        ask *= 1 + 0.10 * (1 - info_confidence(ctx))  # mild: preys on a poorly-informed buyer only
    ask *= 1 + (_r(ctx["seed"], p["id"], "val").random() - 0.5) * 0.06  # studied, seeded variation +-3%
    unwilling = p["role"] == "key" and left >= 3 and rq < 0.6 and need < 0.7
    if unwilling:
        ask *= 1.2
    ask = _clamp(ask, 0.25 * v, 1.9 * v)
    ratio = _clamp(st["minr"] - 0.06 * need + 0.02 * rivals, 0.75, 0.99)
    minp = ask * min(0.995, ratio * d["min_mult"])
    if unwilling:
        minp = max(minp, min(ask * 0.995, v * 1.15))
    return dict(value=v, ask=ask, min_price=minp, unwilling=unwilling, stub=st["stub"],
                step=0.30 * d["flex"] * (1 - st["stub"]) * (1 + 0.5 * need), contract_left=left)


# ===================================================================== fee offers
def normalize_fee(o):
    o = dict(o or {})
    inst = [dict(amount=int(i["amount"]), months=int(i["months"])) for i in o.get("installments", [])]
    inst_total = sum(i["amount"] for i in inst)
    if "immediate" in o:
        immediate = int(o["immediate"])
    else:
        immediate = int(o.get("fee", 0)) - inst_total
    if immediate < 0 or any(i["amount"] < 0 or i["months"] <= 0 for i in inst):
        raise NegotiationError("negative amounts are not allowed")
    ex = o.get("exchange_player")
    if ex is not None:
        ex = dict(id=int(ex["id"]), value=int(ex["value"]))
    bonus = [dict(amount=int(b["amount"]), condition=str(b.get("condition", ""))) for b in o.get("achievement_bonus", [])]
    sell_on = float(o.get("sell_on_pct", 0))
    if not 0 <= sell_on <= 50:
        raise NegotiationError("sell-on percentage must be 0..50")
    opt = o.get("purchase_option")
    if opt is not None:
        if opt.get("type") not in ("option", "obligation"):
            raise NegotiationError("purchase_option.type must be option|obligation")
        opt = dict(type=opt["type"], price=int(opt["price"]))
    return dict(immediate=immediate, installments=inst, exchange_player=ex, achievement_bonus=bonus,
                sell_on_pct=sell_on, loan_fee=int(o.get("loan_fee", 0)), wage_share=_clamp(float(o.get("wage_share", 0)), 0, 100),
                loan_months=int(o.get("loan_months", 12)), purchase_option=opt,
                fee=immediate + inst_total)


def effective_fee(offer, ctx):
    """One comparable number for a fee offer: what the SELLER thinks it is worth now."""
    o = normalize_fee(offer)
    v = intrinsic_value(ctx["player"])
    if ctx["kind"] == "loan":
        wk = ctx["player"]["wage"] * 4.33 * o["loan_months"]
        eff = o["loan_fee"] + 0.5 * wk * o["wage_share"] / 100
    else:
        eff = o["immediate"]
        eff += sum(i["amount"] * (1 - 0.03 * i["months"] / 12) for i in o["installments"])
        eff += (o["exchange_player"]["value"] * 0.85) if o["exchange_player"] else 0
        eff += sum(b["amount"] for b in o["achievement_bonus"]) * 0.35
        eff += v * 0.6 * o["sell_on_pct"] / 100
    if o["purchase_option"]:
        eff += o["purchase_option"]["price"] * (0.6 if o["purchase_option"]["type"] == "obligation" else 0.2) * 0.5
    return eff


def _loan_scale(ctx, o_months=12):
    """Loan asking price = fraction of a transfer ask (loan fee ~10% of value per year)."""
    return 0.10 * o_months / 12


# ===================================================================== contract offers
def normalize_contract(o, ctx=None):
    o = dict(o or {})
    L = o.get("length")
    if not isinstance(L, int) or isinstance(L, bool) or not 1 <= L <= 5:
        raise NegotiationError("contract length must be a whole number of years from 1 to 5")
    role = o.get("role")
    if role not in ROLE_RANK:
        raise NegotiationError("unknown squad role")
    w = float(o.get("weekly_wage", 0))
    if w <= 0:
        raise NegotiationError("weekly wage must be positive")
    for k in ("signing_bonus", "agent_fee"):
        if float(o.get(k, 0)) < 0:
            raise NegotiationError(k + " cannot be negative")
    rc = o.get("release_clause")
    if rc is not None and float(rc) <= 0:
        raise NegotiationError("release clause must be positive")
    ab, gb = o.get("appearance_bonus"), o.get("goal_bonus")
    for b, key in ((ab, "apps"), (gb, "goals")):
        if b is not None and (float(b["amount"]) < 0 or int(b[key]) <= 0):
            raise NegotiationError("bonus needs a non-negative amount and a positive threshold")
    return dict(weekly_wage=int(round(w)), length=L, role=role,
                release_clause=int(rc) if rc is not None else None,
                signing_bonus=int(o.get("signing_bonus", 0)), agent_fee=int(o.get("agent_fee", 0)),
                appearance_bonus=dict(amount=int(ab["amount"]), apps=int(ab["apps"])) if ab else None,
                goal_bonus=dict(amount=int(gb["amount"]), goals=int(gb["goals"])) if gb else None)


def total_commitment(c, ctx):
    """Full financial commitment. Conditional bonuses are NOT part of the weekly wage and are shown separately."""
    c = normalize_contract(c)
    p = ctx["player"]
    L = c["length"]
    share = ROLE_APPS_SHARE[c["role"]]
    fixed = c["weekly_wage"] * 52 * L + c["signing_bonus"] + c["agent_fee"]
    exp = mx = 0.0
    if c["appearance_bonus"]:
        b = c["appearance_bonus"]
        prob = _clamp((38 * share / b["apps"]) ** 1.5, 0, 1)
        exp += b["amount"] * L * prob
        mx += b["amount"] * L
    if c["goal_bonus"]:
        b = c["goal_bonus"]
        g = GOALS_BY_POS.get(p["pos"], 3) * share * _clamp(p["ovr"] / 75, 0.6, 1.3)
        prob = _clamp((g / b["goals"]) ** 1.5, 0, 1)
        exp += b["amount"] * L * prob
        mx += b["amount"] * L
    return dict(weekly_wage=c["weekly_wage"], fixed=int(fixed), conditional_expected=int(exp),
                conditional_max=int(mx), total_expected=int(fixed + exp), total_max=int(fixed + mx))


def expected_role(ctx):
    d = ctx["player"]["ovr"] - ctx["buyer"]["squad_avg_ovr"]
    return "key" if d >= 3 else "important" if d >= -2 else "rotation" if d >= -8 else "limited"


def player_openness(ctx):
    p, b = ctx["player"], ctx["buyer"]
    cur_rep = p.get("club_rep", 0) if p.get("club_id") else 0
    score = (b["reputation"] - cur_rep) / 50.0 + 0.25 * (ROLE_RANK[expected_role(ctx)] - 1)
    score += (_r(ctx["seed"], p["id"], "open").random() - 0.5) * 0.4
    if ctx["kind"] == "renewal":
        return "open"
    return "willing" if score > 0.35 else "reluctant" if score < -0.35 else "open"


def player_demand(ctx, role, length, release_clause=None):
    """The player's reservation wage (weekly, wage-equivalent) for THIS role/length/clause. Fully deterministic."""
    p, b = ctx["player"], ctx["buyer"]
    d = DIFFICULTIES[ctx["difficulty"]]
    v = intrinsic_value(p)
    market = T.weekly_wage(v)
    if ctx["kind"] == "renewal":
        base = max(p["wage"], market)
    else:
        base = max(p["wage"] * 1.12, market)
        cur_rep = p.get("club_rep", 0) if p.get("club_id") else b["reputation"]
        base *= _clamp(1 - 0.25 * (b["reputation"] - cur_rep) / 100.0, 0.85, 1.2)
        if player_openness(ctx) == "reluctant":
            base *= 1.10
    gap = max(0, ROLE_RANK[expected_role(ctx)] - ROLE_RANK[role])
    base *= 1 + 0.12 * min(gap, 1) + (0.25 * max(0, gap - 1))
    age = p["age"]
    per_year = 0.04 if age <= 25 else (-0.04 if age >= 30 else 0.0)
    base *= 1 + per_year * (length - 3)  # young: locking them in costs more; veterans trade wage for security
    if release_clause is not None and release_clause <= 1.5 * v:
        base *= 0.96  # players value an exit door
    return base * d["wage_mult"]


def wage_equivalent(c, ctx):
    tc = total_commitment(c, ctx)
    L = c["length"]
    return c["weekly_wage"] + c["signing_bonus"] / (52 * L) + 0.7 * tc["conditional_expected"] / (52 * L)


def detect_conflicts(c, ctx):
    out = []
    gap = ROLE_RANK[expected_role(ctx)] - ROLE_RANK[c["role"]]
    if gap > 0:
        out.append("role_below_expectation")
    if c["role"] in ("limited", "rotation") and c["weekly_wage"] > 1.4 * T.weekly_wage(intrinsic_value(ctx["player"])):
        out.append("wage_high_for_role")
    if c["release_clause"] is not None and c["release_clause"] < 0.8 * intrinsic_value(ctx["player"]):
        out.append("clause_below_value")
    return out


# ===================================================================== state
def new_negotiation(ctx):
    ctx = copy.deepcopy(ctx)
    kind = ctx.get("kind")
    if kind not in KINDS:
        raise NegotiationError("unknown negotiation kind")
    ctx.setdefault("difficulty", "realistic")
    if ctx["difficulty"] not in DIFFICULTIES:
        raise NegotiationError("unknown difficulty")
    ctx.setdefault("seed", 1)
    ctx.setdefault("scouting", 0)
    ctx.setdefault("window", dict(open=True, days_left=30))
    ctx["player"].setdefault("role", "rotation")
    ctx["player"].setdefault("contract_years_left", 2)
    ctx["player"].setdefault("club_rep", 50)
    st = dict(version=1, id=None, ctx=ctx, kind=kind, status="active", rounds=dict(club=0, contract=0),
              progress=dict(club=0.0, contract=0.0), tension=dict(club=0.0, contract=0.0),
              unwilling_given=False, best_eff=0.0, history=[], club_terms=None, contract_terms=None,
              last_counter=None, fail_reason=None, retry_after_days=None)
    if kind == "sell":
        buyer_max = intrinsic_value(ctx["player"]) * (1.05 + 0.25 * _clamp(ctx.get("interest", 0.5), 0, 1))
        r = _r(ctx["seed"], ctx["player"]["id"], "sellbid")
        bid = buyer_max * (0.72 + 0.10 * r.random())
        st.update(stage="club", val=dict(buyer_max=buyer_max), current_offer=int(bid), sell_rounds=0)
        return st
    if kind in ("buy", "loan"):
        v = club_valuation(ctx)
        st["val"] = v
        st["current_ask"] = _fee_scale(ctx, v["ask"])
        st["stage"] = "inquiry"
    elif kind == "free_agent":
        st["stage"] = "inquiry"
        st["val"] = None
    else:  # renewal
        st["stage"] = "contract"
        st["val"] = None
    return st


def _fee_scale(ctx, amount):
    return amount * (_loan_scale(ctx, ctx.get("loan_months", 12)) if ctx["kind"] == "loan" else 1.0)


def _reservation(state):
    v = state["val"]
    k = state["ctx"]["kind"]
    s = _loan_scale(state["ctx"], state["ctx"].get("loan_months", 12)) if k == "loan" else 1.0
    return v["ask"] * s, v["min_price"] * s


def _hist(state, **kw):
    state["history"].append(kw)
    del state["history"][:-MAX_HISTORY]


def _band(t, patience):
    f = t / patience
    return "calm" if f < 0.35 else "tense" if f < 0.7 else "critical"


def inquire(state):
    """Stage 1. Returns what the user may know: a market-value RANGE with confidence, the club's STATED asking price
    (not the real value; not the hidden reservation), and attitudes. Safe to call repeatedly."""
    ctx = state["ctx"]
    out = dict(market_estimate=market_estimate(ctx), player_openness=player_openness(ctx),
               expected_role=expected_role(ctx))
    if state["val"]:
        ask, _ = _reservation(state)
        out["stated_ask"] = int(state["current_ask"])
        out["club_attitude"] = "reluctant" if state["val"]["unwilling"] else "open"
        est = out["market_estimate"]["midpoint"]
        rel = state["current_ask"] / (est * (_loan_scale(ctx, ctx.get("loan_months", 12)) if ctx["kind"] == "loan" else 1))
        out["ask_vs_estimate"] = "below_expected" if rel < 0.95 else "near_expected" if rel <= 1.10 else "above_expected"
    if state["stage"] == "inquiry":
        state["stage"] = "club" if state["kind"] in ("buy", "loan") else "contract"
    return out


# ===================================================================== club stage
def _check_window(state):
    ctx = state["ctx"]
    if state["kind"] in ("buy", "loan", "sell") and not ctx.get("window", {}).get("open", True):
        return "window_closed"
    return None


def submit_club_offer(state, offer):
    """User offers the selling club a fee package. Returns a response dict:
    {'response': accept|counter|reject|collapse|invalid, 'reason', 'counter', 'tension', 'hint', ...}"""
    if state["status"] != "active":
        raise NegotiationError("negotiation is not active")
    if state["kind"] not in ("buy", "loan"):
        raise NegotiationError("no club fee talks in this negotiation kind")
    if state["stage"] == "inquiry":
        inquire(state)
    if state["stage"] != "club":
        raise NegotiationError("club stage is already finished")
    ctx, v = state["ctx"], state["val"]
    d = DIFFICULTIES[ctx["difficulty"]]
    if _check_window(state):
        return dict(response="invalid", reason="window_closed", counter=None)
    o = normalize_fee(offer)
    if state["kind"] == "buy" and o["immediate"] > ctx["buyer"]["budget"]:
        return dict(response="invalid", reason="over_budget", counter=None)
    eff = effective_fee(o, ctx)
    ask, minp = _reservation(state)
    rd = state["rounds"]
    rd["club"] += 1
    t = 0.0
    reason = None
    ratio = eff / ask
    if ratio < 0.55:
        t += 28
        reason = "value_too_low"
    elif ratio < 0.80:
        t += 12
        reason = "value_too_low"
    elif eff < minp:
        t += 5
        reason = "value_too_low"
    last = state["history"][-1] if state["history"] and state["history"][-1]["stage"] == "club" else None
    if last and abs(eff - last["eff"]) < 1 and last["response"] != "accept":
        t += 8
        reason = reason or "value_too_low"
    if state["best_eff"] and eff < state["best_eff"] * 0.97:
        t += 10
        reason = "offer_regressed"
    state["best_eff"] = max(state["best_eff"], eff)
    state["tension"]["club"] += t * d["tension"]
    patience = d["patience"]

    # contract-clause style shortcut: a release clause on the player lets any club that meets it buy him
    clause = ctx["player"].get("release_clause")
    triggered = clause is not None and state["kind"] == "buy" and o["immediate"] >= clause
    if triggered or eff >= state["current_ask"] * 0.985:
        resp = dict(response="accept", reason=None, counter=None)
        state["club_terms"] = dict(offer=o, effective=int(eff), via_release_clause=bool(triggered))
        state["stage"] = "contract" if state["kind"] == "buy" else "contract"
        state["last_counter"] = None
        return _finish_club(state, resp, eff, patience)

    if state["tension"]["club"] >= patience:
        state["status"] = "collapsed"
        state["fail_reason"] = "negotiation_collapsed"
        state["retry_after_days"] = 14  # this pairing only; nothing global
        return _finish_club(state, dict(response="collapse", reason="negotiation_collapsed", counter=None), eff, patience)

    # first time a club that does not want to sell is pushed below its door price: say so ONCE, then keep talking
    if v["unwilling"] and not state["unwilling_given"] and eff < minp:
        state["unwilling_given"] = True
        reason = "club_unwilling_to_sell"
    if o["installments"] and o["immediate"] < 0.35 * o["fee"] and eff < state["current_ask"] and \
            ctx["seller"]["style"] != "cooperative" and reason != "club_unwilling_to_sell":
        reason = "payment_structure"
    if ctx["seller"]["rival_interest"] > 0 and eff < state["current_ask"] and reason is None:
        reason = "better_alternatives"

    # concede toward the reservation price in proportion to how engaged the user is (lowballing earns nothing)
    if ratio >= 0.55:
        state["progress"]["club"] = min(1.0, state["progress"]["club"] + v["step"])
    pr = state["progress"]["club"]
    cur = ask - (ask - minp) * pr
    state["current_ask"] = max(minp, cur)
    if eff >= state["current_ask"] * 0.985:
        state["club_terms"] = dict(offer=o, effective=int(eff), via_release_clause=False)
        state["stage"] = "contract"
        return _finish_club(state, dict(response="accept", reason=None, counter=None), eff, patience)
    counter = dict(immediate=int(round(state["current_ask"], -3)))
    if state["kind"] == "loan":
        counter = dict(loan_fee=int(round(state["current_ask"], -3)), wage_share=o["wage_share"], loan_months=o["loan_months"])
    state["last_counter"] = dict(stage="club", offer=counter)
    resp = dict(response="reject" if (reason in ("value_too_low", "club_unwilling_to_sell") and ratio < 0.8) else "counter",
                reason=reason or "value_too_low", counter=counter)
    return _finish_club(state, resp, eff, patience)


def _finish_club(state, resp, eff, patience):
    d = DIFFICULTIES[state["ctx"]["difficulty"]]
    resp["tension"] = _band(state["tension"]["club"], patience)
    resp["round"] = state["rounds"]["club"]
    if d["hints"] >= 1 and state["val"] and state["status"] == "active" and resp["response"] != "accept":
        _, minp = _reservation(state)
        gap = (state["current_ask"] - eff) / state["current_ask"]
        resp["hint"] = "close" if gap < 0.08 else "far"
        if d["hints"] >= 2:
            resp["settle_range"] = (int(minp), int(state["current_ask"]))
    _hist(state, stage="club", eff=int(eff), response=resp["response"], reason=resp.get("reason"))
    resp["stage"] = state["stage"]
    return resp


# ===================================================================== contract stage
def submit_contract_offer(state, offer):
    """User offers the player/agent a personal contract."""
    if state["status"] != "active":
        raise NegotiationError("negotiation is not active")
    if state["kind"] == "sell":
        raise NegotiationError("selling: the buyer's contract is resolved automatically")
    if state["stage"] == "inquiry":
        inquire(state)
    if state["kind"] in ("buy", "loan") and state["club_terms"] is None:
        raise NegotiationError("agree the fee with the club first")
    if state["stage"] != "contract":
        raise NegotiationError("contract stage is not open")
    ctx = state["ctx"]
    d = DIFFICULTIES[ctx["difficulty"]]
    c = normalize_contract(offer)
    if state["kind"] == "loan":
        if c["release_clause"] or c["signing_bonus"] or c["appearance_bonus"] or c["goal_bonus"]:
            raise NegotiationError("loan contracts take wage and role only")
    wr = ctx["buyer"].get("wage_room")
    if wr is not None and c["weekly_wage"] > wr:
        return dict(response="invalid", reason="over_wage_budget", counter=None)
    p = ctx["player"]
    rd = state["rounds"]
    rd["contract"] += 1
    base_demand = player_demand(ctx, c["role"], c["length"], c["release_clause"])
    util = wage_equivalent(c, ctx)
    ratio = util / base_demand
    gap = max(0, ROLE_RANK[expected_role(ctx)] - ROLE_RANK[c["role"]])
    conflicts = detect_conflicts(c, ctx)
    t, reason = 0.0, None
    if gap >= 2:
        t += 20
        reason = "role_unsuitable"
    if ratio < 0.60:
        t += 30
        reason = reason or "wage_below_expectation"
    elif ratio < 0.85:
        t += 12
        reason = reason or "wage_below_expectation"
    elif ratio < 0.985:
        t += 4
        reason = reason or "wage_below_expectation"
    last = state["history"][-1] if state["history"] and state["history"][-1]["stage"] == "contract" else None
    if last and abs(util - last["eff"]) < 1:
        t += 8
    if last and util < last["eff"] * 0.97:
        t += 10
        reason = "offer_regressed"
    state["tension"]["contract"] += t * d["tension"]

    greedy = _r(ctx["seed"], p["id"], "agent").random()
    open_mult = 1.12 if greedy > 0.66 else 1.06 if greedy > 0.25 else 1.02
    flex = 0.34 * d["flex"]
    if ratio >= 0.55 and gap < 2:
        state["progress"]["contract"] = min(1.0, state["progress"]["contract"] + flex)
    pr = state["progress"]["contract"]
    cur_demand = base_demand * (open_mult - (open_mult - 1.0) * pr)

    patience = d["patience"]
    resp = None
    if gap < 2 and util >= cur_demand * 0.985:
        state["contract_terms"] = dict(offer=c, commitment=total_commitment(c, ctx))
        state["stage"] = "confirm"
        state["last_counter"] = None
        resp = dict(response="accept", reason=None, counter=None)
    elif state["tension"]["contract"] >= patience:
        state["status"] = "collapsed"
        state["fail_reason"] = "player_unwilling"
        state["retry_after_days"] = 14
        resp = dict(response="collapse", reason="player_unwilling", counter=None)
    else:
        need_role = expected_role(ctx) if gap >= 2 else c["role"]
        dem_wage = cur_demand if gap < 2 else player_demand(ctx, need_role, c["length"], c["release_clause"]) * open_mult
        # express the demand in plain wage, net of what bonuses already give him
        extra = (wage_equivalent(c, ctx) - c["weekly_wage"]) if gap < 2 else 0
        counter = dict(role=need_role, length=c["length"], weekly_wage=int(round(max(1, dem_wage - extra), -1)),
                       release_clause=c["release_clause"])
        state["last_counter"] = dict(stage="contract", offer=counter)
        resp = dict(response="reject" if ratio < 0.8 or gap >= 2 else "counter",
                    reason=reason or "wage_below_expectation", counter=counter)
    resp["conflicts"] = conflicts
    resp["tension"] = _band(state["tension"]["contract"], patience)
    resp["round"] = rd["contract"]
    if d["hints"] >= 1 and resp["response"] not in ("accept", "collapse"):
        resp["hint"] = "close" if util / cur_demand > 0.92 else "far"
    if d["hints"] >= 2 and resp["response"] not in ("accept", "collapse"):
        resp["demand_wage_equivalent"] = int(cur_demand)
    _hist(state, stage="contract", eff=int(util), response=resp["response"], reason=resp.get("reason"))
    resp["stage"] = state["stage"]
    return resp


# ===================================================================== sell side (offers received)
def respond_incoming(state, action, counter_fee=None):
    """The AI buyer made `state['current_offer']` for the user's player. action: accept | reject | counter."""
    if state["kind"] != "sell" or state["status"] != "active":
        raise NegotiationError("not an active incoming offer")
    if _check_window(state):
        return dict(response="invalid", reason="window_closed")
    v = state["val"]
    if action == "reject":
        state["status"] = "failed"
        state["fail_reason"] = "walked_away"
        return dict(response="closed", reason=None)
    if action == "accept":
        state["club_terms"] = dict(offer=normalize_fee(dict(immediate=state["current_offer"])), effective=state["current_offer"])
        state["stage"] = "contract"
        return _resolve_incoming_contract(state)
    if action != "counter" or counter_fee is None:
        raise NegotiationError("counter needs counter_fee")
    state["sell_rounds"] += 1
    if counter_fee <= v["buyer_max"] * 0.99:
        state["current_offer"] = int(counter_fee)
        state["club_terms"] = dict(offer=normalize_fee(dict(immediate=int(counter_fee))), effective=int(counter_fee))
        state["stage"] = "contract"
        return _resolve_incoming_contract(state, extra=dict(response="accept"))
    if state["sell_rounds"] >= 3:
        state["status"] = "failed"
        state["fail_reason"] = "price_too_high"
        return dict(response="walk_away", reason="price_too_high")
    d = DIFFICULTIES[state["ctx"]["difficulty"]]
    state["current_offer"] = int(min(v["buyer_max"], state["current_offer"] + (counter_fee - state["current_offer"]) * 0.4 * d["flex"]))
    return dict(response="counter", reason="price_too_high", counter=state["current_offer"], round=state["sell_rounds"])


def _resolve_incoming_contract(state, extra=None):
    ctx = state["ctx"]
    p = ctx["player"]
    r = _r(ctx["seed"], p["id"], "sellplayer")
    openness_p = {"willing": 0.95, "open": 0.8, "reluctant": 0.5}[player_openness(ctx)]
    if r.random() <= openness_p:
        wage = int(T.weekly_wage(intrinsic_value(p)) * 1.15)
        length = 3 if p["age"] < 30 else 2
        c = normalize_contract(dict(weekly_wage=wage, length=length, role=expected_role(ctx)))
        state["contract_terms"] = dict(offer=c, commitment=total_commitment(c, ctx))
        state["stage"] = "confirm"
        out = dict(response="accept", reason=None, player_agreed=True)
    else:
        state["status"] = "failed"
        state["fail_reason"] = "player_unwilling"
        out = dict(response="club_agreed_player_refused", reason="player_unwilling", player_agreed=False)
    if extra:
        out.update({k: v for k, v in extra.items() if k != "response" or out["response"] == "accept"})
    return out


# ===================================================================== lifecycle
def accept_counter(state):
    """User accepts the other side's last counter-offer as it stands."""
    if state["status"] != "active" or not state.get("last_counter"):
        raise NegotiationError("no counter-offer to accept")
    lc = state["last_counter"]
    if lc["stage"] == "club":
        r = submit_club_offer(state, lc["offer"])
    else:
        r = submit_contract_offer(state, lc["offer"])
    return r


def walk_away(state):
    if state["status"] == "active":
        state["status"] = "failed"
        state["fail_reason"] = "walked_away"
    return state


def budget_impact(state):
    """What the deal does to the buyer's money. Installments are listed, never hidden inside one total."""
    ctx = state["ctx"]
    ct, cc = state.get("club_terms"), state.get("contract_terms")
    imm = inst = bon = 0
    if ct:
        o = ct["offer"]
        imm = o["loan_fee"] if state["kind"] == "loan" else o["immediate"]
        inst = sum(i["amount"] for i in o["installments"])
        bon = sum(b["amount"] for b in o["achievement_bonus"])
    sign = cc["commitment"]["fixed"] - cc["commitment"]["weekly_wage"] * 52 * cc["offer"]["length"] if cc else 0
    budget = ctx["buyer"]["budget"] if state["kind"] != "sell" else None
    return dict(budget_before=budget, paid_now=int(imm + sign), budget_after=(budget - imm - sign) if budget is not None else None,
                future_installments=[i for i in (ct["offer"]["installments"] if ct else [])], installments_total=int(inst),
                conditional_transfer_bonuses_max=int(bon), weekly_wage=cc["commitment"]["weekly_wage"] if cc else 0,
                contract_commitment=cc["commitment"] if cc else None)


def confirm(state):
    """Stage 5: both agreements must exist (club stage skipped where it does not apply)."""
    if state["status"] != "active":
        raise NegotiationError("negotiation is not active")
    need_club = state["kind"] in ("buy", "loan", "sell")
    if need_club and not state.get("club_terms"):
        raise NegotiationError("club agreement missing")
    if not state.get("contract_terms"):
        raise NegotiationError("player has not agreed a contract - deal is NOT complete")
    imp = budget_impact(state)
    if imp["budget_after"] is not None and imp["budget_after"] < 0:
        raise NegotiationError("not enough transfer budget")
    state["status"] = "agreed"
    state["stage"] = "confirm"
    return imp


def public_view(state):
    """Everything the UI may show: no hidden reservation prices, no tension number, no valuation internals."""
    d = DIFFICULTIES[state["ctx"]["difficulty"]]
    return dict(id=state["id"], kind=state["kind"], stage=state["stage"], status=state["status"],
                market_estimate=market_estimate(state["ctx"]) if state["kind"] != "sell" else None,
                stated_ask=int(state["current_ask"]) if state.get("current_ask") else None,
                rounds=state["rounds"], tension={k: _band(v, d["patience"]) for k, v in state["tension"].items()},
                last_counter=state.get("last_counter"), fail_reason=state["fail_reason"],
                retry_after_days=state["retry_after_days"], history=state["history"][-2:],
                club_terms=state.get("club_terms") and state["club_terms"]["offer"],
                contract_terms=state.get("contract_terms") and state["contract_terms"]["offer"])


def to_json(state):
    return json.dumps(state, ensure_ascii=False, sort_keys=True)


def from_json(text):
    return json.loads(text)


# ===================================================================== persistence + context from the career DB
def ensure_schema(con):
    con.executescript("""
CREATE TABLE IF NOT EXISTS negotiation(id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, player_id INTEGER NOT NULL,
  status TEXT NOT NULL, stage TEXT NOT NULL, state TEXT NOT NULL, updated TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_neg_status ON negotiation(status);
CREATE TABLE IF NOT EXISTS club_finance(club_id INTEGER PRIMARY KEY, transfer_budget INTEGER NOT NULL, wage_budget INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS payment_due(id INTEGER PRIMARY KEY AUTOINCREMENT, negotiation_id INTEGER, due_date TEXT NOT NULL,
  from_club INTEGER NOT NULL, to_club INTEGER NOT NULL, amount INTEGER NOT NULL, paid INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS deal_terms(player_id INTEGER PRIMARY KEY, terms TEXT NOT NULL);
""")
    con.commit()


def save(con, state):
    ensure_schema(con)
    now = con.execute("SELECT cur_date FROM career_info").fetchone()[0]
    with con:
        if state["id"] is None:
            cur = con.execute("INSERT INTO negotiation(kind,player_id,status,stage,state,updated) VALUES(?,?,?,?,?,?)",
                              (state["kind"], state["ctx"]["player"]["id"], state["status"], state["stage"], "{}", now))
            state["id"] = cur.lastrowid
        con.execute("UPDATE negotiation SET status=?,stage=?,state=?,updated=? WHERE id=?",
                    (state["status"], state["stage"], to_json(state), now, state["id"]))
    return state["id"]


def load(con, nid):
    ensure_schema(con)
    row = con.execute("SELECT state FROM negotiation WHERE id=?", (nid,)).fetchone()
    if not row:
        raise NegotiationError("unknown negotiation")
    return from_json(row[0])


def cancel_for_club(con, club_id):
    """Used when the manager leaves a club: its open negotiations are dropped (nothing else happens)."""
    ensure_schema(con)
    n = 0
    for row in con.execute("SELECT id,state FROM negotiation WHERE status IN ('active','agreed')").fetchall():
        st = from_json(row[1])
        if st["ctx"].get("buyer", {}).get("club_id") == club_id or st["ctx"].get("seller", {}) and st["ctx"]["seller"].get("club_id") == club_id:
            st["status"] = "cancelled"
            save(con, st)
            n += 1
    return n


def get_finance(con, club_id):
    ensure_schema(con)
    row = con.execute("SELECT transfer_budget,wage_budget FROM club_finance WHERE club_id=?", (club_id,)).fetchone()
    if row:
        return dict(transfer_budget=row[0], wage_budget=row[1])
    w = con.execute("SELECT transfer_budget,wage_budget FROM world.clubs WHERE id=?", (club_id,)).fetchone()
    return dict(transfer_budget=w[0], wage_budget=w[1])


def _set_finance(con, club_id, tb, wb=None):
    cur = get_finance(con, club_id)
    con.execute("INSERT INTO club_finance VALUES(?,?,?) ON CONFLICT(club_id) DO UPDATE SET transfer_budget=excluded.transfer_budget,"
                "wage_budget=excluded.wage_budget", (club_id, int(tb), int(cur["wage_budget"] if wb is None else wb)))


def _age(birth, season):
    return season - int(birth[:4])


def build_context(con, kind, player_id, buyer_club_id, difficulty="realistic", seed=None, scouting=0,
                  window_open=True, window_days_left=30, interest=0.5, loan_months=12):
    """Assemble the plain-dict context from the career DB (read-only). Hidden club traits (finance need, style,
    rival interest) are derived deterministically from ids + career seed, so replays are identical."""
    from . import db
    ensure_schema(con)
    info = con.execute("SELECT season,seed FROM career_info").fetchone()
    seed = info["seed"] if seed is None else seed
    p = con.execute("SELECT * FROM v_player WHERE id=?", (player_id,)).fetchone()
    if p is None:
        raise NegotiationError("unknown player")
    cid = p["club_id"]
    age = _age(p["birth_date"], info["season"])
    cl = con.execute("SELECT reputation FROM world.clubs WHERE id=?", (cid,)).fetchone() if cid else None
    squad = db.squad(con, cid) if cid else []
    rank = 1 + sum(1 for x in squad if x["ovr"] > p["ovr"])
    role = "key" if rank <= 5 else "important" if rank <= 12 else "rotation" if rank <= 18 else "limited"
    same = sorted((x["ovr"] for x in squad if x["pos"] == p["pos"] and x["id"] != p["id"]), reverse=True)
    rq = _clamp((same[0] / p["ovr"]) if same else 0.0, 0, 1) ** 2 if same else 0.0
    left = max(0, int(p["contract_end"] or info["season"]) - info["season"])
    rr = _r(seed, cid or 0, "club")
    fin = get_finance(con, cid) if cid else None
    base0 = con.execute("SELECT transfer_budget FROM world.clubs WHERE id=?", (cid,)).fetchone() if cid else None
    spent = _clamp(1 - fin["transfer_budget"] / base0[0], 0, 1) if cid and base0 and base0[0] else 0
    need = _clamp(rr.random() * 0.6 + 0.5 * spent, 0, 1)
    rivals = int(_clamp((p["ovr"] - 70) / 6, 0, 3)) + (1 if _r(seed, player_id, "rival").random() < 0.3 else 0)
    bf = get_finance(con, buyer_club_id)
    br = con.execute("SELECT reputation FROM world.clubs WHERE id=?", (buyer_club_id,)).fetchone()[0]
    bsq = sorted((x["ovr"] for x in db.squad(con, buyer_club_id)), reverse=True)[:18]
    ctx = dict(kind=kind, difficulty=difficulty, seed=seed, scouting=scouting, interest=interest, loan_months=loan_months,
               window=dict(open=window_open, days_left=window_days_left), season=info["season"],
               player=dict(id=p["id"], ovr=p["ovr"], potential=p["potential"], age=age, value=p["value"], wage=p["wage"],
                           contract_years_left=left, pos=p["pos"], club_id=cid, club_rep=cl[0] if cl else 0, role=role),
               seller=dict(club_id=cid, finance_need=need, replacement_quality=rq, rival_interest=rivals,
                           style=STYLES[rr.randrange(4)], reputation=cl[0] if cl else 0) if cid else None,
               buyer=dict(club_id=buyer_club_id, budget=bf["transfer_budget"], wage_room=None, reputation=br,
                          squad_avg_ovr=sum(bsq) / len(bsq) if bsq else 60))
    if kind == "renewal":
        ctx["buyer"]["club_id"] = cid
    return ctx


def apply_deal(con, state):
    """Execute an AGREED negotiation in one transaction: player move, wage/contract, budgets, installments, terms."""
    if state["status"] == "done":
        raise NegotiationError("deal already applied")
    if state["status"] != "agreed":
        raise NegotiationError("only an agreed deal can be applied (player and club must both have agreed)")
    ensure_schema(con)
    ctx, ct, cc = state["ctx"], state.get("club_terms"), state["contract_terms"]
    info = con.execute("SELECT season,cur_date FROM career_info").fetchone()
    pid, buyer = ctx["player"]["id"], ctx["buyer"]["club_id"]
    seller = ctx["player"]["club_id"] if state["kind"] != "free_agent" else None
    o = cc["offer"]
    from datetime import date, timedelta
    cur = date.fromisoformat(info["cur_date"])
    with con:
        if ct:
            f = ct["offer"]
            paid = f["loan_fee"] if state["kind"] == "loan" else f["immediate"]
            if state["kind"] != "sell":
                bf = get_finance(con, buyer)
                total_out = paid + (cc["commitment"]["fixed"] - cc["commitment"]["weekly_wage"] * 52 * o["length"])
                if bf["transfer_budget"] < total_out:
                    raise NegotiationError("not enough transfer budget")
                _set_finance(con, buyer, bf["transfer_budget"] - total_out)
            else:
                bf = get_finance(con, buyer)
                _set_finance(con, buyer, bf["transfer_budget"] - paid)
            if seller:
                sf = get_finance(con, seller)
                _set_finance(con, seller, sf["transfer_budget"] + paid)
            for i in f["installments"]:
                con.execute("INSERT INTO payment_due(negotiation_id,due_date,from_club,to_club,amount) VALUES(?,?,?,?,?)",
                            (state["id"], (cur + timedelta(days=30 * i["months"])).isoformat(), buyer, seller or 0, i["amount"]))
            if f["exchange_player"]:
                con.execute("INSERT INTO player_state(player_id,club_id) VALUES(?,?) ON CONFLICT(player_id) DO UPDATE SET club_id=excluded.club_id",
                            (f["exchange_player"]["id"], seller or 0))
        else:  # renewal / free agent: only the signing cost (signing bonus + agent fee)
            bf = get_finance(con, buyer)
            cost = cc["commitment"]["fixed"] - cc["commitment"]["weekly_wage"] * 52 * o["length"]
            if bf["transfer_budget"] < cost:
                raise NegotiationError("not enough transfer budget")
            _set_finance(con, buyer, bf["transfer_budget"] - cost)
        con.execute("INSERT INTO player_state(player_id,club_id,wage,contract_end) VALUES(?,?,?,?) "
                    "ON CONFLICT(player_id) DO UPDATE SET club_id=excluded.club_id,wage=excluded.wage,contract_end=excluded.contract_end",
                    (pid, buyer, o["weekly_wage"], info["season"] + o["length"]))
        terms = dict(release_clause=o["release_clause"], appearance_bonus=o["appearance_bonus"], goal_bonus=o["goal_bonus"],
                     role=o["role"], sell_on_pct=ct["offer"]["sell_on_pct"] if ct else 0, sell_on_to=seller,
                     loan_from=seller if state["kind"] == "loan" else None)
        con.execute("INSERT INTO deal_terms VALUES(?,?) ON CONFLICT(player_id) DO UPDATE SET terms=excluded.terms",
                    (pid, json.dumps(terms)))
        state["status"] = "done"
        save(con, state)
    return state


def settle_due_payments(con):
    """Pay installments due on/before the current in-game date (call when time advances)."""
    ensure_schema(con)
    today = con.execute("SELECT cur_date FROM career_info").fetchone()[0]
    rows = con.execute("SELECT * FROM payment_due WHERE paid=0 AND due_date<=?", (today,)).fetchall()
    with con:
        for r in rows:
            b = get_finance(con, r["from_club"])
            _set_finance(con, r["from_club"], b["transfer_budget"] - r["amount"])
            if r["to_club"]:
                s = get_finance(con, r["to_club"])
                _set_finance(con, r["to_club"], s["transfer_budget"] + r["amount"])
            con.execute("UPDATE payment_due SET paid=1 WHERE id=?", (r["id"],))
    return len(rows)
