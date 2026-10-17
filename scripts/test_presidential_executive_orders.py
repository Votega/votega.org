#!/usr/bin/env python3
"""Offline invariants for the presidential executive-order pipeline: the
generator's parsing and reconciliation, and the validator's tier split.
No network, no repo writes. Run: python scripts/test_presidential_executive_orders.py
"""
import os
import sys
import unittest
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import generate_presidential_executive_orders as g  # noqa: E402
import validate_presidential_executive_orders as v  # noqa: E402

TODAY = date(2026, 10, 17)


def fr(num, title, signed, doc=None):
    num = 14000 + num if num < 1000 else num      # small ints are fixture shorthand
    return {"document_number": doc or f"2026-{num}", "executive_order_number": str(num),
            "title": title, "signing_date": signed, "abstract": None,
            "html_url": f"https://www.federalregister.gov/documents/{num}"}


def wh(title, signed, url="https://www.whitehouse.gov/presidential-actions/x/"):
    return {"title": title, "url": url, "signing_date": signed, "abstract": "Body.",
            "signing_date_source": "signature"}


def feed_item(title, pub, paras, cats=("Presidential Actions", "Executive Orders")):
    body = ('<div class="topper"><nav>Presidential Actions Search Select Category</nav></div>'
            + "".join(f'<p class="wp-block-paragraph">{p}</p>' for p in paras))
    cat_xml = "".join(f"<category>{c}</category>" for c in cats)
    return (f"<item><title>{title}</title><link>https://www.whitehouse.gov/presidential-actions/{title[:8]}/</link>"
            f"<pubDate>{pub}</pubDate>{cat_xml}"
            f'<content:encoded><![CDATA[{body}]]></content:encoded></item>')


def feed(*items):
    return ('<?xml version="1.0"?><rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">'
            f"<channel>{''.join(items)}</channel></rss>").encode()


PREAMBLE = ("By the authority vested in me as President by the Constitution and the laws of the "
            "United States of America, it is hereby ordered:")


class Helpers(unittest.TestCase):
    def test_normalize_title_ignores_case_punctuation_and_fffd(self):
        self.assertEqual(
            g.normalize_title("Eliminating Disease-Carrying Pests And Restoring Enjoyment Of The Great Outdoors"),
            g.normalize_title("Eliminating Disease-Carrying Pests and Restoring Enjoyment of the Great Outdoors"))
        self.assertEqual(g.normalize_title("America�s Hunting"), g.normalize_title("America’s Hunting"))

    def test_clean_title_repairs_fffd_apostrophe(self):
        self.assertEqual(g.clean_title("Reinvigorating America�s Hunting Heritage"),
                         "Reinvigorating America’s Hunting Heritage")

    def test_signature_date_is_parsed_from_the_block(self):
        text = "... DONALD J. TRUMP THE WHITE HOUSE, October 16, 2026."
        self.assertEqual(g.parse_signature_date(text), date(2026, 10, 16))
        self.assertIsNone(g.parse_signature_date("no signature here"))

    def test_pubdate_after_8pm_eastern_is_not_next_day(self):
        # Oct 17 00:34 UTC = Oct 16 20:34 EDT.
        self.assertEqual(g.pubdate_to_eastern_date("Sat, 17 Oct 2026 00:34:24 +0000"), date(2026, 10, 16))
        # Winter: Jan 5 03:00 UTC = Jan 4 22:00 EST.
        self.assertEqual(g.pubdate_to_eastern_date("Mon, 05 Jan 2026 03:00:00 +0000"), date(2026, 1, 4))

    def test_abstract_skips_preamble_and_section_heading(self):
        paras = [PREAMBLE,
                 "Section 1. Purpose. This order restores the thing that was lost and sets a policy for all agencies.",
                 "DONALD J. TRUMP"]
        self.assertTrue(g.build_abstract(paras).startswith("This order restores"))

    def test_abstract_none_when_only_boilerplate(self):
        self.assertIsNone(g.build_abstract([PREAMBLE, "DONALD J. TRUMP"]))

    def test_abstract_keeps_a_real_opening_sentence(self):
        self.assertTrue(g.build_abstract(["It is the policy of the United States to protect water quality nationwide."])
                        .startswith("It is the policy"))

    def test_inline_spans_do_not_split_section_number(self):
        xml = feed(feed_item("Some Order", "Fri, 16 Oct 2026 15:00:00 +0000", [
            PREAMBLE,
            '<span>Section</span> <span>1</span>. Background. Congress passed a law last month to do a thing.',
            "THE WHITE HOUSE,", "October 16, 2026."]))
        item = g.parse_whitehouse_feed(xml)[0]
        self.assertTrue(item["abstract"].startswith("Congress passed"), item["abstract"])


