#!/usr/bin/env python3
"""freeze_federal_congress.py: the on-site copy of a Congress's Georgia delegation (D12).

What must hold:
  * the freeze writes only under <out-root>/<slug>/, names every member's page URL in the
    manifest, and copies each member's vote and sponsorship slices byte for byte;
  * a Congress other than the one it is filed under is refused before anything is written
    (the publisher's own refusal, reused: after 3 January the live files are the 120th's);
  * a final freeze is not replaced without --overwrite, but provisional -> final is the plan;
  * a freeze may not drop or move a URL an earlier freeze promised;
  * a member without a slice, or a roster and sponsorship index that disagree, refuse.

Usage: python scripts/test_freeze_federal_congress.py   (no network; exit 0 ok, 1 on failure)
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import freeze_federal_congress as F  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def raises(fn, exc=F.FreezeError):
    try:
        fn()
    except exc:
        return True
    return False


def tree(root):
    out = []
    for d, _, fs in os.walk(root):
        out += [os.path.relpath(os.path.join(d, f), root).replace(os.sep, "/") for f in fs]
    return sorted(out)


def member(bid, first, last, district=None, chamber="House of Representatives", state="Georgia", **kw):
    m = {"bioguideId": bid, "firstName": first, "lastName": last, "name": f"{last}, {first}",
         "state": state, "district": district, "partyName": "Republican",
         "terms": {"item": [{"chamber": chamber, "startYear": 2015}]}}
    m.update(kw)
    return m


def write(root, rel, doc):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, separators=(",", ":"))


def live(congress=119, extra_members=(), with_slice=True, index_ids=None):
    """A live data dir for a two-member delegation plus a member of another state."""
    d = tempfile.mkdtemp()
    ga = [member("A000001", "Ann", "Alpha", 1), member("B000002", "Bo", "Beta", chamber="Senate")]
    write(d, "current-members.json", {"metadata": {"generatedAt": "2026-11-20T00:00:00+00:00"},
                                      "members": ga + [member("X000009", "Xi", "Other", 3, state="Ohio")]
                                      + list(extra_members)})
    meta = {"congress": congress, "generatedAt": "2026-11-20T01:00:00+00:00", "totalVotes": 12}
    write(d, "federal-votes-index.json", {"metadata": meta, "voteIds": [], "rows": []})
    write(d, "federal-votes-keyvotes.json", {"metadata": meta, "voteIds": [], "rows": []})
    write(d, "federal-party-unity.json", {"metadata": meta, "members": {}})
    ids = index_ids if index_ids is not None else ["A000001", "B000002"]
    write(d, "federal-sponsorship-index.json",
          {"metadata": {"congress": congress, "totalSponsored": 3, "totalCosponsored": 4,
                        "generatedAt": "2026-11-20T02:00:00+00:00"},
           "members": {b: [1, 2] for b in ids}})
    write(d, "curated-federal-bills.json", [])
    if with_slice:
        for b in ("A000001", "B000002"):
            write(d, f"federal-votes/{b}.json", {"bioguideId": b, "compact": {"0": "Y"}})
            write(d, f"federal-sponsorship/{b}.json", {"bioguideId": b, "congress": congress, "primary": []})
    return d


def test_writes_manifest_roster_and_slices():
    d, out = live(), tempfile.mkdtemp()
    m = F.freeze("119th", d, out)
    files = tree(os.path.join(out, "119th"))
    check("manifest lists both members", m["members"], ["A000001", "B000002"])
    check("urls follow the page rule", m["urls"],
          {"A000001": "/us-congress/ann-alpha-ga-1/", "B000002": "/us-congress/bo-beta-senate/"})
    check("a slice per member and every shared file", files, sorted([
        "freeze.json", "current-members.json", "federal-votes-index.json", "federal-votes-keyvotes.json",
        "federal-party-unity.json", "federal-sponsorship-index.json", "curated-federal-bills.json",
        "federal-votes/A000001.json", "federal-votes/B000002.json",
        "federal-sponsorship/A000001.json", "federal-sponsorship/B000002.json"]))
    roster = json.load(open(os.path.join(out, "119th", "current-members.json"), encoding="utf-8"))
    check("only the Georgia delegation is kept", [x["bioguideId"] for x in roster["members"]],
          ["A000001", "B000002"])
    check("roster is stamped with its Congress", roster["metadata"]["congress"], 119)
    check("slice copied byte for byte",
          open(os.path.join(d, "federal-votes/A000001.json"), "rb").read()
          == open(os.path.join(out, "119th", "federal-votes/A000001.json"), "rb").read(), True)
    check("term end recorded", m["termEnds"], "2027-01-03")
    check("kind defaults to provisional", m["kind"], "provisional")


def test_refuses_a_different_congress_and_writes_nothing():
    out = tempfile.mkdtemp()
    try:
        F.freeze("119th", live(congress=120), out)
        refused = False
    except SystemExit:  # the publisher's own assert_same_congress
        refused = True
    check("the 120th's files are not filed under 119th", refused, True)
    check("nothing was written", os.listdir(out), [])


def test_roster_from_another_congress_is_refused():
    d = live()
    doc = json.load(open(os.path.join(d, "current-members.json"), encoding="utf-8"))
    doc["metadata"]["congress"] = 120
    write(d, "current-members.json", doc)
    try:
        F.freeze("119th", d, tempfile.mkdtemp())
        refused = False
    except SystemExit:
        refused = True
    check("a roster already turned over is refused", refused, True)


def test_bad_slug_missing_slice_and_disagreeing_index():
    out = tempfile.mkdtemp()
    check("bad slug", raises(lambda: F.freeze("119", live(), out)), True)
    check("missing slice", raises(lambda: F.freeze("119th", live(with_slice=False), out)), True)
    check("index disagrees with roster",
          raises(lambda: F.freeze("119th", live(index_ids=["A000001"]), out)), True)
    check("nothing written by any refusal", os.listdir(out), [])


def test_final_needs_overwrite_but_provisional_to_final_is_fine():
    d, out = live(), tempfile.mkdtemp()
    F.freeze("119th", d, out)
    final = F.freeze("119th", d, out, kind="final")
    check("provisional -> final", final["kind"], "final")
    check("a final freeze is not replaced casually",
          raises(lambda: F.freeze("119th", d, out, kind="final")), True)
    check("--overwrite replaces it", F.freeze("119th", d, out, kind="final", overwrite=True)["kind"], "final")


def test_a_promised_url_cannot_be_dropped():
    d, out = live(), tempfile.mkdtemp()
    F.freeze("119th", d, out)
    renamed = json.load(open(os.path.join(d, "current-members.json"), encoding="utf-8"))
    renamed["members"][0]["lastName"] = "Alphabet"
    write(d, "current-members.json", renamed)
    check("a changed name would move a URL: refused",
          raises(lambda: F.freeze("119th", d, out)), True)
    check("the frozen URL is untouched",
          json.load(open(os.path.join(out, "119th", "freeze.json"), encoding="utf-8"))["urls"]["A000001"],
          "/us-congress/ann-alpha-ga-1/")
    check("only with --overwrite", bool(F.freeze("119th", d, out, overwrite=True)), True)


NOMINEES = "federal-en-bloc-nominees.json"


def test_en_bloc_nominee_lists_are_frozen_when_present():
    d, out = live(), tempfile.mkdtemp()
    write(d, NOMINEES, {"metadata": {"congress": 119, "count": 0}, "batches": {}, "votes": {}, "pending": []})
    F.freeze("119th", d, out)
    frozen = os.path.join(out, "119th", NOMINEES)
    check("the nominee file is copied byte for byte",
          os.path.isfile(frozen)
          and open(os.path.join(d, NOMINEES), "rb").read() == open(frozen, "rb").read(), True)
    # A replacement freeze taken without it must not leave the old copy behind.
    os.remove(os.path.join(d, NOMINEES))
    F.freeze("119th", d, out)
    check("a freeze without the file works and keeps no stale copy", os.path.exists(frozen), False)


def test_another_congress_nominee_file_is_refused():
    d, out = live(), tempfile.mkdtemp()
    write(d, NOMINEES, {"metadata": {"congress": 120}, "batches": {}, "votes": {}, "pending": []})
    try:
        F.freeze("119th", d, out)
        refused = False
    except SystemExit:
        refused = True
    check("the 120th's nominee lists are not filed under 119th", (refused, os.listdir(out)), (True, []))


def test_unreadable_nominee_file_stops_the_freeze():
    d, out = live(), tempfile.mkdtemp()
    with open(os.path.join(d, NOMINEES), "w", encoding="utf-8") as f:
        f.write("{truncated")
    check("a damaged file is not silently left out",
          (raises(lambda: F.freeze("119th", d, out)), os.listdir(out)), (True, []))


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
