#!/usr/bin/env python3
"""Invariants of the GA roll-call index + per-member slices (build_member_votes_slices.py).

The legislator page (_includes/entity/ga-legislator.html) decodes these files with
conventions of its own, and a drift between the two sides fails silently: the page
reads a missing slice as "this member has no roll calls in our data", and an unknown
vote code decodes to undefined. So every legislator page could show an empty or
wrong voting record while CI stays green. Four conventions are shared:

  * the vote-code map (lib/votes_schema.VOTE_CODES vs the page's CODE map)
  * the Yea/Nay codes that feed partyTally
  * the slice filename transform (member_slug vs the page's id.replace(...))
  * the bill-text URL split (TEXT_URL_PREFIX + docSegments[session] + doc)

This pins each of them, then builds a fixture end to end.

Run: python scripts/test_ga_votes_slices.py        (no network, no repo writes)
"""
import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import build_member_votes_slices as B  # noqa: E402
from lib.votes_schema import VOTE_CODES, VOTE_DECODE  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INCLUDE = os.path.join(ROOT, "_includes", "entity", "ga-legislator.html")

failures = []


def check(label, got, want):
    if got == want:
        print("  ok   %s" % label)
    else:
        print("  FAIL %s: got %r, want %r" % (label, got, want))
        failures.append(label)


with open(INCLUDE, encoding="utf-8") as fh:
    include_src = fh.read()


def contract_cases():
    print("shared conventions")
    # 1. The page's CODE map decodes exactly the codes the codec writes.
    m = re.search(r"const CODE = \{(.*?)\};", include_src, re.S)
    check("the page has a CODE map", bool(m), True)
    js_code = dict(re.findall(r"(\w+):\s*'([^']*)'", m.group(1))) if m else {}
    check("the page's CODE map matches lib/votes_schema", js_code, VOTE_DECODE)

    # 2. partyTally counts the codec's Yea/Nay, not literals of its own.
    check("YEA/NAY come from VOTE_CODES", (B.YEA, B.NAY), (VOTE_CODES["Yea"], VOTE_CODES["Nay"]))

    # 3. The slice filename. The page builds it inline; pin the expression and check
    #    the Python transform agrees with a direct port of it.
    js_slug = "member.id.replace(/[^a-zA-Z0-9]+/g, '-').replace(/^-+|-+$/g, '')"
    check("the page's slice-name expression is unchanged", js_slug in include_src, True)

    def js_port(member_id):
        return re.sub(r"^-+|-+$", "", re.sub(r"[^a-zA-Z0-9]+", "-", member_id))

    for mid in ("ocd-person/7b8c3f4e-1a2b-4c5d-9e0f-123456789abc",
                "/leading/and/trailing/", "a//b", "plain", "ünïcode-id", "--x--"):
        check("slug agrees with the page for %r" % mid, B.member_slug(mid), js_port(mid))

    # 4. The bill-text URL the page rebuilds from docSegments + doc.
    check("the page rebuilds bill-text URLs from the same prefix",
          "`%s${encodeURIComponent(seg)}/${encodeURIComponent(meta.doc)}`" % B.TEXT_URL_PREFIX
          in include_src, True)
    check("the page reads docSegments from the index metadata",
          "data.metadata?.docSegments" in include_src, True)


def fixture():
    vote_ids = ["v0", "v1", "v2"]
    member_votes = {
        "ocd-person/aaa": {"0": "Y", "1": "N", "2": "NV"},
        "ocd-person/bbb": {"0": "Y", "1": "Y"},
        "ocd-person/ccc": {"0": "N", "1": "E"},
        "ocd-person/nop": {"0": "Y"},          # no party on the roster: skipped in tallies
    }
    votes = {
        "v0": {"bill": "HB 1", "session": "2025_26", "date": "2025-02-01"},
        "v1": {"bill": "SB 2", "session": "2025_26", "date": "2025-02-02"},
        "v2": {"bill": "HR 9", "session": "2025_26", "date": "2025-02-03"},
    }
    members = [{"id": "ocd-person/aaa", "party": "Democratic"},
               {"id": "ocd-person/bbb", "party": "Republican"},
               {"id": "ocd-person/ccc", "party": "Republican"},
               {"id": "ocd-person/nop"}]
    bills = [
        {"session": "2025_26", "identifier": "HB 1",
         "textUrl": B.TEXT_URL_PREFIX + "20252026/12345"},
        {"session": "2025_26", "identifier": "SB 2", "textUrl": "https://elsewhere.invalid/x"},
        {"session": "2023_24", "identifier": "HR 9",          # same number, other biennium
         "textUrl": B.TEXT_URL_PREFIX + "20232024/999"},
    ]
    return ({"metadata": {"generatedAt": "t"}, "voteIds": vote_ids,
             "memberVotes": member_votes, "votes": votes},
            {"members": members}, {"bills": bills})


