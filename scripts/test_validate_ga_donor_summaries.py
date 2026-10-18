#!/usr/bin/env python3
"""Tests for validate_ga_donor_summaries.py: plain dicts, no files, no network.

tier2() is called directly with two dicts rather than through a fixture file, because
baseline() shells out to `git show` and silently returns None for a path outside the
repo, which would disable the diff checks and print "no material change".

Run: python scripts/test_validate_ga_donor_summaries.py
"""
import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import validate_ga_donor_summaries as v  # noqa: E402


def entry(raised=1000.0):
    return {"raised": raised,
            "largest": [{"name": "A Giver", "amount": 500.0, "place": "Atlanta, GA"}],
            "byType": [{"type": "Individual", "code": "TIND", "amount": 700.0},
                       {"type": "Business", "code": "TBSN", "amount": 200.0}],
            "inState": 800.0, "outOfState": 100.0, "unitemized": None}


def doc(**filers):
    return {"metadata": {"generatedAt": "2026-10-18T00:00:00+00:00", "cycle": 2026,
                         "count": len(filers), "failedFilers": []},
            "filers": filers}


def finance(**totals):
    return {"metadata": {"cycle": 2026},
            "filers": {k: {"filerName": f"Name {k}", "totalRaised": t} for k, t in totals.items()}}


class Tier1(unittest.TestCase):
    def test_good_file_passes(self):
        self.assertEqual(v.tier1(doc(**{"1": entry(), "2": entry()})), [])

    def test_empty_file_is_not_a_contradiction(self):
        # Early in a cycle nobody has raised money: the calendar, not a bug.
        self.assertEqual(v.tier1(doc()), [])

    def mutated(self, mutate, expect):
        """Negative control: break one thing and confirm tier 1 names it."""
        d = doc(**{"1": entry()})
        mutate(d)
        errs = v.tier1(d)
        self.assertTrue(any(expect in e for e in errs), (expect, errs))

    def test_each_contradiction_is_caught(self):
        self.mutated(lambda d: d["metadata"].update(count=5), "metadata.count")
        self.mutated(lambda d: d["metadata"].pop("generatedAt"), "generatedAt")
        self.mutated(lambda d: d["metadata"].pop("failedFilers"), "failedFilers")
        self.mutated(lambda d: d["filers"]["1"].pop("largest"), "missing largest")
        self.mutated(lambda d: d["filers"]["1"].pop("unitemized"), "missing unitemized")
        self.mutated(lambda d: d["filers"]["1"].update(raised=0), "raised")
        self.mutated(lambda d: d["filers"]["1"].update(raised="9"), "raised")
        self.mutated(lambda d: d["filers"]["1"]["largest"].extend(
            [{"name": "x", "amount": 1.0}] * 10), "over the cap")
        self.mutated(lambda d: d["filers"]["1"]["largest"].append({"name": "", "amount": 5}), "largest row")
        self.mutated(lambda d: d["filers"]["1"]["largest"].append({"name": "x", "amount": 0}), "largest row")
        self.mutated(lambda d: d["filers"]["1"]["byType"].append(
            {"type": "Dup", "code": "TIND", "amount": 1.0}), "repeats")
        self.mutated(lambda d: d["filers"]["1"]["byType"].append(
            {"type": "Neg", "code": "TX", "amount": -4.0}), "byType row")
        self.mutated(lambda d: d["filers"]["1"].update(inState=-1.0), "inState")
        self.mutated(lambda d: d["filers"]["1"].update(outOfState="9"), "outOfState")

    def test_absent_key_and_null_are_different_things(self):
        d = doc(**{"1": entry()})
        d["filers"]["1"]["inState"] = None          # a value: fine
        self.assertEqual(v.tier1(d), [])
        del d["filers"]["1"]["inState"]             # a bug
        self.assertTrue(v.tier1(d))

    def test_not_a_dict_at_all(self):
        self.assertTrue(v.tier1({"metadata": {}, "filers": []}))
        self.assertTrue(v.tier1({"filers": {}}))

    def test_cap_matches_the_generator(self):
        import generate_ga_donor_summaries as g
        self.assertEqual(v.LARGEST_CAP, g.TOP_N)


class Tier2(unittest.TestCase):
    def headings(self, sections):
        return [h for h, _ in sections]

    def test_clean_run_reports_nothing(self):
        new = doc(**{"1": entry(1000.0)})
        self.assertEqual(v.tier2(new, copy.deepcopy(new), finance(**{"1": 1000.0})), [])

    def test_empty_file_is_reported_not_gated(self):
        self.assertIn("No donor entries", self.headings(v.tier2(doc(), None, None)))

    def test_failed_filers_are_named_and_split_by_whether_they_keep_an_entry(self):
        new = doc(**{"1": entry()})
        new["metadata"]["failedFilers"] = ["1", "9"]
        secs = dict(v.tier2(new, None, finance(**{"1": 1000.0, "9": 500.0})))
        text = "\n".join(secs["Filers the generator could not fetch"])
        self.assertIn("Name 1 (1)", text)
        self.assertIn("Name 9 (9)", text)
        self.assertIn("1 of them keep", text)

    def test_stale_entry_is_the_headline_staleness_signal(self):
        new = doc(**{"1": entry(1000.0)})
        secs = dict(v.tier2(new, None, finance(**{"1": 2500.0})))
        self.assertIn("Name 1 (1)", "\n".join(secs["Donor detail is behind the headline totals"]))

    def test_filer_with_money_but_no_entry(self):
        new = doc(**{"1": entry(1000.0)})
        secs = dict(v.tier2(new, None, finance(**{"1": 1000.0, "2": 400.0, "3": 0})))
        text = "\n".join(secs["Filers with money but no donor detail"])
        self.assertIn("Name 2 (2)", text)
        self.assertNotIn("Name 3", text)            # no money: nothing to break down

    def test_orphan_and_cycle_mismatch(self):
        new = doc(**{"7": entry()})
        fin = finance(**{"1": 5.0})
        fin["metadata"]["cycle"] = 2028
        h = self.headings(v.tier2(new, None, fin))
        self.assertIn("Donor entries for a filer the finance file no longer holds", h)
        self.assertIn("Cycle differs from the finance file", h)

    def test_no_finance_file_skips_cross_checks_instead_of_guessing(self):
        self.assertEqual(v.tier2(doc(**{"1": entry()}), None, None), [])

    def test_lost_entries_against_baseline(self):
        old = doc(**{"1": entry(), "2": entry()})
        new = doc(**{"1": entry()})
        secs = dict(v.tier2(new, old, finance(**{"1": 1000.0, "2": 0})))
        self.assertIn("Name 2 (2)", "\n".join(secs["Filers that lost their donor entry since the baseline"]))

    def test_many_names_are_truncated_with_a_count(self):
        ids = {str(i): entry() for i in range(30)}
        new = doc(**ids)
        new["metadata"]["failedFilers"] = list(ids)
        text = "\n".join(dict(v.tier2(new, None, None))["Filers the generator could not fetch"])
        self.assertIn("and 20 more", text)

    def test_render_says_no_change_when_empty(self):
        self.assertIn("No material change", v.render("x.json", []))


if __name__ == "__main__":
    unittest.main()
