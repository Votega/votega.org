#!/usr/bin/env python3
"""The one-time backfill of documentType / nomineeCount onto held Senate rows.

It edits a committed record of how senators voted, so what matters is what it does
NOT change: only the two fields are added, only en bloc titles are replaced, and a
refused or implausible fetch writes nothing at all.

Run: python scripts/test_backfill_nomination_fields.py     (no network, no repo writes)
"""
import contextlib
import copy
import io
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import backfill_federal_nomination_fields as B  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print("  ok   %s" % label)
    else:
        print("  FAIL %s: got %r, want %r" % (label, got, want))
        failures.append(label)


A = "Ann Alpha, of Ohio, to be an Assistant Secretary of Labor"
Z = "Zed Zulu, of Iowa, to be Ambassador to Greece"


def xml(number, question, docs):
    body = "".join(
        f"<document><document_type>{t}</document_type><document_number>{n}</document_number>"
        f"<document_title>{title}</document_title></document>" for t, n, title in docs)
    return ("<roll_call_vote><congress>119</congress><session>1</session>"
            f"<vote_number>{number}</vote_number><question>{question}</question>{body}"
            "<count><yeas>51</yeas><nays>47</nays></count></roll_call_vote>").encode()


XML = {
    1: xml(1, "On the Nomination", [("PN", "1", A), ("PN", "2", Z)]),
    2: xml(2, "On the Nomination", [("PN", "3", Z)]),
    3: xml(3, "On Passage of the Bill", [("S.", "5", "A bill")]),
    4: xml(4, "On the Amendment", [("S.Amdt.", "", "")]),
    5: xml(5, "On the Cloture Motion", [("S.Amdt.", "", "")]),
    6: xml(6, "On Passage of the Bill", [("S.", "6", "A bill")]),
    7: xml(7, "On Passage of the Bill", [("S.", "7", "A bill")]),
    8: xml(8, "On Passage of the Bill", [("S.", "8", "A bill")]),
    9: xml(9, "On Passage of the Bill", [("S.", "9", "A bill")]),
}


def row(number, motion, bill_type=None, title="old title"):
    return {"bill": None, "billUrl": None, "billType": bill_type, "billNumber": bill_type and str(number),
            "title": title, "motionText": motion, "date": "2025-01-01", "yea": 51, "nay": 47,
            "chamber": "Senate", "session": 1, "rollNumber": number, "result": "Pass",
            "resultText": "x", "partyTally": None}


def key(n):
    return f"S119_1_{n:05d}"


def monolith():
    votes = {key(1): row(1, "On the Nomination", title=A), key(2): row(2, "On the Nomination", title=Z),
             "H2025_0001": {"chamber": "House", "title": "house"}}
    votes[key(3)] = row(3, "On Passage of the Bill", "s")
    votes[key(4)] = row(4, "On the Amendment", "s")
    votes[key(5)] = row(5, "On the Cloture Motion", "s")
    for n in (6, 7, 8, 9):
        votes[key(n)] = row(n, "On Passage of the Bill", "s")
    return {"metadata": {"congress": 119, "generatedAt": "then"}, "votes": votes,
            "memberVotes": {"O000174": [{"voteId": key(1), "vote": "Nay"}]}}


def fetcher(files, seen):
    def fetch(session, number):
        seen.append(number)
        return files.get(number)
    return fetch


print("What changes:")
before = monolith()
original = copy.deepcopy(before)
seen = []
after, side, report = B.backfill(before, fetcher(XML, seen))
check("the input is not mutated", before, original)
check("same roll calls in the same order", list(after["votes"]), list(original["votes"]))
check("metadata and memberVotes untouched",
      (after["metadata"], after["memberVotes"]), (original["metadata"], original["memberVotes"]))
diffs = {}
for k, old in original["votes"].items():
    new = after["votes"][k]
    changed = sorted(f for f in set(old) | set(new) if old.get(f, "<absent>") != new.get(f, "<absent>"))
    if changed:
        diffs[k] = changed