def build(tmp, votes_doc, members_doc, bills_doc):
    paths = {"VOTES_FILE": "ga-member-votes.json", "MEMBERS_FILE": "ga-members.json",
             "INDEX_OUT": "ga-votes-index.json", "SLICES_DIR": "ga-votes",
             "BILLS_FILE": "ga-bills.json"}
    saved = {k: getattr(B, k) for k in paths}
    for k, name in paths.items():
        setattr(B, k, os.path.join(tmp, name))
    try:
        for k, doc in (("VOTES_FILE", votes_doc), ("MEMBERS_FILE", members_doc),
                       ("BILLS_FILE", bills_doc)):
            if doc is not None:
                with open(getattr(B, k), "w", encoding="utf-8") as fh:
                    json.dump(doc, fh)
        os.makedirs(B.SLICES_DIR, exist_ok=True)
        with open(os.path.join(B.SLICES_DIR, "departed-member.json"), "w") as fh:
            fh.write("{}")
        return B.main()
    finally:
        for k, v in saved.items():
            setattr(B, k, v)


def build_cases():
    print("end-to-end build")
    votes_doc, members_doc, bills_doc = fixture()
    with tempfile.TemporaryDirectory() as tmp:
        rc = build(tmp, votes_doc, members_doc, bills_doc)
        check("the build succeeds", rc, 0)
        with open(os.path.join(tmp, "ga-votes-index.json"), encoding="utf-8") as fh:
            index = json.load(fh)
        check("the index keeps voteIds in order", index["voteIds"], ["v0", "v1", "v2"])
        check("the index keeps the source metadata", index["metadata"]["generatedAt"], "t")
        check("docSegments maps each session to its URL segment",
              index["metadata"].get("docSegments"), {"2025_26": "20252026", "2023_24": "20232024"})

        v0, v1, v2 = (index["votes"][k] for k in ("v0", "v1", "v2"))
        check("partyTally counts Yea/Nay by party, skipping voters with no party",
              v0.get("partyTally"), {"Democratic": {"yea": 1, "nay": 0},
                                     "Republican": {"yea": 1, "nay": 1}})
        check("non-Yea/Nay codes never reach a tally",
              v1.get("partyTally"), {"Democratic": {"yea": 0, "nay": 1},
                                     "Republican": {"yea": 1, "nay": 0}})
        check("a vote with no Yea/Nay at all has no partyTally", "partyTally" in v2, False)
        check("the bill text joins on (session, identifier)", v0.get("doc"), "12345")
        check("a textUrl with another prefix is not joined", "doc" in v1, False)
        check("the same bill number in another biennium is not joined", "doc" in v2, False)

        slices = sorted(os.listdir(os.path.join(tmp, "ga-votes")))
        check("one slice per member, named by member_slug",
              slices, sorted(B.member_slug(m) + ".json" for m in votes_doc["memberVotes"]))
        check("a stale slice from a departed member is removed",
              "departed-member.json" in slices, False)
        with open(os.path.join(tmp, "ga-votes", "ocd-person-aaa.json"), encoding="utf-8") as fh:
            sl = json.load(fh)
        check("a slice carries the member id and compact map unchanged",
              sl, {"id": "ocd-person/aaa", "compact": votes_doc["memberVotes"]["ocd-person/aaa"]})

        # Decoding a slice the way the page does reproduces the member's positions.
        decoded = {index["voteIds"][int(i)]: VOTE_DECODE[c] for i, c in sl["compact"].items()}
        check("a slice decodes through the shared code map",
              decoded, {"v0": "Yea", "v1": "Nay", "v2": "Not Voting"})

    print("refusals")
    with tempfile.TemporaryDirectory() as tmp:
        legacy = {"metadata": {}, "members": []}
        rc = build(tmp, legacy, members_doc, bills_doc)
        check("a legacy-schema file is refused without writing an index",
              (rc, os.path.exists(os.path.join(tmp, "ga-votes-index.json"))), (0, False))
        check("a refused build leaves existing slices alone",
              os.listdir(os.path.join(tmp, "ga-votes")), ["departed-member.json"])
    with tempfile.TemporaryDirectory() as tmp:
        rc = build(tmp, votes_doc, members_doc, None)
        with open(os.path.join(tmp, "ga-votes-index.json"), encoding="utf-8") as fh:
            index = json.load(fh)
        check("a missing bill file only drops the text links",
              (rc, any("doc" in v for v in index["votes"].values()),
               "docSegments" in index["metadata"]), (0, False, False))


def main():
    contract_cases()
    build_cases()
    if failures:
        print("\n%d failure(s): %s" % (len(failures), failures))
        return 1
    print("\nAll passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