class Feed(unittest.TestCase):
    def test_only_executive_orders_category(self):
        xml = feed(feed_item("An Order", "Fri, 16 Oct 2026 15:00:00 +0000", [PREAMBLE, "THE WHITE HOUSE,", "October 16, 2026."]),
                   feed_item("A Proclamation", "Fri, 16 Oct 2026 15:00:00 +0000", ["x"], cats=("Proclamations",)))
        self.assertEqual([i["title"] for i in g.parse_whitehouse_feed(xml)], ["An Order"])

    def test_signature_beats_pubdate_across_midnight_utc(self):
        xml = feed(feed_item("Late Order", "Sat, 17 Oct 2026 00:34:24 +0000",
                             [PREAMBLE, "THE WHITE HOUSE,", "October 16, 2026."]))
        item = g.parse_whitehouse_feed(xml)[0]
        self.assertEqual((item["signing_date"], item["signing_date_source"]), ("2026-10-16", "signature"))

    def test_falls_back_to_eastern_pubdate_without_signature(self):
        xml = feed(feed_item("No Sig", "Sat, 17 Oct 2026 00:34:24 +0000", [PREAMBLE]))
        item = g.parse_whitehouse_feed(xml)[0]
        self.assertEqual((item["signing_date"], item["signing_date_source"]), ("2026-10-16", "pubDate"))

    def test_signature_far_from_pubdate_is_rejected(self):
        xml = feed(feed_item("Odd", "Sat, 17 Oct 2026 12:00:00 +0000", [PREAMBLE, "THE WHITE HOUSE,", "March 3, 2024."]))
        self.assertEqual(g.parse_whitehouse_feed(xml)[0]["signing_date_source"], "pubDate")

    def test_other_orders_numbers_in_body_are_not_the_items_number(self):
        xml = feed(feed_item("Amends Another", "Fri, 16 Oct 2026 15:00:00 +0000",
                             [PREAMBLE, "Executive Order 14100 is amended.", "THE WHITE HOUSE,", "October 16, 2026."]))
        self.assertNotIn("executive_order_number", g.parse_whitehouse_feed(xml)[0])


