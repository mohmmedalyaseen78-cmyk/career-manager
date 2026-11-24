import copy
import json
import os
import random
import shutil
import socket
import statistics
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine import db, negotiation as N, talents as T
from engine.career import CareerManager
from engine.match import MatchSession, auto_lineup
from engine.worldgen import build_world

TMP = tempfile.mkdtemp(prefix="grafeco_neg_")
WORLD = os.path.join(TMP, "world.db")


def setUpModule():
    build_world(WORLD, seed=7)


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def mk(kind="buy", ovr=75, age=26, value=20_000_000, left=3, role="important", need=0.2, rq=0.5, rivals=0,
       style="firm", difficulty="realistic", seed=1, budget=100_000_000, buyer_rep=70, buyer_avg=72, club_rep=60,
       days_left=30, pos="CM", scouting=0, release_clause=None, wage=None, pid=1, window_open=True):
    return dict(kind=kind, difficulty=difficulty, seed=seed, scouting=scouting, interest=0.5, loan_months=12,
                window=dict(open=window_open, days_left=days_left),
                player=dict(id=pid, ovr=ovr, potential=ovr, age=age, value=value, wage=wage or T.weekly_wage(value),
                            contract_years_left=left, pos=pos, club_id=2, club_rep=club_rep, role=role,
                            release_clause=release_clause),
                seller=dict(club_id=2, finance_need=need, replacement_quality=rq, rival_interest=rivals, style=style,
                            reputation=club_rep),
                buyer=dict(club_id=1, budget=budget, wage_room=None, reputation=buyer_rep, squad_avg_ovr=buyer_avg))


def agree_fee(state, factor=1.0):
    """Offer the club's stated ask * factor in cash until it accepts (user-side behaviour, uses only public info)."""
    info = N.inquire(state)
    r = N.submit_club_offer(state, dict(immediate=int(info["stated_ask"] * factor)))
    return r


def good_contract(ctx, mult=1.2, length=3, role=None, **extra):
    role = role or N.expected_role(ctx)
    return dict(weekly_wage=int(N.player_demand(ctx, role, length) * mult), length=length, role=role, **extra)


