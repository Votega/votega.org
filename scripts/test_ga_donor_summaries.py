#!/usr/bin/env python3
"""Tests for generate_ga_donor_summaries.py, with a fake API and no network.

Run: python scripts/test_ga_donor_summaries.py
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import generate_ga_donor_summaries as g  # noqa: E402


def fake_post_factory(top=None, cats=None, geo=None, fail=False):
    def fake_post(path, payload, retries=3):
        if fail:
            return None
        if path.endswith("GetTopDonorsAndPayees"):
            return {"succeeded": True, "data": top if top is not None else []}
        if path.endswith("GetContributionsCategoriesDetails"):
            return {"succeeded": True, "data": cats if cats is not None else []}
        if path.endswith("GetContributionsInStateAndOutStateDetail"):
            return {"succeeded": True, "data": geo if geo is not None else []}
        raise AssertionError(path)
    return fake_post


class FetchSummary(unittest.TestCase):
    def setUp(self):
        self._sleep = mock.patch.object(g.time, "sleep", lambda *_: None)
        self._sleep.start()

    def tearDown(self):
        self._sleep.stop()

    def run_with(self, **kw):
        with mock.patch.object(g.base, "post", fake_post_factory(**kw)):
            return g.fetch_summary("guid")

    def test_shapes_and_cleans(self):
        s = self.run_with(
            top=[{"sourceName": "Kahn,   Matthew ", "transactionAmount": 2000.0, "cityState": "Atlanta, GA"},
                 {"sourceName": "", "transactionAmount": 5.0},          # nameless: dropped
                 {"sourceName": "Zero", "transactionAmount": 0}],       # no money: dropped
            cats=[{"amount": 10.0, "transactionSourceTypeCode": "TIND", "transactionSourceType": "Individual"},
                  {"amount": 30.0, "transactionSourceTypeCode": "TBSN", "transactionSourceType": "Business"},
                  {"amount": 0, "transactionSourceTypeCode": "TNCC", "transactionSourceType": "Committee"}],
            geo=[{"inStateAmount": 7.0, "outOfStateAmount": 3.0, "unItemizedAmount": 1.0}])
        self.assertEqual(s["largest"], [{"name": "Kahn, Matthew", "amount": 2000.0, "place": "Atlanta, GA"}])
        self.assertEqual([t["code"] for t in s["byType"]], ["TBSN", "TIND"])   # sorted, zero dropped
        self.assertEqual((s["inState"], s["outOfState"], s["unitemized"]), (7.0, 3.0, 1.0))

    def test_any_failed_call_is_none_not_partial(self):
        # A half-built summary would publish as fact that a candidate had no donors.
        self.assertIsNone(self.run_with(fail=True))

    def test_empty_geo_is_tolerated(self):
        s = self.run_with(top=[], cats=[], geo=[])
        self.assertEqual(s["largest"], [])
        self.assertIsNone(s["inState"])


class Main(unittest.TestCase):
    """The carry-forward and failure-floor rules, which decide what gets published."""

    def run_main(self, roster, prev, fetch_results, prev_doc=None):
        written = {}
        rows = [{"filerEntityId": fid, "guid": f"g{fid}", "totalContributions": raised,
                 "electionCycleName": "2026 Georgia State Election"}
                for fid, raised in roster.items()]
        calls = []

        def fake_fetch(guid):
            calls.append(guid)
            return fetch_results.get(guid)

        with mock.patch.object(g.base, "fetch_office", lambda oid: (rows if oid == "10" else [], True)), \
             mock.patch.object(g.base, "target_cycle", lambda: 2026), \
             mock.patch.object(g.time, "sleep", lambda *_: None), \
             mock.patch.object(g, "load_previous", lambda: prev), \
             mock.patch.object(g, "load_previous_doc",
                               lambda: prev_doc if prev_doc is not None else {"filers": prev}), \
             mock.patch.object(g, "fetch_summary", fake_fetch), \
             mock.patch.object(g, "write_json_atomic", lambda path, obj, **kw: written.update(obj)), \
             mock.patch.object(sys, "argv", ["x"]):
            g.main()
        return written, calls

    def test_unchanged_total_is_carried_not_refetched(self):
        prev = {"1": {"raised": 100.0, "largest": ["old"]}}
        out, calls = self.run_main({"1": 100.0}, prev, {})
        self.assertEqual(calls, [])
        self.assertEqual(out["filers"]["1"]["largest"], ["old"])

    def test_changed_total_is_refetched(self):
        prev = {"1": {"raised": 100.0}}
        out, calls = self.run_main({"1": 250.0}, prev, {"g1": {"largest": []}})
        self.assertEqual(calls, ["g1"])
        self.assertEqual(out["filers"]["1"]["raised"], 250.0)

    def test_zero_raised_gets_no_entry_and_no_calls(self):
        out, calls = self.run_main({"1": 0}, {}, {})
        self.assertEqual(calls, [])
        self.assertEqual(out["filers"], {})

    def test_failed_fetch_keeps_previous_entry(self):
        prev = {"1": {"raised": 100.0, "largest": ["old"]}}
        roster = {"1": 250.0, **{str(i): 100.0 for i in range(2, 8)}}
        results = {f"g{i}": {"largest": []} for i in range(2, 8)}   # only #1 fails (1/7 < floor)
        out, _ = self.run_main(roster, prev, results)
        self.assertEqual(out["filers"]["1"]["largest"], ["old"])
        self.assertEqual(out["metadata"]["failedFilers"], ["1"])

    def test_quiet_week_rewrites_the_previous_document_byte_for_byte(self):
        # generatedAt / fetchedThisRun are run-scoped; if they were rewritten, every
        # weekly run would commit a diff even when no donor changed.
        prev = {"1": {"raised": 100.0, "largest": []}}
        prev_doc = {"metadata": {"generatedAt": "2026-10-11T00:00:00+00:00", "cycle": 2026,
                                 "fetchedThisRun": 9, "failedFilers": []},
                    "filers": prev}
        out, calls = self.run_main({"1": 100.0}, prev, {}, prev_doc=prev_doc)
        self.assertEqual(calls, [])
        self.assertEqual(out, prev_doc)

    def test_changed_data_gets_a_fresh_timestamp(self):
        prev = {"1": {"raised": 100.0, "largest": []}}
        prev_doc = {"metadata": {"generatedAt": "OLD", "cycle": 2026, "failedFilers": []},
                    "filers": prev}
        out, _ = self.run_main({"1": 250.0}, prev, {"g1": {"largest": []}}, prev_doc=prev_doc)
        self.assertNotEqual(out["metadata"]["generatedAt"], "OLD")

    def test_mostly_failed_run_refuses_to_publish(self):
        roster = {str(i): 100.0 for i in range(1, 5)}
        with self.assertRaises(SystemExit):
            self.run_main(roster, {}, {})   # every fetch fails


if __name__ == "__main__":
    unittest.main()
