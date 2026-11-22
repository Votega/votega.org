#!/usr/bin/env python3
"""Tests for check_site_page_count.py (stdlib only; run: python scripts/test_check_site_page_count.py)."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_site_page_count as g


def make_site(root, n):
    os.makedirs(os.path.join(root, "sub"))
    for i in range(n):
        d = root if i % 2 else os.path.join(root, "sub")
        open(os.path.join(d, f"p{i}.html"), "w").close()
    open(os.path.join(root, "data.json"), "w").close()  # not a page


class GateTests(unittest.TestCase):
    def test_evaluate(self):
        self.assertEqual(g.evaluate(1484, 1484), [])
        self.assertEqual(g.evaluate(1484, None), [])
        self.assertEqual(g.evaluate(1350, 1484), [])          # -9%: tolerated
        self.assertTrue(g.evaluate(1300, 1484))               # -12.4%: relative trip
        self.assertTrue(g.evaluate(90, None))                 # floor trip, no baseline
        self.assertEqual(len(g.evaluate(90, 1484)), 2)        # both

    def test_count_ignores_non_html(self):
        with tempfile.TemporaryDirectory() as d:
            make_site(d, 7)
            self.assertEqual(g.count_pages(d), 7)

    def test_main_writes_state_only_on_pass(self):
        with tempfile.TemporaryDirectory() as d:
            site, state = os.path.join(d, "_site"), os.path.join(d, "s.json")
            os.makedirs(site)
            make_site(os.path.join(site, "x"), 10)
            self.assertEqual(g.main(["--site", site, "--state", state]), 1)
            self.assertFalse(os.path.exists(state))           # failure: no baseline written
            with open(state, "w") as f:
                json.dump({"pages": 1500}, f)
            self.assertEqual(g.main(["--site", site, "--state", state]), 1)
            self.assertEqual(json.load(open(state))["pages"], 1500)  # baseline untouched

    def test_missing_site_fails(self):
        self.assertEqual(g.main(["--site", "/nonexistent-site-dir"]), 1)

    def test_bad_state_file_is_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.json")
            open(p, "w").write("not json")
            self.assertIsNone(g.load_prior(p))


if __name__ == "__main__":
    unittest.main()