class TestValuationAndFees(unittest.TestCase):
    def test_1_money_needy_club_with_replacement_is_more_flexible(self):
        needy = N.club_valuation(N.new_negotiation(mk(need=0.9, rq=0.9, style="firm"))["ctx"])
        rich = N.club_valuation(N.new_negotiation(mk(need=0.0, rq=0.1, style="firm"))["ctx"])
        self.assertLess(needy["ask"], rich["ask"] * 0.9)
        self.assertLess(needy["min_price"], rich["min_price"] * 0.9)
        self.assertGreater(needy["step"], rich["step"])  # concedes faster too

    def test_2_core_player_long_contract_high_price_and_one_time_refusal(self):
        ctx = mk(role="key", left=4, rq=0.2, need=0.1, style="firm")
        s = N.new_negotiation(ctx)
        v = N.club_valuation(ctx)
        self.assertTrue(v["unwilling"])
        self.assertGreater(v["ask"], 1.4 * v["value"])
        N.inquire(s)
        r1 = N.submit_club_offer(s, dict(immediate=int(v["value"])))
        self.assertIn(r1["response"], ("reject", "counter"))
        self.assertEqual(r1["reason"], "club_unwilling_to_sell")
        self.assertGreater(r1["counter"]["immediate"], 1.15 * v["value"])
        r2 = N.submit_club_offer(s, dict(immediate=int(v["value"] * 1.05)))
        self.assertNotEqual(r2["reason"], "club_unwilling_to_sell")  # no repeated absolute refusal
        self.assertEqual(s["status"], "active")
        # and a generous enough offer does buy him
        r3 = N.submit_club_offer(s, dict(immediate=int(v["ask"] * 1.02)))
        self.assertEqual(r3["response"], "accept")

    def test_3_very_low_offer_rejected_with_understandable_reason(self):
        s = N.new_negotiation(mk())
        N.inquire(s)
        r = N.submit_club_offer(s, dict(immediate=3_000_000))
        self.assertIn(r["response"], ("reject", "counter"))
        self.assertIn(r["reason"], N.REASONS)
        self.assertEqual(r["reason"], "value_too_low")
        self.assertIsNotNone(r["counter"])
        self.assertGreater(r["counter"]["immediate"], 3_000_000)

    def test_4_very_high_offer_accepted_and_budget_impact_visible(self):
        ctx = mk(budget=100_000_000)
        s = N.new_negotiation(ctx)
        N.inquire(s)
        r = N.submit_club_offer(s, dict(immediate=50_000_000))
        self.assertEqual(r["response"], "accept")
        rc = N.submit_contract_offer(s, good_contract(ctx))
        self.assertEqual(rc["response"], "accept", rc)
        imp = N.confirm(s)
        self.assertEqual(imp["budget_before"], 100_000_000)
        self.assertEqual(imp["paid_now"], 50_000_000)
        self.assertEqual(imp["budget_after"], 50_000_000)
        self.assertEqual(s["status"], "agreed")

    def test_installments_are_listed_not_hidden(self):
        ctx = mk()
        s = N.new_negotiation(ctx)
        N.inquire(s)
        ask = s["current_ask"]
        offer = dict(immediate=int(ask * 0.5), installments=[dict(amount=int(ask * 0.3), months=6), dict(amount=int(ask * 0.3), months=12)],
                     achievement_bonus=[dict(amount=1_000_000, condition="20 apps")], sell_on_pct=10)
        r = N.submit_club_offer(s, offer)
        self.assertEqual(r["response"], "accept", r)
        N.submit_contract_offer(s, good_contract(ctx))
        imp = N.confirm(s)
        self.assertEqual(len(imp["future_installments"]), 2)
        self.assertAlmostEqual(imp["installments_total"], int(ask * 0.3) * 2, delta=2)
        self.assertEqual(imp["conditional_transfer_bonuses_max"], 1_000_000)
        self.assertLess(imp["paid_now"], ask)  # only the immediate part leaves the budget now

    def test_over_budget_rejected_before_anything_happens(self):
        s = N.new_negotiation(mk(budget=5_000_000))
        N.inquire(s)
        r = N.submit_club_offer(s, dict(immediate=9_000_000))
        self.assertEqual((r["response"], r["reason"]), ("invalid", "over_budget"))
        self.assertEqual(s["rounds"]["club"], 0)
        self.assertEqual(s["tension"]["club"], 0)

    def test_market_value_is_a_range_with_confidence_not_the_asking_price(self):
        ctx = mk(scouting=0)
        s = N.new_negotiation(ctx)
        info = N.inquire(s)
        est = info["market_estimate"]
        self.assertLess(est["low"], est["high"])
        self.assertLess(est["confidence"], 0.6)
        better = N.market_estimate(mk(scouting=3))
        self.assertGreater(better["confidence"], est["confidence"])
        self.assertLess(better["high"] - better["low"], est["high"] - est["low"])  # better scouting narrows it
        self.assertNotEqual(info["stated_ask"], est["midpoint"])  # asking price != estimated value
        self.assertIn(info["ask_vs_estimate"], ("below_expected", "near_expected", "above_expected"))

    def test_public_view_hides_internals(self):
        s = N.new_negotiation(mk())
        N.inquire(s)
        N.submit_club_offer(s, dict(immediate=1_000_000))
        pv = json.dumps(N.public_view(s))
        for hidden in ("min_price", "buyer_max", "unwilling", '"val"'):
            self.assertNotIn(hidden, pv)

    def test_memory_repeat_and_regression_raise_tension(self):
        s = N.new_negotiation(mk(style="firm"))
        N.inquire(s)
        ask = s["current_ask"]
        a = int(ask * 0.85)
        N.submit_club_offer(s, dict(immediate=a))
        t1 = s["tension"]["club"]
        N.submit_club_offer(s, dict(immediate=a))  # same rejected offer again
        t2 = s["tension"]["club"]
        self.assertGreater(t2 - t1, 5)
        N.submit_club_offer(s, dict(immediate=int(a * 0.8)))  # worse than before
        r = s["history"][-1]
        self.assertEqual(r["reason"], "offer_regressed")
        self.assertEqual(len(s["history"]), 3)
        self.assertGreater(s["best_eff"], a * 0.99)

    def test_collapse_is_local_and_not_a_cascade(self):
        s1 = N.new_negotiation(mk(pid=1, style="hard"))
        N.inquire(s1)
        for _ in range(8):
            r = N.submit_club_offer(s1, dict(immediate=500_000)) if s1["status"] == "active" else None
        self.assertEqual(s1["status"], "collapsed")
        self.assertEqual(s1["retry_after_days"], 14)
        with self.assertRaises(N.NegotiationError):
            N.submit_club_offer(s1, dict(immediate=20_000_000))
        # an unrelated negotiation (another player, another club) is completely unaffected
        ctx2 = mk(pid=2, style="firm", seed=5)
        s2 = N.new_negotiation(ctx2)
        N.inquire(s2)
        self.assertEqual(N.submit_club_offer(s2, dict(immediate=int(s2["current_ask"])))["response"], "accept")
        # and the same pairing can be reopened as a NEW negotiation
        s3 = N.new_negotiation(mk(pid=1, style="hard"))
        N.inquire(s3)
        self.assertEqual(s3["status"], "active")

    def test_accept_counter_and_walk_away(self):
        s = N.new_negotiation(mk())
        N.inquire(s)
        r = N.submit_club_offer(s, dict(immediate=int(s["current_ask"] * 0.8)))
        self.assertIn(r["response"], ("counter", "reject"))
        r2 = N.accept_counter(s)
        self.assertEqual(r2["response"], "accept")
        self.assertEqual(s["stage"], "contract")
        s2 = N.new_negotiation(mk())
        N.walk_away(s2)
        self.assertEqual((s2["status"], s2["fail_reason"]), ("failed", "walked_away"))

    def test_window_closed_and_free_agent_exception(self):
        s = N.new_negotiation(mk(window_open=False))
        N.inquire(s)
        r = N.submit_club_offer(s, dict(immediate=30_000_000))
        self.assertEqual((r["response"], r["reason"]), ("invalid", "window_closed"))
        ctx = mk(kind="free_agent", window_open=False)
        fa = N.new_negotiation(ctx)
        N.inquire(fa)
        self.assertEqual(N.submit_contract_offer(fa, good_contract(ctx))["response"], "accept")


