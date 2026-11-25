#!/usr/bin/env python3
"""Senate nomination fields and en bloc nominee lists.

lib/senate_nominations.py, as used by generate_federal_votes_data.py and validated
by validate_federal_votes.py. An en bloc roll call's XML carries one <document> per
nomination; reading only the first one titled a vote on 48 people as a vote on one
of them. What matters here: every document is counted and listed, a list is never
partial, a Voteview row gets no list, and the lists belong to one Congress.

Run: python scripts/test_senate_nominations.py        (no network, no repo writes)
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import generate_federal_votes_data as G  # noqa: E402
from lib import senate_drop, senate_nominations as N, voteview  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print("  ok   %s" % label)
    else:
        print("  FAIL %s: got %r, want %r" % (label, got, want))
        failures.append(label)


KRAMER = "Jessica Kramer, of Wisconsin, to be an Assistant Administrator of the Environmental Protection Agency"
GIL = "Dario Gil, of New York, to be Under Secretary for Science, Department of Energy"
HOSKINS = "Dudley Hoskins, of the District of Columbia, to be Under Secretary of Agriculture"
LIST_STYLE = "Air Force nominations beginning with Anthony Aceto"


def doc(kind, number, title):
    return ("<document><document_congress>119</document_congress>"
            f"<document_type>{kind}</document_type><document_number>{number}</document_number>"
            f"<document_name>{kind}{number}</document_name><document_title>{title}</document_title>"
            "<document_short_title/></document><amendment><amendment_number/></amendment>")


def roll(number, docs, question="On the Nomination", session=1, congress=119):
    return ("<roll_call_vote>"
            f"<congress>{congress}</congress><session>{session}</session><vote_number>{number}</vote_number>"
            f"<vote_date>September 18, 2025,  04:23 PM</vote_date><question>{question}</question>"
            "<vote_result>Nomination Confirmed</vote_result>" + "".join(docs) +
            "<count><yeas>51</yeas><nays>47</nays></count>"
            "<members><member><state>GA</state><party>D</party><lis_member_id>S1</lis_member_id>"
            "<vote_cast>Nay</vote_cast></member></members></roll_call_vote>").encode()


EN_BLOC = roll(2, [doc("PN", "25-28", KRAMER), doc("PN", "12-19", GIL)])
SAME_BATCH = roll(3, [doc("PN", "12-19", GIL), doc("PN", "25-28", KRAMER)], "On the Cloture Motion")
SINGLE = roll(1, [doc("PN", "55-25", KRAMER)])
BILL = roll(4, [doc("S.", "5", "A bill")], "On Passage of the Bill")
NO_DOC = roll(5, [], "On the Motion to Adjourn")

print("Title parts:")
check("name, state and position", N.parse_title(GIL),
      ("Dario Gil", "New York", "Under Secretary for Science, Department of Energy"))
check("'of the District of Columbia' loses only the article",
      N.parse_title(HOSKINS)[1], "District of Columbia")
check("a title outside the pattern gives no parts", N.parse_title(LIST_STYLE), (None, None, None))

print("XML fields:")
parsed = lambda raw: N.nomination_fields(ET.fromstring(raw))  # noqa: E731
check("a multi-document roll call counts every nomination", parsed(EN_BLOC), ("PN", 2))
check("a single nomination counts one", parsed(SINGLE), ("PN", 1))
check("a bill has no nominee count", parsed(BILL), ("S.", None))
check("no document is null, not an empty string", parsed(NO_DOC), (None, None))

lst = N.nominees(ET.fromstring(EN_BLOC))
check("one entry per document, in source order", [e["pn"] for e in lst], ["PN25-28", "PN12-19"])
check("entry keeps the source title", lst[1], {
    "pn": "PN12-19", "name": "Dario Gil", "state": "New York",
    "position": "Under Secretary for Science, Department of Energy", "title": GIL})
unmatched = N.nominees(ET.fromstring(roll(9, [doc("PN", "1", KRAMER), doc("PN", "2", LIST_STYLE)])))
check("an unmatched title keeps its source text with null parts", unmatched[1],
      {"pn": "PN2", "name": None, "state": None, "position": None, "title": LIST_STYLE})
check("a single nomination has no list", N.nominees(ET.fromstring(SINGLE)), None)
no_number = roll(9, [doc("PN", "1", KRAMER), doc("PN", "", GIL)])
check("a document without a PN number gives no list rather than a partial one",
      N.nominees(ET.fromstring(no_number)), None)

print("Generator parse:")
meta, ga = G.parse_senate_vote(EN_BLOC, {"S1": "O000174"})
check("en bloc title is the label", meta["title"], "En bloc: 2 nominations, including Jessica Kramer")
check("fields on the row", (meta["documentType"], meta["nomineeCount"]), ("PN", 2))
check("new fields are appended after partyTally", list(meta)[-3:],
      ["partyTally", "documentType", "nomineeCount"])
meta1, _ = G.parse_senate_vote(SINGLE, {})
check("a single nomination keeps its own title", (meta1["title"], meta1["nomineeCount"]), (KRAMER, 1))
check("label for an unmatched first title uses the text before the comma",
      N.en_bloc_label(3, "John Doe, to be something else"),
      "En bloc: 3 nominations, including John Doe")
check("label with no title at all", N.en_bloc_label(3, None), "En bloc: 3 nominations")

print("Voteview recognition:")
check("two nominees joined by '; and' is en bloc", N.is_en_bloc_description(KRAMER + "; and " + GIL), True)
check("one nominee is not", N.is_en_bloc_description(GIL), False)
check("'and to serve concurrently' is not a second nominee", N.is_en_bloc_description(
    "Callista Gingrich, of Florida, to be Ambassador to Switzerland, and to serve concurrently"), False)

ROLLS = ("congress,chamber,rollnumber,date,session,clerk_rollnumber,yea_count,nay_count,"
         "bill_number,vote_result,vote_desc,vote_question\n"
         f'119,Senate,1,2025-09-18,1,1,51,47,PN2528,Nomination Confirmed,"{KRAMER}; and {GIL}",On the Nomination\n'
         f'119,Senate,2,2025-09-18,1,2,51,47,PN5525,Nomination Confirmed,"{KRAMER}",On the Nomination\n'
         '119,Senate,3,2025-09-18,1,3,51,47,S5,Bill Passed,A bill,On Passage of the Bill\n')
VV = voteview.load_senate(119, lambda url, label: {
    "rollcalls": ROLLS.encode(),
    "votes": b"congress,chamber,rollnumber,icpsr,cast_code\n119,Senate,1,1,6\n119,Senate,2,1,6\n119,Senate,3,1,6\n",
    "members": b"congress,chamber,icpsr,bioguide_id,party_code\n119,Senate,1,O000174,100\n",
}[label.split()[-1]])
check("Voteview documentType comes from the PN bill number",
      [voteview.senate_roll(VV, 1, n, set())["document_type"] for n in (1, 2, 3)], ["PN", "PN", None])


# ---------------------------------------------------------------------------
# The whole generator, with the network replaced.

@contextlib.contextmanager
def patched(**attrs):
    saved = {k: getattr(G, k) for k in attrs}
    for k, v in attrs.items():
        setattr(G, k, v)
    try:
        yield
    finally:
        for k, v in saved.items():
            setattr(G, k, v)


def generate(tmp, xml_by_number, *, congress=119, vv=None, argv=()):
    """Run G.main() into tmp. xml_by_number={n: bytes} is session 1's senate.gov;
    an empty dict means the index is unreachable (Voteview fallback)."""
    out = os.path.join(tmp, "federal-member-votes.json")
    fetched = []

    def fake_fetch(url, label=""):
        fetched.append(label)
        return xml_by_number.get(int(url.rsplit("_", 1)[1].split(".")[0]))

    saved = (sys.argv, voteview.load_senate, senate_drop.DROP_DIR, os.environ.get("FEDERAL_FREEZE_CONFIRMED"))
    sys.argv = ["x", out, os.path.join(tmp, "current-members.json"), *argv]
    voteview.load_senate = lambda c, fetch=None: vv
    senate_drop.DROP_DIR = Path(tmp) / "no-drop"
    os.environ["FEDERAL_FREEZE_CONFIRMED"] = "true"
    try:
        with patched(build_lis_to_bioguide=lambda: {"S1": "O000174"},
                     senate_vote_numbers=lambda c, s: sorted(xml_by_number) if s == 1 else [],
                     fetch_raw=fake_fetch, active_years=lambda c: [], XML_DELAY=0,
                     CURRENT_CONGRESS=congress), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            G.main()
    finally:
        sys.argv, voteview.load_senate, senate_drop.DROP_DIR = saved[:3]
        if saved[3] is None:
            os.environ.pop("FEDERAL_FREEZE_CONFIRMED", None)
        else:
            os.environ["FEDERAL_FREEZE_CONFIRMED"] = saved[3]
    with open(out, encoding="utf-8") as fh:
        votes = json.load(fh)
    side = os.path.join(tmp, N.NOMINEES_FILE)
    with open(side, encoding="utf-8") as fh:
        text = fh.read()
    return votes, json.loads(text), text, fetched


K1, K2, K3 = "S119_1_00001", "S119_1_00002", "S119_1_00003"
OFFICIAL = {1: SINGLE, 2: EN_BLOC, 3: SAME_BATCH}

print("Generator run:")
with tempfile.TemporaryDirectory() as tmp:
    votes, side, text, _ = generate(tmp, OFFICIAL)
    check("only en bloc votes are listed", sorted(side["votes"]), [K2, K3])
    check("votes with identical PN sets share one batch", side["votes"][K2] == side["votes"][K3], True)
    check("one batch", len(side["batches"]), 1)
    check("list length equals nomineeCount",
          [len(side["batches"][side["votes"][k]]) for k in (K2, K3)],
          [votes["votes"][k]["nomineeCount"] for k in (K2, K3)])
    check("metadata", (side["metadata"]["congress"], side["metadata"]["count"], bool(side["metadata"]["source"]),
                       bool(side["metadata"]["generatedAt"])), (119, 2, True, True))
    check("nothing pending", side["pending"], [])
    check("no validation problems", N.problems(votes, side), [])

    votes2, side2, text2, fetched2 = generate(tmp, OFFICIAL)
    check("a quiet run re-fetches nothing", fetched2, [])
    check("and leaves the nominee file byte-identical", text2, text)

    votes3, side3, _, _ = generate(tmp, {**OFFICIAL, 4: BILL})
    check("lists carry forward when another roll call is added",
          (side3["batches"], side3["votes"]), (side["batches"], side["votes"]))

    votes120, side120, _, _ = generate(
        tmp, {1: roll(1, [doc("PN", "1", KRAMER)], congress=120)}, congress=120)
    check("the next Congress starts with empty lists",
          (side120["batches"], side120["votes"], side120["pending"], side120["metadata"]["count"],
           side120["metadata"]["congress"]), ({}, {}, [], 0, 120))

with tempfile.TemporaryDirectory() as tmp:
    votes, side, _, _ = generate(tmp, {2: roll(2, [doc("PN", "1", KRAMER), doc("PN", "2", GIL)]),
                                       3: roll(3, [doc("PN", "1", KRAMER), doc("PN", "3", HOSKINS)])})
    check("different PN sets get different batches", len(set(side["votes"].values())), 2)

with tempfile.TemporaryDirectory() as tmp:
    votes, side, _, _ = generate(tmp, {}, vv=VV)
    rows = votes["votes"]
    check("Voteview PN rows: documentType, no count",
          [(rows[k]["documentType"], rows[k]["nomineeCount"]) for k in (K1, K2)],
          [("PN", None), ("PN", None)])
    check("a Voteview en bloc row is labelled without a number", rows[K1]["title"], "En bloc")
    check("a Voteview single nomination keeps its title", rows[K2]["title"], KRAMER)
    check("a Voteview bill carries null fields", (rows[K3]["documentType"], rows[K3]["nomineeCount"]), (None, None))
    check("no list from Voteview; the en bloc row is pending",
          (side["votes"], side["batches"], side["pending"]), ({}, {}, [K1]))
    check("pending rows validate", N.problems(votes, side), [])

    official = {1: roll(1, [doc("PN", "25-28", KRAMER), doc("PN", "12-19", GIL)]),
                2: roll(2, [doc("PN", "55-25", KRAMER)]), 3: BILL}
    votes, side, _, _ = generate(tmp, official, vv=VV)
    check("senate.gov fills a pending list later",
          (list(side["votes"]), side["pending"], votes["votes"][K1]["title"]),
          ([K1], [], "En bloc: 2 nominations, including Jessica Kramer"))

    # Unreachable again: the official rows and their lists are carried forward.
    _, side_again, _, _ = generate(tmp, {}, vv=VV)
    check("lists survive a fallback run", side_again["votes"], side["votes"])


print("Validation:")


def broken(mutate):
    v = {"metadata": {"congress": 119}, "votes": {
        K2: {"chamber": "Senate", "documentType": "PN", "nomineeCount": 2, "title": "En bloc"},
        K3: {"chamber": "Senate", "documentType": None, "nomineeCount": None, "title": "x"}}}
    entry = lambda pn: {"pn": pn, "name": None, "state": None, "position": None, "title": "t"}  # noqa: E731
    s = {"metadata": {"congress": 119, "count": 2}, "batches": {"b": [entry("PN1"), entry("PN2")]},
         "votes": {K2: "b"}, "pending": []}
    mutate(v, s)
    return bool(N.problems(v, s))


check("a sound pair passes", broken(lambda v, s: None), False)
check("a short list fails", broken(lambda v, s: s["batches"]["b"].pop()), True)
check("a repeated PN fails", broken(lambda v, s: s["batches"]["b"][1].update(pn="PN1")), True)
check("an en bloc row with no list and not pending fails",
      broken(lambda v, s: (s["votes"].clear(), s["batches"].clear(), s["metadata"].update(count=0))), True)
check("a list for a Voteview row fails",
      broken(lambda v, s: v["metadata"].update(senateRollsFromVoteview=[K2])), True)
check("a vote naming a missing batch fails", broken(lambda v, s: s["votes"].update({K2: "zz"})), True)
check("an unused batch fails", broken(lambda v, s: s["batches"].update(c=[])), True)
check("two batches with the same PN set fail", broken(lambda v, s: (
    v["votes"][K3].update(documentType="PN", nomineeCount=2),
    s["batches"].update(c=list(reversed(s["batches"]["b"]))), s["votes"].update({K3: "c"}),
    s["metadata"].update(count=4))), True)
check("another Congress's file fails", broken(lambda v, s: s["metadata"].update(congress=118)), True)
check("a wrong count fails", broken(lambda v, s: s["metadata"].update(count=3)), True)
check("a Senate row without the new fields fails", broken(lambda v, s: v["votes"][K3].pop("documentType")), True)

if failures:
    print("\nFAILED: %s" % ", ".join(failures))
    sys.exit(1)
print("\nall passed")
