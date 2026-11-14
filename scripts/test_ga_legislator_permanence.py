#!/usr/bin/env python3
"""Former GA legislator pages, ledger-owned slugs and redirect stubs, via the real builder.

Runs build_entity_pages.build_ga_legislators over a fixture roster + ledger + frozen tree in
a temp dir (B.SRC_DIR pointed at it), with B.write_page / B.add_card / B.resolve_lastmod
captured, and asserts on every page it would have written.

Usage: python scripts/test_ga_legislator_permanence.py   (exit 0 ok, 1 on failure)
"""
import json
import os
import re
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import yaml  # noqa: F401
except ImportError:
    # run-script-tests.yml installs no pip packages and build_entity_pages imports yaml at
    # module level; the GA-legislator path never calls it, so a stub is enough here.
    sys.modules["yaml"] = types.ModuleType("yaml")

import build_entity_pages as B  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def member(gid, name, chamber, district, status=None, status_date=None, party="Democratic"):
    return {"id": f"ocd-person/{gid:08d}", "legisGaGovId": gid, "name": name, "chamber": chamber,
            "district": district, "party": party, "status": status, "statusDate": status_date,
            "phone": "404-555-0100", "officialWebsiteUrl": "https://example.org/x",
            "committees": [], "imageUrl": None}


HOUSE, SENATE = "House of Representatives", "Senate"
SITTING = member(1, "Ann Sitting", HOUSE, 5)
RESIGNED = member(2, "Bob Resigned", HOUSE, 5, "Resigned", "2026-03-01")
GONE = member(3, "Cy Gone", SENATE, 9)  # only in the frozen tree


def run(live, frozen, ledger_people, live_tag="2025_26", records_for=None, pages=None):
    """Return (pages, urls, cards, dirs); pages is {slug: (front matter, body)}."""
    tmp = tempfile.mkdtemp()
    write = lambda rel, doc: (os.makedirs(os.path.dirname(os.path.join(tmp, rel)), exist_ok=True),
                              json.dump(doc, open(os.path.join(tmp, rel), "w", encoding="utf-8")))
    write("ga-members.json", {"metadata": {"session": live_tag, "generatedAt": "2026-11-01T00:00:00+00:00"},
                              "members": live})
    write("ga-party-unity.json", {"members": []})
    write("ga-sponsorship-index.json", {"members": {}})
    for tag, ms in frozen.items():
        write(f"ga-bienniums/{tag}/ga-members.json", {"metadata": {"session": tag}, "members": ms})
    write("ga-legislator-ledger.json", {"metadata": {"generatedAt": None, "count": len(ledger_people)},
                                        "people": ledger_people})
    everyone = list(live) + [m for ms in frozen.values() for m in ms if m["id"] not in {x["id"] for x in live}]
    records = [{"category": "GA Legislator", "title": m["name"], "desc": "Rep",
                "url": f"ga-member.html?id={m['id']}"} for m in (records_for or everyone)]

    pages = {} if pages is None else pages
    cards = []
    saved = (B.SRC_DIR, B.write_page, B.add_card, B.resolve_lastmod, B._DIRECTORY[:])
    B.SRC_DIR = tmp
    B.write_page = lambda sub, slug, fm, body: pages.__setitem__(slug, (fm, body))
    B.add_card = lambda *a, **k: cards.append((a, k))
    B.resolve_lastmod = lambda *a, **k: "2000-01-01"
    B._DIRECTORY[:] = []
    urls = {}
    try:
        B.build_ga_legislators(records, urls, {}, {})
        dirs = list(B._DIRECTORY)
    finally:
        B.SRC_DIR, B.write_page, B.add_card, B.resolve_lastmod = saved[:4]
        B._DIRECTORY[:] = saved[4]
    return pages, urls, cards, dirs


def led(gid, *paths, bienniums=()):
    """paths: (path, biennium) newest first."""
    return {str(gid): {"rosterId": f"ocd-person/{gid:08d}",
                       "urls": [{"path": p, "biennium": b} for p, b in paths],
                       "bienniums": list(bienniums)}}


def ledger3():
    out = {}
    out.update(led(1, ("/ga-legislators/ann-sitting-house-5/", "2025_26")))
    out.update(led(2, ("/ga-legislators/bob-resigned-house-5/", "2025_26")))
    out.update(led(3, ("/ga-legislators/cy-gone-senate-9/", "2025_26")))
    return out


def ve_of(body):
    return json.loads(re.search(r"window\.VOTEGA_ENTITY = (\{.*?\});</script>", body).group(1))


FROZEN = {"2025_26": [RESIGNED, GONE]}


