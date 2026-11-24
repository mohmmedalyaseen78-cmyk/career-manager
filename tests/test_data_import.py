import os
import sys
import unittest
from unittest import mock

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "data_import"))
import build_squads as B  # noqa: E402


class Resp:
    def __init__(self, code, data=None):
        self.status_code, self._d = code, data or {}

    def json(self):
        return self._d

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def item(i, first, last, ovr, team, gender=0, common=""):
    return dict(id=i, firstName=first, lastName=last, commonName=common, overallRating=ovr,
                team=dict(label=team), gender=dict(id=gender))


class TestEAHandling(unittest.TestCase):
    def test_denied_access_stops_immediately_without_retries(self):
        calls = []

        def fake_get(*a, **k):
            calls.append(1)
            return Resp(403)
        with mock.patch.object(B.requests, "get", fake_get), mock.patch.object(B.time, "sleep") as sl:
            with self.assertRaises(B.EAAccessDenied):
                B.fetch_ea_page(0)
        self.assertEqual(len(calls), 1)      # no retry, no workaround
        sl.assert_not_called()

    def test_rate_limit_also_stops(self):
        with mock.patch.object(B.requests, "get", lambda *a, **k: Resp(429)):
            with self.assertRaises(B.EAAccessDenied):
                B.fetch_ea_page(0)

    def test_parse_index_skips_women_and_bad_ovr(self):
        pages = {0: dict(totalItems=4, items=[item(1, "Aaa", "Bbb", 80, "Club A"), item(2, "Ccc", "Ddd", 90, "Club B", gender=1),
                                              item(3, "Eee", "Fff", 150, "Club C"), item(4, "Ggg", "Hhh", 70, "Club D")])}
        with mock.patch.object(B, "fetch_ea_page", lambda off: pages[off]):
            index, meta = B.fetch_ea_official_ovrs()
        self.assertIn("aaa bbb", index)
        self.assertNotIn("ccc ddd", index)       # women's item skipped
        self.assertNotIn("eee fff", index)       # impossible OVR skipped
        self.assertEqual(meta["unique_male_player_items"], 2)

    def test_matching_never_guesses(self):
        idx = {"john smith": [dict(ovr=70, team_norm="arsenal"), dict(ovr=60, team_norm="chelsea")],
               "ana lopez": [dict(ovr=75, team_norm="valencia", source_url="u")]}
        self.assertEqual(B.match_ea_ovr("Ana López", "Valencia CF", idx)["ovr"], 75)
        self.assertEqual(B.match_ea_ovr("John Smith", "Arsenal FC", idx)["ovr"], 70)   # club disambiguates
        self.assertIsNone(B.match_ea_ovr("John Smith", "Everton", idx))                # ambiguous -> no guess
        self.assertIsNone(B.match_ea_ovr("Unknown Guy", "Arsenal", idx))


class TestEstimator(unittest.TestCase):
    def row(self, **k):
        d = dict(base_ovr=68, age=26, recent_apps=30, senior_caps=0, award_bonus=0, impact_percentile=50, has_recent_stats=True)
        d.update(k)
        return pd.Series(d)

    def test_range_and_ordering(self):
        for pct in (0, 50, 100):
            v = B.estimate_ovr(self.row(impact_percentile=pct))
            self.assertTrue(48 <= v <= 89)
        self.assertGreater(B.estimate_ovr(self.row(impact_percentile=95)), B.estimate_ovr(self.row(impact_percentile=10)))
        self.assertGreater(B.estimate_ovr(self.row(base_ovr=68)), B.estimate_ovr(self.row(base_ovr=63)))
        self.assertLess(B.estimate_ovr(self.row(age=38)), B.estimate_ovr(self.row(age=27)))

    def test_no_stats_no_invented_bonus(self):
        a = B.estimate_ovr(self.row(has_recent_stats=False, recent_apps=0, impact_percentile=99))
        b = B.estimate_ovr(self.row(has_recent_stats=False, recent_apps=0, impact_percentile=1))
        self.assertEqual(a, b)

    def test_normalize(self):
        self.assertEqual(B.normalize_name("Kylian Mbappé"), "kylian mbappe")
        self.assertEqual(B.normalize_club("Real Madrid CF"), "real madrid")


if __name__ == "__main__":
    unittest.main(verbosity=2)
