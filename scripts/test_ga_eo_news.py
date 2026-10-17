#!/usr/bin/env python3
"""Offline invariant checks for scripts/lib/ga_eo_news.py.

No network, no repo writes. Reads two committed order texts from
assets/data/eo-text/ on purpose: the snippet extractor's whole job is to cope
with how `pdftotext` lays out Georgia's real executive orders (labels first,
body after), so a test built only on synthetic text would not catch the
regression that matters.

Run: python scripts/test_ga_eo_news.py
"""

import io
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from lib.ga_eo_news import (  # noqa: E402
    DEFAULT_CATEGORIES,
    SNIPPET_MAX,
    build_news_items,
    eo_snippet,
    load_orders,
    make_text_reader,
    order_descriptor,
)

FAILURES = []


def check(label, cond, detail=""):
    if cond:
        print(f"  PASS {label}")
    else:
        print(f"  FAIL {label}{(' -- ' + detail) if detail else ''}")
        FAILURES.append(label)


def read_order_text(year, number):
    path = os.path.join(REPO, "assets", "data", "eo-text", str(year), f"{number}.txt")
    if not os.path.exists(path):
        print(f"  FAIL fixture missing: {path}")
        FAILURES.append(f"fixture {number}")
        return None
    with io.open(path, encoding="utf-8") as f:
        return f.read()


def fake_id(url):
    return "id" + str(abs(hash(url)) % 10000)


# --------------------------------------------------------------------------- #
# Snippet extraction
# --------------------------------------------------------------------------- #
def test_label_run_is_skipped_on_a_real_state_of_emergency():
    """The headline case: pdftotext emits the masthead and a run of bare
    WHEREAS: labels before the body, so a naive text[:200] yields
    'WHEREAS: WHEREAS: WHEREAS:'."""
    text = read_order_text(2026, "10.08.26.01")
    if text is None:
        return
    snip = eo_snippet(text)
    check("real SoE order yields a snippet", bool(snip))
    if not snip:
        return
    check("snippet starts at the first substantive sentence",
          snip.startswith("The National Hurricane Center forecasts"), snip[:80])
    check("snippet carries no WHEREAS label", "WHEREAS" not in snip, snip[:80])
    check("snippet drops the masthead",
          "STATE OF GEORGIA" not in snip and "BY THE GOVERNOR" not in snip, snip[:80])
    check("snippet drops the all-caps subject block",
          "HURRICANE ISAIAS" not in snip, snip[:80])
    check(f"snippet is <= {SNIPPET_MAX} chars", len(snip) <= SNIPPET_MAX, str(len(snip)))


def test_leading_ocr_noise_and_caps_block_skipped_on_a_real_order():
    """A Flag at Half-Staff order whose text begins with an OCR artifact line
    ('7 Lo'), then the masthead, then WHEREAS:/ORDERED: labels, then an
    all-caps subject block, and only then the body."""
    text = read_order_text(2026, "09.10.26.01")
    if text is None:
        return
    snip = eo_snippet(text)
    check("real half-staff order yields a snippet", bool(snip))
    if not snip:
        return
    check("snippet starts after the OCR noise and the caps block",
          snip.startswith("On September 11, 2001"), snip[:80])
    check("snippet carries no ORDERED label", "ORDERED" not in snip, snip[:80])


def test_short_appointment_body_is_extracted():
    text = (
        "alt Lb\n\nTHE STATE OF GEORGIA\n\nEXECUTIVE ORDER\n\nBY THE GOVERNOR:\n\n"
        "ORDERED:\n\nThat the Honorable Antonio Long of Fulton\nCounty, Georga, is "
        "reappointed to serve as a\nmember of the Georgia Board of Private Detective\n\n"
        "and Security Agencies, for a term of office expiring\nOctober 6, 2030.\n\n"
        "This 6 day of October 2026\n\npl\n\nGOVERNOR\n"
    )
    snip = eo_snippet(text)
    check("appointment body extracted",
          bool(snip) and snip.startswith("That the Honorable Antonio Long of Fulton County"),
          repr(snip))


def test_line_wrapping_is_collapsed():
    text = ("EXECUTIVE ORDER\n\nBY THE GOVERNOR:\n\nWHEREAS:\n\n"
            "A vacancy now exists in Georgia's Thirteenth Congressional\n"
            "District for the United States House of Representatives due to\n"
            "the death of Congressman David Scott.\n")
    snip = eo_snippet(text)
    check("wrapped lines joined into one sentence",
          snip == ("A vacancy now exists in Georgia's Thirteenth Congressional District "
                   "for the United States House of Representatives due to the death of "
                   "Congressman David Scott."),
          repr(snip))


def test_no_body_yields_none():
    text = ("THE STATE OF GEORGIA\n\nEXECUTIVE ORDER\n\nBY THE GOVERNOR:\n\n"
            "WHEREAS:\n\nWHEREAS:\n\nORDERED:\n\noa\n\nBel\n\nGOVERNOR\n")
    check("label-and-noise-only text yields None", eo_snippet(text) is None,
          repr(eo_snippet(text)))
    check("empty text yields None", eo_snippet("") is None)
    check("missing text yields None", eo_snippet(None) is None)