check("every Senate row gains exactly the two fields, plus the en bloc title",
      diffs, {key(n): (["documentType", "nomineeCount", "title"] if n == 1
                       else ["documentType", "nomineeCount"]) for n in range(1, 10)})
check("the House row is untouched", after["votes"]["H2025_0001"], original["votes"]["H2025_0001"])
check("the fields are appended last", list(after["votes"][key(2)])[-2:], ["documentType", "nomineeCount"])
check("values", [(after["votes"][key(n)]["documentType"], after["votes"][key(n)]["nomineeCount"])
                 for n in (1, 2, 3, 4, 5)],
      [("PN", 2), ("PN", 1), ("S.", None), ("S.Amdt.", None), ("S.Amdt.", None)])
check("en bloc title", after["votes"][key(1)]["title"], "En bloc: 2 nominations, including Ann Alpha")
check("nominee file", (list(side["votes"]), side["metadata"]["count"]), ([key(1)], 2))
check("report names the en bloc votes", report["enBloc"], {key(1): 2})

print("What is fetched:")
check("nominations and ambiguous motions are always fetched", {1, 2, 5} <= set(seen), True)
check("an unambiguous group is only sampled (three of five passage votes)",
      len([n for n in seen if n in (3, 6, 7, 8, 9)]), 3)
check("report counts what was derived", report["derived"], 2)

again, side_again, _ = B.backfill(after, fetcher(XML, []), previous_nominees=side)
check("running it twice changes nothing", (again, side_again), (after, side))

print("Provisional (Voteview) rows:")
prov = monolith()
prov["metadata"]["senateRollsFromVoteview"] = [key(1)]
after_p, side_p, _ = B.backfill(prov, fetcher(XML, []))
check("no count and no list; the en bloc row is pending",
      (after_p["votes"][key(1)]["nomineeCount"], after_p["votes"][key(1)]["title"],
       side_p["votes"], side_p["pending"]), (None, "En bloc", {}, [key(1)]))


def refuses(files):
    try:
        B.backfill(monolith(), fetcher(files, []))
    except B.BackfillError as exc:
        return str(exc)
    return None


print("Refusals:")
check("senate.gov refusing one file stops the run",
      bool(refuses({k: v for k, v in XML.items() if k != 2})), True)
check("a challenge page is not a roll call",
      bool(refuses({**XML, 2: b"<html>challenge</html>"})), True)
check("the wrong roll call is refused", bool(refuses({**XML, 2: XML[1]})), True)
check("a sample that contradicts the derivation rule stops the run",
      "derivation" in (refuses({**XML, 3: xml(3, "On Passage of the Bill", [("H.R.", "5", "t")])}) or ""), True)
check("an en bloc vote without a complete list stops the run", bool(refuses(
    {**XML, 1: xml(1, "On the Nomination", [("PN", "1", A), ("PN", "", Z)])})), True)

print("Files:")
with tempfile.TemporaryDirectory() as tmp:
    votes_path = os.path.join(tmp, "federal-member-votes.json")
    side_path = os.path.join(tmp, "federal-en-bloc-nominees.json")
    start = json.dumps(monolith(), ensure_ascii=False, separators=(",", ":"))
    with open(votes_path, "w", encoding="utf-8") as fh:
        fh.write(start)
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        rc = B.main(["--votes", votes_path], fetch=fetcher({}, []))
    with open(votes_path, encoding="utf-8") as fh:
        check("a refused run exits 1 and writes nothing",
              (rc, fh.read() == start, os.path.exists(side_path)), (1, True, False))
    with contextlib.redirect_stdout(io.StringIO()):
        rc = B.main(["--votes", votes_path], fetch=fetcher(XML, []))
    check("a good run writes both files beside each other", (rc, os.path.exists(side_path)), (0, True))

if failures:
    print("\nFAILED: %s" % ", ".join(failures))
    sys.exit(1)
print("\nall passed")