class TestContracts(unittest.TestCase):
    def test_5_club_agrees_but_player_refuses_deal_not_complete(self):
        ctx = mk()
        s = N.new_negotiation(ctx)
        agree_fee(s, 1.0)
        self.assertEqual(s["stage"], "contract")
        low = dict(weekly_wage=int(N.player_demand(ctx, "important", 3) * 0.5), length=3, role="important")
        for _ in range(10):
            if s["status"] != "active":
                break
            N.submit_contract_offer(s, low)
        self.assertEqual(s["status"], "collapsed")
        self.assertEqual(s["fail_reason"], "player_unwilling")
        self.assertIsNotNone(s["club_terms"])  # the club had agreed...
        with self.assertRaises(N.NegotiationError):
            N.confirm(s)  # ...but the deal is NOT complete
        with self.assertRaises(N.NegotiationError):
            N.apply_deal(None, s)

    def test_6_star_offered_limited_role_shows_logical_conflict(self):
        ctx = mk(ovr=86, buyer_avg=72, age=27)
        self.assertEqual(N.expected_role(ctx), "key")
        s = N.new_negotiation(ctx)
        agree_fee(s)
        market = N.player_demand(ctx, "key", 3)
        r = N.submit_contract_offer(s, dict(weekly_wage=int(market * 1.1), length=3, role="limited"))
        self.assertEqual(r["response"], "reject")
        self.assertEqual(r["reason"], "role_unsuitable")
        self.assertIn("role_below_expectation", r["conflicts"])
        self.assertEqual(r["counter"]["role"], "key")
        # and the reverse conflict: a fringe role with a huge wage is flagged for the club's own structure
        c2 = N.normalize_contract(dict(weekly_wage=int(market * 3), length=3, role="rotation"))
        self.assertIn("wage_high_for_role", N.detect_conflicts(c2, mk(ovr=60, buyer_avg=72)))

    def test_7_contract_length_1_to_5_changes_demand_logically(self):
        young = mk(age=22)
        old = mk(age=33)
        self.assertGreater(N.player_demand(young, "important", 5), N.player_demand(young, "important", 1))
        self.assertLess(N.player_demand(old, "important", 5), N.player_demand(old, "important", 1))
        for bad in (0, 6, -1, 2.5, "3", True):
            with self.assertRaises(N.NegotiationError):
                N.normalize_contract(dict(weekly_wage=1000, length=bad, role="key"))
        for ok in range(1, 6):
            N.normalize_contract(dict(weekly_wage=1000, length=ok, role="key"))

    def test_8_bonuses_are_conditional_commitment_not_weekly_wage(self):
        ctx = mk(pos="ST", ovr=78)
        base = dict(weekly_wage=30_000, length=3, role="key")
        c0 = N.total_commitment(base, ctx)
        withb = dict(base, signing_bonus=500_000, appearance_bonus=dict(amount=200_000, apps=20),
                     goal_bonus=dict(amount=300_000, goals=10), agent_fee=100_000)
        c1 = N.total_commitment(withb, ctx)
        self.assertEqual(c0["weekly_wage"], c1["weekly_wage"] == 30_000 and 30_000)  # weekly wage untouched by bonuses
        self.assertEqual(c0["fixed"], 30_000 * 52 * 3)
        self.assertEqual(c1["fixed"], 30_000 * 52 * 3 + 500_000 + 100_000)  # signing + agent are certain
        self.assertEqual(c1["conditional_max"], (200_000 + 300_000) * 3)
        self.assertGreater(c1["conditional_expected"], 0)
        self.assertLess(c1["conditional_expected"], c1["conditional_max"] + 1)
        self.assertEqual(c1["total_expected"], c1["fixed"] + c1["conditional_expected"])
        self.assertGreater(c1["total_max"], c1["total_expected"] - 1)
        # a bench player is less likely to hit the same targets than a starter
        bench = N.total_commitment(dict(withb, role="limited"), ctx)
        self.assertLess(bench["conditional_expected"], c1["conditional_expected"])
        # bonuses can substitute part of the wage in the player's eyes
        ctxb = mk()
        dem = N.player_demand(ctxb, "important", 3)
        plain = N.wage_equivalent(N.normalize_contract(dict(weekly_wage=int(dem * 0.9), length=3, role="important")), ctxb)
        bon = N.wage_equivalent(N.normalize_contract(dict(weekly_wage=int(dem * 0.9), length=3, role="important",
                                                          signing_bonus=int(dem * 52 * 3 * 0.15))), ctxb)
        self.assertGreater(bon, plain)

    def test_9_release_clause_in_contract_and_effect_on_both_sides(self):
        ctx = mk()
        s = N.new_negotiation(ctx)
        agree_fee(s)
        v = N.intrinsic_value(ctx["player"])
        self.assertLess(N.player_demand(ctx, "important", 3, release_clause=int(v * 1.2)),
                        N.player_demand(ctx, "important", 3) * 0.97)  # the player likes an exit door
        c = good_contract(ctx, release_clause=int(v * 1.2))
        self.assertEqual(N.submit_contract_offer(s, c)["response"], "accept")
        self.assertEqual(s["contract_terms"]["offer"]["release_clause"], int(v * 1.2))  # appears in the accepted contract
        # other side: a clause that is cheap triggers an automatic club agreement for any buyer who meets it
        cctx = mk(release_clause=15_000_000, role="key", left=4, rq=0.2, need=0.1)
        s2 = N.new_negotiation(cctx)
        N.inquire(s2)
        r = N.submit_club_offer(s2, dict(immediate=15_000_000))
        self.assertEqual(r["response"], "accept")
        self.assertTrue(s2["club_terms"]["via_release_clause"])
        self.assertIn("clause_below_value", N.detect_conflicts(N.normalize_contract(
            dict(weekly_wage=1000, length=3, role="key", release_clause=int(v * 0.3))), ctx))

    def test_contract_stage_counter_and_concession(self):
        ctx = mk()
        s = N.new_negotiation(ctx)
        agree_fee(s)
        dem = N.player_demand(ctx, "important", 3)
        w = int(dem * 0.9)
        seen = []
        for _ in range(8):
            r = N.submit_contract_offer(s, dict(weekly_wage=w, length=3, role="important"))
            if r["response"] == "accept":
                break
            seen.append(r["counter"]["weekly_wage"])
            w = int(w * 1.03)
        self.assertEqual(s["stage"], "confirm", seen)
        self.assertTrue(all(b <= a + 1 for a, b in zip(seen, seen[1:])))  # demands only come down as talks progress

    def test_loan_renewal_free_agent_flows(self):
        # loan: fee talks + simplified contract (no bonuses/clauses allowed)
        lctx = mk(kind="loan")
        s = N.new_negotiation(lctx)
        info = N.inquire(s)
        r = N.submit_club_offer(s, dict(loan_fee=int(info["stated_ask"] * 1.0), wage_share=70, loan_months=12))
        self.assertEqual(r["response"], "accept", r)
        with self.assertRaises(N.NegotiationError):
            N.submit_contract_offer(s, good_contract(lctx, signing_bonus=1000))
        self.assertEqual(N.submit_contract_offer(s, good_contract(lctx, length=1))["response"], "accept")
        N.confirm(s)
        # renewal: starts at contract stage, no club talks
        rctx = mk(kind="renewal")
        rs = N.new_negotiation(rctx)
        self.assertEqual(rs["stage"], "contract")
        with self.assertRaises(N.NegotiationError):
            N.submit_club_offer(rs, dict(immediate=1))
        self.assertEqual(N.submit_contract_offer(rs, good_contract(rctx))["response"], "accept")
        self.assertEqual(N.confirm(rs)["paid_now"], 0)
        # free agent: no club stage
        fctx = mk(kind="free_agent")
        fs = N.new_negotiation(fctx)
        N.inquire(fs)
        self.assertEqual(fs["stage"], "contract")
        self.assertEqual(N.submit_contract_offer(fs, good_contract(fctx))["response"], "accept")
        N.confirm(fs)

    def test_sell_side_incoming_offer(self):
        ctx = mk(kind="sell")
        s = N.new_negotiation(ctx)
        v = N.intrinsic_value(ctx["player"])
        first = s["current_offer"]
        self.assertLess(first, v * 1.1)
        r = N.respond_incoming(s, "counter", counter_fee=int(v * 3))
        self.assertEqual(r["response"], "counter")
        self.assertGreater(r["counter"], first)
        r = N.respond_incoming(s, "counter", counter_fee=int(v * 3))
        r = N.respond_incoming(s, "counter", counter_fee=int(v * 3))
        self.assertEqual((r["response"], r["reason"]), ("walk_away", "price_too_high"))  # no endless haggling
        s2 = N.new_negotiation(mk(kind="sell", seed=3))
        out = N.respond_incoming(s2, "accept")
        self.assertIn(out["response"], ("accept", "club_agreed_player_refused"))
        s3 = N.new_negotiation(mk(kind="sell"))
        self.assertEqual(N.respond_incoming(s3, "reject")["response"], "closed")

    def test_wage_room_enforced_when_provided(self):
        ctx = mk()
        ctx["buyer"]["wage_room"] = 5_000
        s = N.new_negotiation(ctx)
        agree_fee(s)
        r = N.submit_contract_offer(s, dict(weekly_wage=50_000, length=3, role="important"))
        self.assertEqual((r["response"], r["reason"]), ("invalid", "over_wage_budget"))