def test_truncation_is_on_a_word_boundary():
    body = "The Governor hereby finds that " + ("alpha beta gamma delta " * 40)
    text = f"EXECUTIVE ORDER\n\nBY THE GOVERNOR:\n\nWHEREAS:\n\n{body}\n"
    snip = eo_snippet(text)
    check("long body truncated", len(snip) <= SNIPPET_MAX, str(len(snip)))
    check("truncation marked with an ellipsis", snip.endswith("…"), snip[-20:])
    check("truncation does not split a word",
          not snip[:-1].rstrip().endswith(("alph", "bet", "gamm", "delt")), snip[-20:])


# --------------------------------------------------------------------------- #
# Fallback descriptor
# --------------------------------------------------------------------------- #
def test_order_descriptor():
    order = {"category": "Writ of Election", "date": "2026-05-01",
             "number": "05.01.26.01", "title": "Issuing a Writ of Election"}
    check("descriptor names the category and the signing date",
          order_descriptor(order) == "Writ of Election signed May 1, 2026.",
          order_descriptor(order))
    check("descriptor degrades without a date",
          order_descriptor({"category": "Suspension", "date": None})
          == "Suspension order.",
          order_descriptor({"category": "Suspension", "date": None}))
    check("descriptor degrades without a category",
          order_descriptor({"date": "2026-05-01"})
          == "Executive order signed May 1, 2026.",
          order_descriptor({"date": "2026-05-01"}))


# --------------------------------------------------------------------------- #
# Item building
# --------------------------------------------------------------------------- #
ORDERS = [
    {"date": "2026-10-08", "number": "10.08.26.01",
     "title": "Declaring a State of Emergency for Hurricane Isaias",
     "category": "State of Emergency",
     "url": "https://gov.georgia.gov/document/2026-executive-order/10082601/download",
     "sha256": "abc123", "bytes": 497035, "fetchedAt": "2026-10-09T01:31:13Z",
     "archiveUrl": "https://web.archive.org/web/2026/x"},
    {"date": "2026-10-06", "number": "10.06.26.21",
     "title": "Reappointing the Honorable Antonio Long",
     "category": "Appointment",
     "url": "https://gov.georgia.gov/document/2026-executive-order/10062621/download",
     "sha256": "def456"},
    {"date": "2026-05-01", "number": "05.01.26.01",
     "title": "Issuing a Writ of Election to fill the vacancy",
     "category": "Writ of Election",
     "url": "https://gov.georgia.gov/document/2026-executive-order/05012601/download",
     "sha256": "ghi789"},
]

TEXTS = {
    ("2026", "10.08.26.01"): ("THE STATE OF GEORGIA\n\nEXECUTIVE ORDER\n\n"
                              "BY THE GOVERNOR:\n\nWHEREAS:\n\nWHEREAS:\n\n"
                              "STATE OF EMERGENCY FOR\nHURRICANE ISAIAS\n\n"
                              "The National Hurricane Center forecasts Hurricane "
                              "Isaias will make landfall Friday evening.\n"),
}


def lookup(year, number):
    return TEXTS.get((year, number))


def test_allowlist_excludes_appointments():
    items = build_news_items(ORDERS, "Gov. Brian Kemp (executive orders)",
                             lookup, DEFAULT_CATEGORIES, fake_id)
    nums = [it["orderNumber"] for it in items]
    check("appointment excluded by the default allowlist",
          "10.06.26.21" not in nums, str(nums))
    check("newsworthy categories kept",
          nums == ["10.08.26.01", "05.01.26.01"], str(nums))
    check("Appointment is not in the default allowlist",
          "Appointment" not in DEFAULT_CATEGORIES, str(sorted(DEFAULT_CATEGORIES)))


def test_allowlist_is_configurable():
    items = build_news_items(ORDERS, "src", lookup, ["Appointment"], fake_id)
    check("a configured allowlist is honoured",
          [it["orderNumber"] for it in items] == ["10.06.26.21"],
          str([it["orderNumber"] for it in items]))


def test_unknown_category_is_dropped_not_crashed():
    odd = [{"date": "2026-10-08", "number": "x", "title": "t", "category": None,
            "url": "https://example.org/x"}]
    check("an order with no category is dropped",
          build_news_items(odd, "src", lookup, DEFAULT_CATEGORIES, fake_id) == [])