class Reconcile(unittest.TestCase):
    def test_unpublished_order_becomes_provisional(self):
        orders, expired = g.reconcile([fr(1, "Old Order", "2026-09-01")], [wh("New Order", "2026-10-16")], TODAY)
        top = orders[0]
        self.assertEqual((top["title"], top["provisional"], top["executive_order_number"]), ("New Order", True, None))
        self.assertIsNone(top["document_number"])
        self.assertEqual(expired, [])

    def test_published_order_gains_number_and_keeps_whitehouse_url(self):
        url = "https://www.whitehouse.gov/presidential-actions/2026/10/new/"
        orders, _ = g.reconcile([fr(14436, "New Order", "2026-10-16")], [wh("NEW ORDER", "2026-10-16", url)], TODAY)
        self.assertEqual(len(orders), 1)
        o = orders[0]
        self.assertFalse(o["provisional"])
        self.assertEqual(o["executive_order_number"], "14436")
        self.assertTrue(o["html_url"].startswith("https://www.federalregister.gov"))
        self.assertEqual(o["whitehouse_url"], url)

    def test_unmatched_past_ttl_is_dropped_and_reported(self):
        orders, expired = g.reconcile([], [wh("Reworded Title", "2026-09-18")], TODAY)
        self.assertEqual(orders, [])
        self.assertEqual([e["title"] for e in expired], ["Reworded Title"])
        self.assertNotIn("ageDays", expired[0])

    def test_exactly_at_ttl_is_still_provisional(self):
        orders, expired = g.reconcile([], [wh("Edge", "2026-10-03")], TODAY)   # 14 days
        self.assertEqual((len(orders), expired), (1, []))

    def test_same_title_far_apart_in_time_is_a_different_order(self):
        orders, _ = g.reconcile([fr(14000, "Amendment To Tariffs", "2026-03-01")],
                                [wh("Amendment To Tariffs", "2026-10-16")], TODAY)
        self.assertEqual([o["provisional"] for o in orders], [True, False])

    def test_one_register_record_matches_one_item(self):
        orders, _ = g.reconcile([fr(5, "Dup", "2026-10-15")],
                                [wh("Dup", "2026-10-15", "https://w/1"), wh("Dup", "2026-10-16", "https://w/2")], TODAY)
        self.assertEqual(sorted(o["provisional"] for o in orders), [False, True])

    def test_sorted_newest_first_with_provisional_on_top(self):
        orders, _ = g.reconcile([fr(2, "B", "2026-10-01"), fr(1, "A", "2026-09-01")], [wh("C", "2026-10-16")], TODAY)
        self.assertEqual([o["title"] for o in orders], ["C", "B", "A"])

    def test_feed_outage_carries_forward_unexpired_provisionals(self):
        carried = [dict(wh("Carried", "2026-10-15"), whitehouse_url="https://w/c", provisional=True)]
        carried[0]["html_url"] = "https://w/c"
        orders, expired = g.reconcile([fr(1, "A", "2026-09-01")], None, TODAY, carried)
        self.assertEqual([o["title"] for o in orders], ["Carried", "A"])
        # ...and a carried entry that has since been published is replaced, not duplicated.
        orders, _ = g.reconcile([fr(2, "Carried", "2026-10-15")], None, TODAY, carried)
        self.assertEqual([(o["title"], o["provisional"]) for o in orders], [("Carried", False)])

    def test_build_output_metadata(self):
        data = g.build_output([fr(1, "A", "2026-09-01")], [wh("B", "2026-10-16")], TODAY, "2025-01-20",
                              now=datetime(2026, 10, 17, tzinfo=timezone.utc))
        m = data["metadata"]
        self.assertEqual((m["count"], m["federalRegisterCount"], m["provisionalCount"], m["whitehouseFeed"]),
                         (2, 1, 1, "ok"))


class Dedupe(unittest.TestCase):
    def test_reprint_is_dropped_whichever_comes_first(self):
        orig, rep = fr(88, "Same", "2026-02-20", doc="2026-03829"), fr(88, "Same", "2026-02-20", doc="R1-2026-03829")
        for order in ([rep, orig], [orig, rep]):
            kept, dropped = g.dedupe_register(order)
            self.assertEqual([k["document_number"] for k in kept], ["2026-03829"])
            self.assertEqual(dropped, ["R1-2026-03829"])

    def test_distinct_orders_untouched(self):
        kept, dropped = g.dedupe_register([fr(1, "A", "2026-01-01"), fr(2, "B", "2026-01-02")])
        self.assertEqual((len(kept), dropped), (2, []))

    def test_build_output_records_dropped_duplicates(self):
        data = g.build_output([fr(88, "S", "2026-02-20", doc="R1-x"), fr(88, "S", "2026-02-20", doc="x")],
                              [], TODAY, "2025-01-20")
        self.assertEqual(data["metadata"]["duplicateRegisterRecords"], ["R1-x"])
        self.assertEqual(data["metadata"]["count"], 1)


class FederalRegisterPaging(unittest.TestCase):
    def test_pages_until_total_pages(self):
        pages = {1: {"total_pages": 2, "results": [fr(2, "B", "2026-02-01")]},
                 2: {"total_pages": 2, "results": [fr(1, "A", "2026-01-01")]}}
        calls = []

        def fetcher(url, **kw):
            n = int(url.split("&page=")[1].split("&")[0])
            calls.append(n)
            return pages[n]
        self.assertEqual(len(g.fetch_federal_register("2025-01-20", fetcher)), 2)
        self.assertEqual(calls, [1, 2])

    def test_a_failed_page_discards_everything(self):
        def fetcher(url, **kw):
            return {"total_pages": 2, "results": [fr(1, "A", "2026-01-01")]} if "&page=1&" in url else None
        self.assertIsNone(g.fetch_federal_register("2025-01-20", fetcher))