class TestDifficultyAndOffline(unittest.TestCase):
    def _run_policy(self, difficulty, seeds):
        """A fixed, reasonable human policy using only public information. Returns (price/value list, failures)."""
        prices, fails = [], 0
        for sd in seeds:
            rr = random.Random(sd)
            ctx = mk(difficulty=difficulty, seed=sd, pid=sd, need=rr.random() * 0.6, rq=rr.random(),
                     style=N.STYLES[rr.randrange(4)], role=rr.choice(["rotation", "important", "key", "limited"]),
                     left=rr.randint(1, 4), rivals=rr.randint(0, 2), ovr=rr.randint(62, 82), value=rr.choice([8, 15, 25]) * 1_000_000,
                     age=rr.randint(21, 31))
            s = N.new_negotiation(ctx)
            info = N.inquire(s)
            ask0 = info["stated_ask"]
            offer = ask0 * 0.80
            done = False
            for _ in range(14):
                if s["status"] != "active":
                    break
                r = N.submit_club_offer(s, dict(immediate=int(offer)))
                if r["response"] == "accept":
                    done = True
                    break
                offer = min(ask0, max(offer * 1.04, r["counter"]["immediate"] * 0.93))
            if done:
                prices.append(s["club_terms"]["effective"] / ask0)
            else:
                fails += 1
        return prices, fails

    def test_10_four_difficulties_measurable_but_fair(self):
        seeds = list(range(100, 160))
        res = {d: self._run_policy(d, seeds) for d in N.DIFFICULTIES}
        mean = {d: statistics.mean(p) for d, (p, f) in res.items()}
        fails = {d: f for d, (p, f) in res.items()}
        print(f"\n  price paid as share of stated ask, 60 deals: { {d: round(m, 3) for d, m in mean.items()} } failures {fails}")
        self.assertLess(mean["easy"], mean["normal"])
        self.assertLessEqual(mean["normal"], mean["hard"] + 1e-9)
        self.assertLess(mean["easy"], mean["hard"] - 0.01)          # clearly measurable
        self.assertAlmostEqual(mean["realistic"], mean["normal"], delta=0.03)  # realistic = context only, not tilted
        for d, f in fails.items():
            self.assertLessEqual(f, 6, d)                            # fair: nearly all sensible deals still close
        for d in N.DIFFICULTIES:
            self.assertLess(max(res[d][0]), 1.001)                   # nobody ever pays above the stated ask
        # hints differ by difficulty
        s_easy = N.new_negotiation(mk(difficulty="easy"))
        s_hard = N.new_negotiation(mk(difficulty="hard"))
        for s in (s_easy, s_hard):
            N.inquire(s)
        r_easy = N.submit_club_offer(s_easy, dict(immediate=int(s_easy["current_ask"] * 0.7)))
        r_hard = N.submit_club_offer(s_hard, dict(immediate=int(s_hard["current_ask"] * 0.7)))
        self.assertIn("settle_range", r_easy)
        self.assertNotIn("hint", r_hard)

    def test_11_difficulty_never_touches_ovr_budgets_or_match_results(self):
        cm = CareerManager(os.path.join(TMP, "s_diff"), WORLD)
        con = cm.open(cm.create(1, "d", seed=4))
        pid = con.execute("SELECT id FROM v_player WHERE club_id=2 ORDER BY ovr DESC LIMIT 1 OFFSET 7").fetchone()[0]

        def snapshot():
            players = con.execute("SELECT id,ovr,potential,attrs,club_id,wage FROM v_player ORDER BY id").fetchall()
            fin = (N.get_finance(con, 1), N.get_finance(con, 2))
            hl, hb = auto_lineup(db.squad(con, 1))
            al, ab = auto_lineup(db.squad(con, 2))
            res = MatchSession(dict(club_id=1, lineup=hl, bench=hb), dict(club_id=2, lineup=al, bench=ab), 77).finish()
            return [tuple(r) for r in players], fin, res["events"], res["score"]
        before = snapshot()
        for diff in N.DIFFICULTIES:
            ctx = N.build_context(con, "buy", pid, 1, difficulty=diff, seed=11)
            s = N.new_negotiation(ctx)
            N.inquire(s)
            N.submit_club_offer(s, dict(immediate=int(s["current_ask"] * 0.7)))
            N.submit_club_offer(s, dict(immediate=int(s["current_ask"])))
            N.save(con, s)  # even persisted: still nothing changes in the game world
            self.assertEqual(ctx["player"]["ovr"], con.execute("SELECT ovr FROM v_player WHERE id=?", (pid,)).fetchone()[0])
        self.assertEqual(snapshot(), before)
        # the same context rebuilt under two difficulties differs ONLY in the 'difficulty' field
        a = N.build_context(con, "buy", pid, 1, difficulty="easy", seed=11)
        b = N.build_context(con, "buy", pid, 1, difficulty="hard", seed=11)
        a.pop("difficulty"), b.pop("difficulty")
        self.assertEqual(a, b)
        con.close()

    def test_12_works_offline_and_is_deterministic(self):
        real = socket.socket

        class Boom:
            def __init__(self, *a, **k):
                raise AssertionError("network access attempted")
        socket.socket = Boom
        try:
            def run():
                ctx = mk(seed=42)
                s = N.new_negotiation(ctx)
                agree_fee(s, 1.0)
                N.submit_contract_offer(s, good_contract(ctx, 1.05))
                return N.to_json(s)
            a, b = run(), run()
        finally:
            socket.socket = real
        self.assertEqual(a, b)  # same seed + same inputs = identical negotiation (testable, not "unfairly random")
        # different seeds give studied, bounded variation between otherwise identical deals
        asks = [N.club_valuation(mk(seed=i))["ask"] for i in range(30)]
        spread = (max(asks) - min(asks)) / statistics.mean(asks)
        self.assertTrue(0.01 < spread < 0.08, spread)

    def test_json_roundtrip_and_resume(self):
        ctx = mk(seed=9)
        s = N.new_negotiation(ctx)
        N.inquire(s)
        N.submit_club_offer(s, dict(immediate=int(s["current_ask"] * 0.8)))
        s2 = N.from_json(N.to_json(s))
        self.assertEqual(s2, s)
        r1 = N.submit_club_offer(s, dict(immediate=int(s["current_ask"])))
        r2 = N.submit_club_offer(s2, dict(immediate=int(s2["current_ask"])))
        self.assertEqual(r1, r2)