def test_item_shape_and_provenance():
    items = build_news_items(ORDERS, "Gov. Brian Kemp (executive orders)",
                             lookup, DEFAULT_CATEGORIES, fake_id)
    soe = items[0]
    check("publishedAt is an ISO datetime",
          soe["publishedAt"] == "2026-10-08T00:00:00+00:00", soe["publishedAt"])
    check("url is the order PDF", soe["url"] == ORDERS[0]["url"], soe["url"])
    check("source name carried", soe["source"] == "Gov. Brian Kemp (executive orders)")
    check("title carried", soe["title"] == ORDERS[0]["title"])
    check("category carried", soe["category"] == "State of Emergency")
    check("archiveUrl inherited from the EO pipeline",
          soe["archiveUrl"] == ORDERS[0]["archiveUrl"])
    check("sha256 inherited from the EO pipeline", soe["sha256"] == "abc123")
    check("id built with the injected id maker", soe["id"] == fake_id(ORDERS[0]["url"]))
    check("snippet extracted from the order text",
          soe["snippet"].startswith("The National Hurricane Center"), soe["snippet"])


def test_missing_text_falls_back_to_the_descriptor():
    items = build_news_items(ORDERS, "src", lookup, DEFAULT_CATEGORIES, fake_id)
    writ = [it for it in items if it["orderNumber"] == "05.01.26.01"][0]
    check("no order text -> honest category + date descriptor",
          writ["snippet"] == "Writ of Election signed May 1, 2026.", writ["snippet"])


def test_same_titled_orders_stay_distinct():
    """Two different orders routinely carry byte-identical titles -- measured on
    2026, three pairs do ('Amending the State of Emergency for Georgia
    Wildfires' on 05-05 and 05-12, and two Albany State demolitions signed the
    same day). An order's identity is its number, not its boilerplate title, so
    they must come out as two items with two ids. (generate_ga_news.py's
    cross-outlet title dedupe is therefore disabled for this source -- it exists
    to collapse one story syndicated by several outlets, not two signed
    documents.)"""
    pair = [
        dict(ORDERS[0], number="05.05.26.01", date="2026-05-05",
             title="Amending the State of Emergency for Georgia Wildfires",
             url="https://gov.georgia.gov/document/2026-executive-order/05052601/download"),
        dict(ORDERS[0], number="05.12.26.01", date="2026-05-12",
             title="Amending the State of Emergency for Georgia Wildfires",
             url="https://gov.georgia.gov/document/2026-executive-order/05122601/download"),
    ]
    items = build_news_items(pair, "src", lookup, DEFAULT_CATEGORIES, fake_id)
    check("both same-titled orders are built", len(items) == 2, str(len(items)))
    check("same-titled orders get distinct ids",
          len({it["id"] for it in items}) == 2, str([it["id"] for it in items]))


def test_order_without_a_url_is_dropped():
    bad = [dict(ORDERS[0], url=None)]
    check("an order with no URL is dropped",
          build_news_items(bad, "src", lookup, DEFAULT_CATEGORIES, fake_id) == [])


# --------------------------------------------------------------------------- #
# Loading the committed artifacts
# --------------------------------------------------------------------------- #
def test_load_orders_concatenates_years_and_skips_a_missing_one():
    with tempfile.TemporaryDirectory() as tmp:
        with io.open(os.path.join(tmp, "ga-executive-orders-2026.json"), "w",
                     encoding="utf-8") as f:
            json.dump({"metadata": {"year": 2026}, "orders": [ORDERS[0]]}, f)
        with io.open(os.path.join(tmp, "ga-executive-orders-2025.json"), "w",
                     encoding="utf-8") as f:
            json.dump({"metadata": {"year": 2025}, "orders": [ORDERS[2]]}, f)
        got = load_orders(tmp, [2025, 2026, 2027])
        check("both present years loaded, missing year skipped",
              [o["number"] for o in got] == ["05.01.26.01", "10.08.26.01"],
              str([o.get("number") for o in got]))
        check("an absent data dir yields no orders",
              load_orders(os.path.join(tmp, "nope"), [2026]) == [])


def test_load_orders_reads_the_committed_repo_file():
    """Guards the real key name: the file is {_note, metadata, orders}, and a
    rename would make the hub silently publish no executive orders."""
    data_dir = os.path.join(REPO, "assets", "data")
    got = load_orders(data_dir, [2026])
    check("committed 2026 order file parses into a non-empty list",
          len(got) > 100, str(len(got)))
    if got:
        check("committed orders carry the fields the hub reads",
              all(k in got[0] for k in ("date", "number", "title", "category", "url")),
              str(sorted(got[0])))


def test_text_reader_reads_a_committed_order_and_misses_cleanly():
    read = make_text_reader(os.path.join(REPO, "assets", "data", "eo-text"))
    check("reader finds a committed order text",
          "National Hurricane Center" in (read("2026", "10.08.26.01") or ""))
    check("reader returns None for an order with no text file",
          read("2026", "99.99.99.99") is None)
    check("reader returns None for a year with no directory",
          read("1999", "10.08.26.01") is None)


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        print(f"\n{fn.__name__}")
        fn()
    print("\n" + "=" * 60)
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}): {', '.join(FAILURES)}")
        sys.exit(1)
    print("All GA executive-order news checks passed.")


if __name__ == "__main__":
    main()