# ── validator ──────────────────────────────────────────────────────────────────

def doc(orders, expired=(), count=None):
    prov = sum(1 for o in orders if o.get("provisional"))
    return {"metadata": {"generatedAt": "2026-10-17T00:00:00Z", "termStart": "2025-01-20",
                         "count": len(orders) if count is None else count,
                         "federalRegisterCount": len(orders) - prov, "provisionalCount": prov,
                         "expiredProvisional": list(expired)},
            "orders": orders}


def prov(title, signed):
    return {"document_number": None, "executive_order_number": None, "title": title,
            "signing_date": signed, "abstract": None, "html_url": "https://w/", "whitehouse_url": "https://w/",
            "provisional": True}


class Validator(unittest.TestCase):
    def good(self):
        return doc([fr(2, "B", "2026-10-01"), fr(1, "A", "2026-09-01"), prov("C", "2026-10-16")])

    def test_clean_file_passes(self):
        self.assertEqual(v.tier1(self.good(), None), [])

    def test_malformed_number_fails(self):
        d = self.good(); d["orders"][0]["executive_order_number"] = "14x"
        self.assertTrue(any("malformed" in e for e in v.tier1(d, None)))

    def test_provisional_with_number_fails(self):
        d = self.good(); d["orders"][2]["executive_order_number"] = "99999"
        self.assertTrue(v.tier1(d, None))

    def test_published_without_number_fails(self):
        d = self.good(); d["orders"][0]["executive_order_number"] = None
        self.assertTrue(v.tier1(d, None))

    def test_date_before_term_fails(self):
        d = self.good(); d["orders"][1]["signing_date"] = "2024-12-31"
        self.assertTrue(any("term" in e for e in v.tier1(d, None)))

    def test_duplicate_document_number_fails(self):
        d = self.good(); d["orders"][1]["document_number"] = d["orders"][0]["document_number"]
        self.assertTrue(any("duplicate" in e for e in v.tier1(d, None)))

    def test_duplicate_eo_number_fails(self):
        d = self.good(); d["orders"][1]["executive_order_number"] = "14002"
        self.assertTrue(any("duplicate" in e for e in v.tier1(d, None)))

    def test_count_metadata_mismatch_fails(self):
        self.assertTrue(v.tier1(doc(self.good()["orders"], count=99), None))

    def test_collapse_to_zero_fails_but_zero_without_baseline_also_fails(self):
        self.assertTrue(v.tier1(doc([]), doc([fr(1, "A", "2026-09-01")])))
        self.assertTrue(v.tier1(doc([]), None))

    def test_fewer_published_than_baseline_is_not_tier1(self):
        old = self.good(); new = doc([fr(1, "A", "2026-09-01")])
        self.assertEqual(v.tier1(new, old), [])

    def test_tier2_reports_new_orders_and_expiry_and_abstract_change(self):
        old = doc([fr(1, "A", "2026-09-01")])
        new = doc([fr(1, "A", "2026-09-01"), prov("C", "2026-10-16")],
                  expired=[{"title": "Lost", "signing_date": "2026-09-18", "whitehouse_url": "https://w/l", "ageDays": 29}])
        new["orders"][0]["abstract"] = "Changed"
        text = v.render("x.json", v.tier2(new, old))
        for needle in ("C", "Lost", "Abstract", "matching"):
            self.assertIn(needle, text)

    def test_whitehouse_announcing_more_than_register_is_never_tier1(self):
        d = doc([fr(1, "A", "2026-09-01"), prov("C", "2026-10-16"), prov("D", "2026-10-16")])
        self.assertEqual(v.tier1(d, None), [])

    def test_no_change_report(self):
        d = self.good()
        self.assertIn("No material change", v.render("x.json", v.tier2(d, d)))


if __name__ == "__main__":
    unittest.main()