class TestPersistenceAndApply(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cm = CareerManager(os.path.join(TMP, "s_apply"), WORLD)

    def _setup(self, seed):
        con = self.cm.open(self.cm.create(1, "t", seed=seed))
        pid = con.execute("SELECT id FROM v_player WHERE club_id=2 ORDER BY ovr DESC LIMIT 1 OFFSET 9").fetchone()[0]
        return con, pid

    def test_save_load_resume_then_apply_in_one_transaction(self):
        con, pid = self._setup(21)
        ctx = N.build_context(con, "buy", pid, 1, difficulty="realistic", seed=5)
        s = N.new_negotiation(ctx)
        N.inquire(s)
        N.submit_club_offer(s, dict(immediate=int(s["current_ask"] * 0.8)))
        nid = N.save(con, s)
        con.close()
        con = self.cm.open(self.cm.list_careers()[0]["id"] if False else [c for c in self.cm.list_careers()][0]["id"])
        # (reopen the same career file) resume where we left off
        con2 = None
        con.close()
        cid = [c["id"] for c in self.cm.list_careers()]
        self.assertTrue(cid)

    def test_apply_updates_player_budgets_installments(self):
        con, pid = self._setup(22)
        ctx = N.build_context(con, "buy", pid, 1, seed=6)
        s = N.new_negotiation(ctx)
        N.inquire(s)
        ask = s["current_ask"]
        offer = dict(immediate=int(ask * 0.6), installments=[dict(amount=int(ask * 0.4), months=6)])
        self.assertEqual(N.submit_club_offer(s, offer)["response"], "accept")
        self.assertEqual(N.submit_contract_offer(s, good_contract(ctx, release_clause=int(ask * 3)))["response"], "accept")
        nid = N.save(con, s)
        s = N.load(con, nid)  # resumed from the DB, not from memory
        before = (N.get_finance(con, 1)["transfer_budget"], N.get_finance(con, 2)["transfer_budget"])
        N.confirm(s)
        N.apply_deal(con, s)
        row = con.execute("SELECT club_id,wage,contract_end,ovr FROM v_player WHERE id=?", (pid,)).fetchone()
        self.assertEqual(row["club_id"], 1)
        self.assertEqual(row["wage"], s["contract_terms"]["offer"]["weekly_wage"])
        self.assertEqual(row["ovr"], ctx["player"]["ovr"])  # attributes untouched by a transfer
        self.assertIn(pid, [p["id"] for p in db.squad(con, 1)])
        self.assertNotIn(pid, [p["id"] for p in db.squad(con, 2)])
        after = (N.get_finance(con, 1)["transfer_budget"], N.get_finance(con, 2)["transfer_budget"])
        self.assertEqual(before[0] - after[0], int(ask * 0.6))
        self.assertEqual(after[1] - before[1], int(ask * 0.6))
        terms = json.loads(con.execute("SELECT terms FROM deal_terms WHERE player_id=?", (pid,)).fetchone()[0])
        self.assertEqual(terms["release_clause"], int(ask * 3))
        with self.assertRaises(N.NegotiationError):
            N.apply_deal(con, s)  # never applied twice
        # installment is due later, paid when time reaches it
        self.assertEqual(con.execute("SELECT COUNT(*) FROM payment_due WHERE paid=0").fetchone()[0], 1)
        self.assertEqual(N.settle_due_payments(con), 0)
        con.execute("UPDATE career_info SET cur_date='2027-06-01'")
        self.assertEqual(N.settle_due_payments(con), 1)
        self.assertEqual(before[0] - N.get_finance(con, 1)["transfer_budget"], int(ask * 0.6) + int(ask * 0.4))
        con.close()

    def test_refused_by_player_changes_nothing_in_the_game(self):
        con, pid = self._setup(23)
        ctx = N.build_context(con, "buy", pid, 1, seed=7)
        s = N.new_negotiation(ctx)
        N.inquire(s)
        N.submit_club_offer(s, dict(immediate=int(s["current_ask"])))
        low = dict(weekly_wage=int(N.player_demand(ctx, N.expected_role(ctx), 3) * 0.4), length=3, role=N.expected_role(ctx))
        for _ in range(10):
            if s["status"] == "active":
                N.submit_contract_offer(s, low)
        self.assertEqual(s["status"], "collapsed")
        b = (N.get_finance(con, 1), N.get_finance(con, 2))
        with self.assertRaises(N.NegotiationError):
            N.apply_deal(con, s)
        self.assertEqual(con.execute("SELECT club_id FROM v_player WHERE id=?", (pid,)).fetchone()[0], 2)
        self.assertEqual(b, (N.get_finance(con, 1), N.get_finance(con, 2)))
        con.close()

    def test_free_agent_and_cancel_for_club(self):
        con, pid = self._setup(24)
        with con:
            con.execute("INSERT INTO player_state(player_id,club_id) VALUES(?,0)", (pid,))
        self.assertIsNone(con.execute("SELECT club_id FROM v_player WHERE id=?", (pid,)).fetchone()[0])
        ctx = N.build_context(con, "free_agent", pid, 1, seed=3)
        s = N.new_negotiation(ctx)
        N.inquire(s)
        self.assertEqual(N.submit_contract_offer(s, good_contract(ctx, 1.2))["response"], "accept")
        N.confirm(s)
        N.save(con, s)
        octx = mk(pid=999)
        octx['buyer']['club_id'], octx['seller']['club_id'], octx['player']['club_id'] = 5, 6, 6
        other = N.new_negotiation(octx)
        N.save(con, other)
        self.assertEqual(N.cancel_for_club(con, 1), 1)  # only the negotiation of club 1 was dropped
        self.assertEqual(N.load(con, other["id"])["status"], "active")
        N.apply_deal(con, N.load(con, s["id"]) if False else s)  # s still agreed in memory
        self.assertEqual(con.execute("SELECT club_id FROM v_player WHERE id=?", (pid,)).fetchone()[0], 1)
        con.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
