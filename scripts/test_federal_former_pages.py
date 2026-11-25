#!/usr/bin/env python3
"""Former members of Georgia's congressional delegation, via the real page builder (D12).

Runs build_entity_pages.build_federal_legislators over a fixture roster + frozen tree in a
temp dir (B.SRC_DIR pointed at it) with write_page / add_card / resolve_lastmod captured.

What must hold:
  * a frozen member who is no longer sitting gets a page at the URL the freeze promised, with a
    "Former member" banner, indexed (no noindex / sitemap:false), and in a "Former" directory group;
  * their id is under urls['us-congress-former'], NOT urls['us-congress']: the race and candidate
    pages read that map to find a SITTING member;
  * nothing is built as "former" before the turnover (every frozen member still sitting);
  * an approved label is shown with links to the certified results; with none, the banner states
    only that they served; and the label wording rules (D6) hold for the committed labels file;
  * a promised URL a sitting member no longer occupies becomes a redirect; a promised member with
    no page raises (after the other pages are written);
  * the page include fetches every frozen file through dataUrl(), never a bare live path.

Usage: python scripts/test_federal_former_pages.py   (exit 0 ok, 1 on failure)
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
except ImportError:  # run-script-tests.yml installs no pip packages; this path never calls yaml
    sys.modules["yaml"] = types.ModuleType("yaml")

import build_entity_pages as B  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def member(bid, first, last, district=None, chamber="House of Representatives", **kw):
    m = {"bioguideId": bid, "firstName": first, "lastName": last, "name": f"{last}, {first}",
         "state": "Georgia", "district": district, "partyName": "Republican",
         "terms": {"item": [{"chamber": chamber, "startYear": 2015}]},
         "contactInfo": {"phoneNumber": "202-555-0100"}, "officialWebsiteUrl": "https://example.house.gov"}
    m.update(kw)
    return m


STAYS = member("S000001", "Sam", "Stays", 5)
LEAVES = member("L000002", "Lee", "Leaves", 1)
SENATOR = member("N000003", "Nia", "Nate", chamber="Senate")
NEW_ONE = member("K000004", "Kim", "Newcomer", 1)  # the 120th's holder of Lee's seat


def run(live, frozen_members, urls_promised=None, labels=None, records_for=None, congress="119th"):
    """Return (pages, urls, cards, dirs, error)."""
    tmp = tempfile.mkdtemp()

    def write(rel, doc):
        path = os.path.join(tmp, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f)

    write("current-members.json", {"metadata": {"generatedAt": "2027-01-04T00:00:00+00:00"}, "members": live})
    if frozen_members is not None:
        promised = urls_promised if urls_promised is not None else {
            m["bioguideId"]: f"/us-congress/{B.slugify(f'{m['firstName']} {m['lastName']}', 'senate' if m['district'] is None else 'ga-' + str(m['district']))}/"
            for m in frozen_members}
        write(f"federal-congresses/{congress}/freeze.json",
              {"congress": 119, "slug": congress, "kind": "final", "frozenAt": "2026-12-30T12:00:00+00:00",
               "urls": promised, "members": sorted(promised)})
        write(f"federal-congresses/{congress}/current-members.json",
              {"metadata": {"congress": 119}, "members": frozen_members})
    if labels is not None:
        write("federal-departure-labels.json", {"labels": labels})
    records = [{"category": "U.S. Congress", "title": f"{m['lastName']}, {m['firstName']}",
                "desc": f"{m['terms']['item'][-1]['chamber']}, Georgia", "url": f"member.html?bioguideId={m['bioguideId']}"}
               for m in (records_for if records_for is not None else live)]
    pages, cards = {}, []
    saved = (B.SRC_DIR, B.write_page, B.add_card, B.resolve_lastmod, B._DIRECTORY[:])
    B.SRC_DIR = tmp
    B.write_page = lambda sub, slug, fm, body: pages.__setitem__(slug, (fm, body))
    B.add_card = lambda *a, **k: cards.append((a, k))
    B.resolve_lastmod = lambda *a, **k: "2000-01-01"
    B._DIRECTORY[:] = []
    urls, error = {}, None
    try:
        try:
            B.build_federal_legislators(records, urls, {}, {})
        except RuntimeError as e:
            error = str(e)
        dirs = list(B._DIRECTORY)
    finally:
        B.SRC_DIR, B.write_page, B.add_card, B.resolve_lastmod = saved[:4]
        B._DIRECTORY[:] = saved[4]
    return pages, urls, cards, dirs, error


def banner_of(body):
    m = re.search(r'<p class="former-member-banner">.*?</p>', body, re.S)
    return m.group(0) if m else None


def ve_of(body):
    return json.loads(re.search(r"window\.VOTEGA_ENTITY = (\{.*?\});</script>", body).group(1))


AFTER_TURNOVER = [STAYS, SENATOR, NEW_ONE]  # the 120th's Georgia delegation (Lee Leaves is gone)
FROZEN = [LEAVES, STAYS, SENATOR]


def test_former_page_built_indexed_and_separate_url_map():
    pages, urls, cards, dirs, err = run(AFTER_TURNOVER, FROZEN)
    check("no error", err, None)
    fm, body = pages["lee-leaves-ga-1"]
    check("page at the promised URL", fm["permalink"], "/us-congress/lee-leaves-ga-1/")
    check("indexed: no noindex / sitemap / search keys", [k for k in ("noindex", "sitemap", "search") if k in fm], [])
    check("former id is in the former map", urls["us-congress-former"], {"L000002": "/us-congress/lee-leaves-ga-1/"})
    check("former id is NOT in the sitting map", "L000002" in urls["us-congress"], False)
    check("sitting members stay in the sitting map", sorted(urls["us-congress"]), ["K000004", "N000003", "S000001"])
    check("jobTitle is Former", '"jobTitle":"Former U.S. Representative"' in body.replace(": ", ":"), True)
    check("title says Former", "Former U.S. Representative" in fm["share-title"], True)
    check("entity.former set", fm["entity"]["former"]["congress"], "119th")
    check("banner sits before the include", body.index("former-member-banner") < body.index("{% include"), True)
    check("front-end gets the frozen Congress", ve_of(body)["frozen"], "119th")
    check("front-end gets the term end", ve_of(body)["former"]["leftOffice"], "January 3, 2027")
    check("directory group is Former", {d["group"] for d in dirs if "Former" in d["group"]},
          {"Former Members from Georgia (119th Congress)"})
    check("card is badged Former", [k["badges"] for a, k in cards if a[1] == "lee-leaves-ga-1"], [["Former Officeholder"]])
    check("a sitting page has no banner", banner_of(pages["sam-stays-ga-5"][1]), None)
    check("a sitting page has no frozen key", "frozen" in ve_of(pages["sam-stays-ga-5"][1]), False)


def test_banner_states_service_and_names_the_new_holder_without_labels():
    pages, *_ = run(AFTER_TURNOVER, FROZEN)
    banner = banner_of(pages["lee-leaves-ga-1"][1])
    check("service sentence", "Served in the U.S. House, Georgia District 1 in the 119th Congress (2025–2027)." in banner, True)
    check("seat holder linked", '<a href="/us-congress/kim-newcomer-ga-1/">Kim Newcomer</a>' in banner, True)
    for word in ("retire", "ousted", "unseated", "defeated"):
        check(f"banner never says {word}", word in banner.lower(), False)


def test_senator_banner_has_no_seat_holder():
    pages, *_ = run([STAYS, NEW_ONE], FROZEN)
    banner = banner_of(pages["nia-nate-senate"][1])
    check("senator served in the Senate", "Served in the U.S. Senate in the 119th Congress" in banner, True)
    check("no single holder of a two-seat office", "now held by" in banner, False)


def test_approved_label_is_shown_with_results_links():
    labels = {"L000002": {"label": "Did not run for re-election in 2026",
                          "results": [{"title": "Georgia 2026 primary results", "url": "/ga-primary-results/"}]}}
    pages, *_ = run(AFTER_TURNOVER, FROZEN, labels=labels)
    fm, body = pages["lee-leaves-ga-1"]
    banner = banner_of(body)
    check("label text", "Did not run for re-election in 2026." in banner, True)
    check("links the certified results page", '<a href="/ga-primary-results/">Georgia 2026 primary results</a>' in banner, True)
    check("entity carries the label", fm["entity"]["former"]["label"], "Did not run for re-election in 2026")


def test_nothing_is_former_before_the_turnover():
    pages, urls, _, dirs, err = run([LEAVES, STAYS, SENATOR], FROZEN)
    check("no error", err, None)
    check("no former map", "us-congress-former" in urls, False)
    check("all three built as sitting", sorted(pages), ["lee-leaves-ga-1", "nia-nate-senate", "sam-stays-ga-5"])
    check("no former directory group", [d for d in dirs if "Former" in d["group"]], [])
    check("no banner anywhere", [s for s, (_, b) in pages.items() if banner_of(b)], [])


def test_no_frozen_tree_changes_nothing():
    pages, urls, _, _, err = run(AFTER_TURNOVER, None)
    check("no error", err, None)
    check("only the sitting members", sorted(pages), ["kim-newcomer-ga-1", "nia-nate-senate", "sam-stays-ga-5"])


def test_roster_flag_alone_makes_a_member_former():
    flagged = dict(LEAVES, currentMember=False)
    pages, urls, *_ = run([flagged, STAYS, SENATOR], FROZEN)
    check("flagged member gets the former page", banner_of(pages["lee-leaves-ga-1"][1]) is not None, True)
    check("and not also a sitting page", urls["us-congress"].get("L000002"), None)


def test_promised_url_that_moved_redirects_and_a_missing_member_raises():
    moved = dict(STAYS, lastName="Staysmore")
    promised = {"S000001": "/us-congress/sam-stays-ga-5/", "L000002": "/us-congress/lee-leaves-ga-1/"}
    pages, _, _, _, err = run([moved, SENATOR], FROZEN, urls_promised=promised)
    check("no error", err, None)
    fm, body = pages["sam-stays-ga-5"]
    check("old URL redirects to the new page", fm["redirect_to"], "https://www.votega.org/us-congress/sam-staysmore-ga-5/")
    check("redirect is out of the sitemap", fm["sitemap"], "false")
    check("new page exists", "sam-staysmore-ga-5" in pages, True)
    # A promised member who is neither sitting nor frozen has no page: raise, after the rest are written.
    pages2, _, _, _, err2 = run([SENATOR], [LEAVES], urls_promised={"L000002": "/us-congress/lee-leaves-ga-1/",
                                                                      "Z000009": "/us-congress/zed-gone-ga-9/"})
    check("raises naming the member", bool(err2) and "Z000009" in err2, True)
    check("other pages still written", "lee-leaves-ga-1" in pages2 and "nia-nate-senate" in pages2, True)


def test_slug_collision_with_a_sitting_member_fails_loudly():
    twin = member("T000009", "Lee", "Leaves", 1)
    _, _, _, _, err = run([twin, STAYS], [LEAVES])
    check("collision raises", bool(err) and "L000002" in err, True)


def test_former_list_data_for_federal_reps_page():
    rows = [{"congress": "119th", "name": "B", "chamber": "House", "district": 11, "party": None, "left": None, "url": "/b/"},
            {"congress": "119th", "name": "A", "chamber": "House", "district": 1, "party": "Republican", "left": "x", "url": "/a/"},
            {"congress": "119th", "name": "S", "chamber": "Senate", "district": None, "party": None, "left": None, "url": "/s/"},
            {"congress": "117th", "name": "Z", "chamber": "House", "district": 2, "party": None, "left": None, "url": "/z/"}]
    got = B.former_federal(rows)
    check("newest Congress first", [g["congress"] for g in got["groups"]], ["119th", "117th"])
    check("Senate, then district", [m["name"] for m in got["groups"][0]["members"]], ["S", "A", "B"])
    check("empty input -> no groups", B.former_federal([]), {"groups": []})
    B._FORMER_FEDERAL[:] = []
    run(AFTER_TURNOVER, FROZEN)
    check("builder collects the former member", [(r["name"], r["url"]) for r in B._FORMER_FEDERAL],
          [("Lee Leaves", "/us-congress/lee-leaves-ga-1/")])
    B._FORMER_FEDERAL[:] = []


def test_include_reads_every_frozen_file_through_dataurl():
    html = open(os.path.join(ROOT, "_includes", "entity", "federal-legislator.html"), encoding="utf-8").read()
    bare = re.findall(r"assets/data/(federal-[a-z\-]+|current-members|curated-federal-bills)", html)
    # The one mention is dataUrl()'s own prefix comment/implementation, which names the directory, not a file.
    check("no bare live path to a per-Congress file", sorted(set(b for b in bare if b != "federal-congresses")), [])
    for name in ("current-members.json", "federal-votes-index.json", "federal-votes-keyvotes.json",
                 "federal-party-unity.json", "federal-sponsorship-index.json", "curated-federal-bills.json",
                 "federal-en-bloc-nominees.json"):
        check(f"dataUrl('{name}')", f"dataUrl('{name}')" in html, True)
    check("vote slice via dataUrl", "dataUrl(`federal-votes/" in html, True)
    check("sponsorship slice via dataUrl", "dataUrl(`federal-sponsorship/" in html, True)
    check("former pages hide contact details", "!FORMER &&" in html, True)
    check("former pages hide social accounts", "!FORMER && socLinks.length" in html, True)
    check("frozen pages never join the live enacted-law index", "Promise.resolve(new Map())" in html, True)


def test_committed_labels_follow_the_wording_rules():
    path = os.path.join(ROOT, "assets", "data", "federal-departure-labels.json")
    doc = json.load(open(path, encoding="utf-8"))
    for bid, rec in (doc.get("labels") or {}).items():
        text = rec["label"].lower()
        for word in ("retired", "ousted", "unseated", "defeated", "beaten", "toppled"):
            check(f"{bid}: no '{word}'", word in text, False)
        check(f"{bid}: links a results page", bool(rec.get("results")), True)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            print(name)
            fn()
    print()
    if failures:
        print(f"FAILED: {len(failures)}")
        sys.exit(1)
    print("all passed")
