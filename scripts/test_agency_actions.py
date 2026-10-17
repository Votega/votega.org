#!/usr/bin/env python3
"""Offline invariants for the Cabinet-department rules pipeline (generator +
validator). No network, no repo writes.
Run: python scripts/test_agency_actions.py
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import generate_agency_actions as g  # noqa: E402
import validate_agency_actions as v  # noqa: E402
from lib import federal_register as fr  # noqa: E402

TODAY = date(2026, 10, 17)


def doc(n, signed="2026-10-01", typ="Rule", abstract="Abstract."):
    return {"document_number": n, "title": f"Rule {n}", "type": typ,
            "publication_date": signed, "html_url": f"https://fr/{n}", "abstract": abstract}


def slice_(name, slug, aid, docs):
    return g.build_slice(name, aid, slug, docs, "2025-01-20", "2026-10-17T00:00:00Z")


def world(docs_by_dept):
    slices = {n: slice_(n, f"{n.lower()}-dept", i, d) for i, (n, d) in enumerate(docs_by_dept.items(), 1)}
    return g.build_index(slices, "2025-01-20", "2026-10-17T00:00:00Z"), slices


class Fetching(unittest.TestCase):
    def test_pages_until_total_pages_and_keeps_only_requested_fields(self):
        pages = {1: {"total_pages": 2, "results": [dict(doc("a"), extra="x")]},
                 2: {"total_pages": 2, "results": [doc("b")]}}
        calls = []

        def fetcher(url, **kw):
            n = int(url.split("&page=")[1].split("&")[0])
            calls.append(n)
            return pages[n]
        out = fr.fetch_all("conditions%5Btype%5D%5B%5D=RULE", g.FIELDS, fetcher=fetcher)
        self.assertEqual([d["document_number"] for d in out], ["a", "b"])
        self.assertEqual(calls, [1, 2])
        self.assertNotIn("extra", out[0])

    def test_one_failed_page_discards_everything(self):
        def fetcher(url, **kw):
            return {"total_pages": 2, "results": [doc("a")]} if "&page=1&" in url else None
        self.assertIsNone(fr.fetch_all("x=1", g.FIELDS, fetcher=fetcher))

    def test_department_query_is_term_scoped_to_rules_and_proposed_rules(self):
        seen = []
        g.fetch_department(12, "2025-01-20", fetcher=lambda url, **kw: seen.append(url) or {"results": []})
        for needle in ("agency_ids%5D%5B%5D=12", "type%5D%5B%5D=RULE", "type%5D%5B%5D=PRORULE",
                       "publication_date%5D%5Bgte%5D=2025-01-20"):
            self.assertIn(needle, seen[0])


class Registry(unittest.TestCase):
    def test_every_registered_slug_is_unique_and_ids_distinct(self):
        slugs = [s for _, s in g.AGENCIES.values()]
        ids = [i for i, _ in g.AGENCIES.values()]
        self.assertEqual((len(set(slugs)), len(set(ids))), (len(slugs), len(ids)))

    def test_verify_agency_ids_flags_a_slug_that_moved(self):
        good = [{"id": i, "slug": s} for i, s in g.AGENCIES.values()]
        self.assertEqual(g.verify_agency_ids(good), [])
        bad = [dict(a) for a in good]
        bad[0]["slug"] = "something-else"
        self.assertEqual(g.verify_agency_ids(bad), [next(iter(g.AGENCIES))])
        self.assertEqual(len(g.verify_agency_ids([])), len(g.AGENCIES))

    def test_page_registry_matches_nothing_hardcoded(self):
        # The page must resolve departments through the index, not its own copy.
        page = open(os.path.join(os.path.dirname(__file__), "..", "_includes", "entity",
                                 "federal-executive.html"), encoding="utf-8").read()
        self.assertNotIn("AGENCY_IDS", page)


class Output(unittest.TestCase):
    def test_index_points_at_each_slice_with_counts(self):
        index, slices = world({"A": [doc("1"), doc("2")], "B": []})
        self.assertEqual(index["departments"]["A"]["count"], 2)
        self.assertEqual(index["departments"]["A"]["file"], "agency-actions/a-dept.json")

    def test_unchanged_content_keeps_generatedAt_so_quiet_days_are_empty_commits(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "s.json")
            old = slice_("A", "a", 1, [doc("1")])
            with open(path, "w", encoding="utf-8") as f:
                json.dump(old, f)
            new = g.build_slice("A", 1, "a", [doc("1")], "2025-01-20", "2099-01-01T00:00:00Z")
            self.assertEqual(g.keep_timestamp_if_unchanged(new, path, "documents")["metadata"]["generatedAt"],
                             "2026-10-17T00:00:00Z")
            changed = g.build_slice("A", 1, "a", [doc("1"), doc("2")], "2025-01-20", "2099-01-01T00:00:00Z")
            self.assertEqual(g.keep_timestamp_if_unchanged(changed, path, "documents")["metadata"]["generatedAt"],
                             "2099-01-01T00:00:00Z")


class Validator(unittest.TestCase):
    def good(self):
        return world({"A": [doc("1"), doc("2", typ="Proposed Rule")], "B": [doc("3")]})

    def test_clean_files_pass(self):
        index, slices = self.good()
        self.assertEqual(v.tier1(index, slices, today=TODAY), [])

    def test_count_mismatch_fails(self):
        index, slices = self.good()
        slices["A"]["metadata"]["count"] = 99
        self.assertTrue(any("count" in e for e in v.tier1(index, slices, today=TODAY)))

    def test_index_count_mismatch_fails(self):
        index, slices = self.good()
        index["departments"]["B"]["count"] = 7
        self.assertTrue(v.tier1(index, slices, today=TODAY))

    def test_duplicate_document_number_fails(self):
        index, slices = world({"A": [doc("1"), doc("1")]})
        self.assertTrue(any("duplicate" in e for e in v.tier1(index, slices, today=TODAY)))

    def test_unknown_type_fails(self):
        index, slices = world({"A": [doc("1", typ="Notice")]})
        self.assertTrue(any("type" in e for e in v.tier1(index, slices, today=TODAY)))

    def test_date_before_term_fails(self):
        index, slices = world({"A": [doc("1", signed="2024-12-31")]})
        self.assertTrue(any("term" in e for e in v.tier1(index, slices, today=TODAY)))

    def test_scheduled_publication_date_is_not_a_contradiction(self):
        index, slices = world({"A": [doc("1", signed="2026-10-19")]})   # Monday, run on Saturday
        self.assertEqual(v.tier1(index, slices, today=TODAY), [])

    def test_absurdly_distant_date_fails(self):
        index, slices = world({"A": [doc("1", signed="2027-06-01")]})
        self.assertTrue(v.tier1(index, slices, today=TODAY))

    def test_missing_slice_file_fails(self):
        index, slices = self.good()
        del slices["B"]
        self.assertTrue(any("missing" in e for e in v.tier1(index, slices, today=TODAY)))

    def test_department_collapsing_to_zero_fails(self):
        index, slices = world({"A": []})
        self.assertTrue(any("collapse" in e for e in v.tier1(
            index, slices, {"A": slice_("A", "a-dept", 1, [doc("1")])}, today=TODAY)))

    def test_fewer_rules_than_before_is_not_tier1(self):
        index, slices = world({"A": [doc("1")]})
        old = {"A": slice_("A", "a-dept", 1, [doc("1"), doc("2")])}
        self.assertEqual(v.tier1(index, slices, old, today=TODAY), [])

    def test_tier2_reports_new_and_vanished_rules(self):
        index, slices = world({"A": [doc("1"), doc("9")]})
        old = {"A": slice_("A", "a-dept", 1, [doc("1"), doc("2")])}
        text = v.render(v.tier2(index, slices, old))
        self.assertIn("1 new", text)
        self.assertIn("no longer returned", text)

    def test_no_change_report(self):
        index, slices = world({"A": [doc("1")]})
        self.assertIn("No material change", v.render(v.tier2(index, slices, {"A": slices["A"]})))


if __name__ == "__main__":
    unittest.main()