def test_former_live_resigned_page_built_indexed():
    pages, urls, _, _ = run([SITTING, RESIGNED], FROZEN, ledger3())
    fm, body = pages["bob-resigned-house-5"]
    check("former page exists", "bob-resigned-house-5" in pages, True)
    check("no noindex/sitemap/search keys", [k for k in ("noindex", "sitemap", "search") if k in fm], [])
    check("retired bucket has id", urls["retired"]["ga-legislator"].get(RESIGNED["id"]), True)
    check("sitting member not retired", SITTING["id"] in urls["retired"]["ga-legislator"], False)
    check("jobTitle is Former", '"jobTitle":"Former State Representative"' in body, True)
    check("share-title prefixed", "Former GA House District 5" in fm["share-title"], True)
    check("entity.former carries status", fm["entity"]["former"],
          {"biennium": "current", "status": "Resigned", "statusDate": "2026-03-01"})


def test_frozen_only_member_page_built():
    pages, urls, cards, dirs = run([SITTING], FROZEN, ledger3())
    fm, body = pages["cy-gone-senate-9"]
    check("frozen-only page built", fm["entity"]["name"], "Cy Gone")
    check("frozen-only is retired", urls["retired"]["ga-legislator"].get(GONE["id"]), True)
    check("frozen biennium recorded", ve_of(body)["former"]["biennium"], "2025_26")
    groups = {d["group"] for d in dirs}
    check("directory group names the biennium", "Former Georgia Legislators (2025-2026)" in groups, True)


def test_banner_text_and_successor_link():
    pages, _, _, _ = run([SITTING, RESIGNED], FROZEN, ledger3())
    body = pages["bob-resigned-house-5"][1]
    banner = re.search(r'<p class="former-member-banner">.*?</p>', body, re.S).group(0)
    check("banner icon", '<i class="fa-solid fa-clock-rotate-left" aria-hidden="true"></i>' in banner, True)
    check("banner departure sentence",
          "Served in the Georgia House, District 5, in the 2025–2026 General Assembly. "
          "Resigned March 1, 2026." in banner, True)
    check("banner successor link",
          'The seat is now held by <a href="/ga-legislators/ann-sitting-house-5/">Ann Sitting</a>.' in banner,
          True)
    check("banner sits before the include", body.index("former-member-banner") < body.index("{% include"), True)
    check("sitting page has no banner", "former-member-banner" in pages["ann-sitting-house-5"][1], False)
    # the senate seat has no sitting holder: no successor sentence
    pages2, _, _, _ = run([SITTING], FROZEN, ledger3())
    check("no successor, no sentence", "now held by" in pages2["cy-gone-senate-9"][1], False)


def test_former_has_no_contact_or_next_election():
    pages, _, cards, _ = run([SITTING, RESIGNED], FROZEN, ledger3())
    ent = pages["bob-resigned-house-5"][0]["entity"]
    check("phone None", ent["phone"], None)
    check("website None", ent["website"], None)
    check("nextElection None", ent["nextElection"], None)
    check("no telephone in JSON-LD", "telephone" in pages["bob-resigned-house-5"][1], False)
    badges = {a[2]: k["badges"] for a, k in cards}
    check("card badge", badges["Bob Resigned"], ["Former Officeholder"])
    check("sitting badge unchanged", badges["Ann Sitting"], ["Current Officeholder"])


def test_slug_comes_from_ledger_not_name():
    led_ = ledger3()
    led_.update(led(1, ("/ga-legislators/ann-the-renamed-house-5/", "2025_26")))
    pages, urls, _, _ = run([SITTING, RESIGNED], FROZEN, led_)
    check("ledger slug used", "ann-the-renamed-house-5" in pages and "ann-sitting-house-5" not in pages, True)
    check("url mapping uses ledger path", urls["ga-legislator"][SITTING["id"]],
          "/ga-legislators/ann-the-renamed-house-5/")


def test_redirect_carries_biennium_when_different():
    led_ = ledger3()
    led_.update(led(1, ("/ga-legislators/ann-new-house-5/", "2027_28"),
                    ("/ga-legislators/ann-sitting-house-5/", "2025_26")))
    pages, _, _, _ = run([SITTING, RESIGNED], FROZEN, led_, live_tag="2027_28")
    fm, body = pages["ann-sitting-house-5"]
    check("stub front matter", fm,
          {"permalink": "/ga-legislators/ann-sitting-house-5/", "sitemap": "false",
           "redirect_to": B.SITE_URL + "/ga-legislators/ann-new-house-5/?biennium=2025-2026"})
    check("stub body empty", body, "")


def test_redirect_same_biennium_has_no_param():
    led_ = ledger3()
    led_.update(led(1, ("/ga-legislators/ann-new-house-5/", "2025_26"),
                    ("/ga-legislators/ann-sitting-house-5/", "2025_26")))
    pages, _, _, _ = run([SITTING, RESIGNED], FROZEN, led_)
    check("no biennium param", pages["ann-sitting-house-5"][0]["redirect_to"],
          B.SITE_URL + "/ga-legislators/ann-new-house-5/")


def test_bienniums_dedupe_live_session():
    pages, _, _, _ = run([SITTING, RESIGNED], FROZEN, ledger3())
    check("live departed member", ve_of(pages["bob-resigned-house-5"][1])["bienniums"], ["current"])
    check("entity.bienniums omitted when default", "bienniums" in pages["bob-resigned-house-5"][0]["entity"], False)
    check("sitting VOTEGA_ENTITY", ve_of(pages["ann-sitting-house-5"][1]),
          {"id": SITTING["id"], "bienniums": ["current"], "former": None})
    # a later live biennium keeps the frozen one as an extra
    pages2, _, _, _ = run([SITTING, RESIGNED], FROZEN, ledger3(), live_tag="2027_28")
    check("live + frozen", ve_of(pages2["bob-resigned-house-5"][1])["bienniums"], ["current", "2025_26"])
    check("entity.bienniums when >1", pages2["bob-resigned-house-5"][0]["entity"]["bienniums"],
          ["current", "2025_26"])


def test_ledger_person_without_page_raises_after_writing_the_rest():
    led_ = ledger3()
    led_.update(led(99, ("/ga-legislators/nobody-house-1/", "2025_26")))
    led_.update(led(1, ("/ga-legislators/ann-new-house-5/", "2025_26"),
                    ("/ga-legislators/ann-sitting-house-5/", "2025_26")))
    pages = {}
    try:
        run([SITTING, RESIGNED], FROZEN, led_, pages=pages)
    except SystemExit:
        check("raises an Exception, not SystemExit", "SystemExit", "RuntimeError")
    except RuntimeError as e:
        check("RuntimeError names the gid", "99" in str(e), True)
    else:
        check("raises", "no exception", "RuntimeError")
    check("other pages still written",
          {"ann-new-house-5", "bob-resigned-house-5", "cy-gone-senate-9"} <= set(pages), True)
    check("redirect stub still written", "ann-sitting-house-5" in pages, True)


def test_ledger_person_absent_from_corpus_still_gets_page():
    only_ann = [m for m in (SITTING, RESIGNED, GONE) if m is SITTING]
    pages, urls, _, _ = run([SITTING, RESIGNED], FROZEN, ledger3(), records_for=only_ann)
    check("live person missing from corpus built", "bob-resigned-house-5" in pages, True)
    check("frozen-only person missing from corpus built", "cy-gone-senate-9" in pages, True)
    check("corpus person unchanged", "ann-sitting-house-5" in pages, True)


def test_former_description_has_no_contact_claim():
    pages, _, _, _ = run([SITTING, RESIGNED], FROZEN, ledger3())
    d = pages["bob-resigned-house-5"][0]["share-description"].strip("\"")
    check("former lead", d.startswith("Former Georgia State Representative, District 5."), True)
    check("no contact information", "contact" in d.lower(), False)
    check("names the biennium", "2025–2026 General Assembly" in d, True)
    check("sitting description unchanged", "contact information" in pages["ann-sitting-house-5"][0]["share-description"], True)


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            print(name)
            fn()
    print("\nFAILED: " + ", ".join(failures) if failures else "\nAll checks passed.")
    return 1 if failures else 0


def test_former_legislators_data_for_state_reps_page():
    B._FORMER[:] = []
    run([SITTING, RESIGNED], FROZEN, ledger3())
    got = B.former_legislators(B._FORMER)
    check("one biennium group, newest first", [g["biennium"] for g in got["groups"]], ["2025–2026"])
    rows = got["groups"][0]["members"]
    check("senate before house, then district", [r["name"] for r in rows], ["Cy Gone", "Bob Resigned"])
    check("row shape", rows[1], {"name": "Bob Resigned", "chamber": "House", "district": 5,
                                 "party": "Democratic", "left": "Resigned March 1, 2026",
                                 "url": "/ga-legislators/bob-resigned-house-5/"})
    check("no departure status -> left is None", rows[0]["left"], None)
    check("sitting members excluded", "Ann Sitting" in [r["name"] for r in rows], False)
    check("empty input -> no groups", B.former_legislators([]), {"groups": []})


if __name__ == "__main__":
    sys.exit(main())
