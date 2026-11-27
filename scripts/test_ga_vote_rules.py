#!/usr/bin/env python3
"""Tests for lib.ga_vote_rules and the generators' derive_result wrappers.

Guards the rule a roll call's "result" follows (see lib/ga_vote_rules.py): a majority
of the chamber's seats (Ga. Const. Art. III, Sec. V, Para. V: 91 House / 29 Senate),
two-thirds of the members elected (120 / 38) for a Georgia constitutional amendment or a
local property-tax exemption act,
a majority of those voting for the few text/calendar motions the classifier keeps, and
six roll calls pinned where the official record contradicts the rule.

Every tally below is a real roll call that VoteGA published as "Pass" before 2026-11
and legis.ga.gov's status history records as lost (or, for the exceptions, passed).

Usage:
  python scripts/test_ga_vote_rules.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.ga_vote_rules import (MAJORITY_REQUIRED_YEAS, OFFICIAL_LOST, OFFICIAL_PASSED,  # noqa: E402
                               is_local_tax_exemption, is_state_constitutional_amendment,
                               required_yeas, requires_two_thirds, vote_passed)
from generate_ga_votes_soap import derive_result as votes_result  # noqa: E402
from generate_ga_bills_soap import derive_result as bills_result  # noqa: E402

failures = []


def check(name, got, want):
    if got != want:
        failures.append("%s: got %r, want %r" % (name, got, want))


# --- the floor is a majority of SEATS, whatever the attendance ---------------
check("house floor", MAJORITY_REQUIRED_YEAS["lower"], 91)
check("senate floor", MAJORITY_REQUIRED_YEAS["upper"], 29)
check("house 91 passes", vote_passed(91, 89, "lower"), True)
check("house 90-0 fails", vote_passed(90, 0, "lower"), False)
check("senate 29 passes", vote_passed(29, 27, "upper"), True)
check("senate 28-0 fails", vote_passed(28, 0, "Senate"), False)
check("tie fails", vote_passed(100, 100, "lower"), False)
check("minority fails", vote_passed(60, 100, "upper"), False)
check("absent tally", vote_passed(None, 5, "lower"), None)
check("published chamber name", vote_passed(89, 73, "House of Representatives"), False)
# Unknown chamber must not invent a threshold.
check("unknown chamber falls back", vote_passed(60, 50, None), True)

# --- bills that legis.ga.gov records as lost the same day ---------------------
# (session, bill, chamber, yea, nay)
LOST_BILLS = [
    ("2017-18", "SB 1", "lower", 85, 83), ("2017-18", "SB 1 again", "lower", 84, 83),
    ("2019-20", "SB 72 CCR", "lower", 89, 72), ("2019-20", "HB 72 local", "lower", 82, 72),
    ("2019-20", "SB 344", "lower", 81, 68), ("2019-20", "SB 71", "lower", 83, 79),
    ("2019-20", "HB 765", "upper", 28, 19),
    ("2021-22", "SB 156", "lower", 85, 84), ("2021-22", "SB 260", "lower", 87, 75),
    ("2021-22", "SB 166", "upper", 26, 24), ("2021-22", "SB 166 again", "upper", 27, 24),
    ("2021-22", "HB 1424", "lower", 88, 79), ("2021-22", "SB 479", "lower", 89, 62),
    ("2021-22", "SB 183", "lower", 83, 55), ("2021-22", "HB 517 CCR", "upper", 28, 20),
    ("2023-24", "HB 1114", "upper", 28, 22),
    ("2025-26", "HB 360", "upper", 26, 24), ("2025-26", "HB 1324", "lower", 87, 76),
    ("2025-26", "SB 175", "lower", 89, 73), ("2025-26", "SB 568", "upper", 27, 21),
]
for session, bill, chamber, yea, nay in LOST_BILLS:
    check("%s %s %d-%d lost" % (session, bill, yea, nay), vote_passed(yea, nay, chamber), False)

# --- concurrence votes lost and then taken again (the re-vote passes) --------
# (bill, chamber, motion, lost tally, passing re-vote)
REVOTED = [
    ("2017-18 HB 125", "upper", "AGREE TO HOUSE AMENDMENT TO HOUSE SUBSTITUTE", (27, 14), (32, 15)),
    ("2017-18 SB 133", "upper", "AGREE TO HOUSE SUBSTITUTE", (26, 23), (29, 23)),
    ("2019-20 HB 516", "upper", "AGREE TO HOUSE AMENDMENT TO SENATE SUBSTITUTE", (27, 25), (29, 25)),
    ("2023-24 HB 196", "upper", "AGREE TO HOUSE AMENDMENT TO SENATE SUBSTITUTE", (28, 26), None),
    ("2023-24 HB 353", "upper", "AGREE TO HOUSE AMENDMENT TO SENATE SUBSTITUTE", (27, 26), (29, 24)),
    ("2025-26 SB 170", "upper", "AGREE TO HOUSE SUBSTITUTE", (27, 22), (50, 0)),
]
for bill, chamber, motion, lost, again in REVOTED:
    check("%s %d-%d lost" % ((bill,) + lost), vote_passed(*lost, chamber, motion=motion), False)
    if again:
        check("%s %d-%d re-vote passes" % ((bill,) + again),
              vote_passed(*again, chamber, motion=motion), True)

# --- resolutions get the same floor ------------------------------------------
check("2019-20 SR 854 26-22 lost", vote_passed(26, 22, "upper", motion="ADOPTION AS AMENDED"), False)
check("2023-24 SR 3 28-23 lost", vote_passed(28, 23, "upper", motion="ADOPTION"), False)

# --- constitutional amendments need 2/3 of the members ELECTED ---------------
check("CA house 99-73 fails", vote_passed(99, 73, "lower", True), False)      # HR 1114
check("CA house 119 fails", vote_passed(119, 0, "lower", True), False)
check("CA house 120 passes", vote_passed(120, 60, "lower", True), True)
check("CA house 162-0 passes", vote_passed(162, 0, "House", True), True)       # HR 1243
check("CA house 88-84 fails", vote_passed(88, 84, "lower", True), False)      # SR 189 (2024)
check("CA senate 32-23 fails", vote_passed(32, 23, "upper", True), False)      # SR 838
check("CA senate 28-21 fails", vote_passed(28, 21, "Senate", True), False)     # SR 875
check("CA senate 37 fails", vote_passed(37, 0, "upper", True), False)
check("CA senate 38 passes", vote_passed(38, 18, "upper", True), True)
check("CA senate 49-0 passes", vote_passed(49, 0, "upper", True), True)        # HR 1243 re-vote
check("CA required", required_yeas("House", True), 120)
check("CA unknown chamber falls back", vote_passed(60, 50, None, True), True)

# --- local property-tax exemption acts need two-thirds too -------------------
# (bill, chamber, yea, nay) — each "Lost" in legis.ga.gov's status history.
for bill, chamber, yea, nay in [
        ("2018 HB 707 (City of Roswell homestead, Local Calendar)", "lower", 107, 50),
        ("2018 HB 945 (Macon-Bibb homestead)", "lower", 104, 56),
        ("2022 HB 1062 (Upson County homestead)", "lower", 104, 61),
        ("2023 HB 391 (Early County school homestead)", "upper", 37, 14),
        ("2026 SB 627 (City of Dallas homestead)", "lower", 94, 75),
        ("2026 HB 77EX (City of Butler LHOST homestead)", "lower", 97, 72),
        ("2026 SB 5EX (City of Toccoa LHOST homestead)", "upper", 32, 19)]:
    check("%s %d-%d lost" % (bill, yea, nay), vote_passed(yea, nay, chamber, True), False)
check("tax exemption 120 passes", vote_passed(120, 40, "lower", True), True)
check("tax exemption 38 passes", vote_passed(38, 10, "upper", True), True)
HOMESTEAD = ("A BILL to be entitled an Act to provide a homestead exemption from City of Dallas "
             "ad valorem taxes for municipal purposes; to provide for a referendum")
CLARKE = ("A BILL to be entitled an Act to amend an Act to grant to residents of Clarke County "
          "and the Clarke County School District, upon their homesteads, an exemption of "
          "$10,000.00 from certain ad valorem taxes levied by the Unified Government; to provide "
          "for a referendum")
MILTON = ("A BILL to be entitled an Act to amend an Act incorporating the City of Milton, so as "
          "to modify the maximum income for a senior homestead exemption; to provide for a "
          "referendum")
STATEWIDE = ("A BILL to be entitled an Act to amend Part 1 of Article 2 of Chapter 5 of Title 48 "
             "of the Official Code of Georgia Annotated, relating to property tax exemptions, so "
             "as to provide for a state-wide exemption from all ad valorem taxes for aircraft "
             "used for the aerial application of fertilizers; to provide for a referendum")
check("local homestead exemption", is_local_tax_exemption(HOMESTEAD), True)
check("exemption of $10,000.00 (a '.' inside the clause)", is_local_tax_exemption(CLARKE), True)
check("senior homestead exemption", is_local_tax_exemption(MILTON), True)
check("statewide (Code) exemption is not local", is_local_tax_exemption(STATEWIDE), False)
check("local exemption without a referendum clause (2021 HB 797)", is_local_tax_exemption(
    "A BILL to amend an Act to grant to residents of Clarke County an exemption of $10,000.00 "
    "from certain ad valorem taxes; to provide for compliance with constitutional requirements"), True)
check("2021 HB 797 108-56 lost", vote_passed(108, 56, "lower", True), False)
cut = ("A BILL to be entitled an Act to provide a homestead exemption from City of Butler ad "
       "valorem taxes in the amount of the assessed value " + "x" * 420)[:500]
check("cut-off abstract", is_local_tax_exemption(cut, 500), True)
check("ad valorem, no exemption", is_local_tax_exemption(
    "A BILL relating to ad valorem taxation of property; to provide for a referendum"), False)
check("Code bill about exemptions is not local (2025 HB 370)", is_local_tax_exemption(
    "A BILL to amend Code Section 48-5-34 of the Official Code of Georgia Annotated, so as to "
    "require the property tax bill for any school district that opts out of the state-wide base "
    "year homestead exemption to state the total amount of reserve funds"), False)
check("sales tax referendum", is_local_tax_exemption(
    "A BILL to provide for a local option sales tax exemption; to provide for a referendum"), False)
check("two-thirds: bill exemption", requires_two_thirds(HOMESTEAD, False), True)
check("two-thirds: resolution needs an amendment", requires_two_thirds(HOMESTEAD, True), False)
check("two-thirds: amendment resolution", requires_two_thirds(
    "A RESOLUTION proposing an amendment to the Constitution so as to", True), True)
check("two-thirds: amendment wording on a bill", requires_two_thirds(
    "A RESOLUTION proposing an amendment to the Constitution so as to", False), False)
# Statewide exemptions take the majority rule; the record is mixed, so the losses are pinned.
check("2026 HB 463 statewide 32-14 passes", vote_passed(32, 14, "upper", False, "PASSAGE BY SUBSTITUTE",
                                                        66000, "2026-02-12"), True)
check("2022 SB 474 pinned lost", vote_passed(31, 17, "upper", False, "PASSAGE BY SUBSTITUTE",
                                             61902, "2022-03-04"), False)
check("2024 HB 808 pinned lost", vote_passed(33, 18, "Senate", False, "PASSAGE",
                                             65535, "2024-03-20T13:20"), False)
check("two lost pins", len(OFFICIAL_LOST), 2)
# A calendar motion on a two-thirds bill is still a majority-of-voting question.
check("2020 HB 1167 remove from local calendar", vote_passed(
    94, 64, "lower", True, "Remove from Local Calendar"), True)

# --- text/calendar motions are decided by a majority of those voting ---------
for motion in ("ADOPT COMMITTEE SUB", "ADOPTION OF THE COMMITTEE SUBSTITUTE",
               "ADOPTION OF THE SUBSTITUTE BY THE SENATOR FROM THE 2ND",
               "AGREE TO COMMITTEE REPORT", "REMOVE FROM LOCAL CALENDAR"):
    check("majority-of-voting %s" % motion, vote_passed(25, 20, "upper", motion=motion), True)
    check("required %s" % motion, required_yeas("upper", motion=motion), None)
# ...but the floor still holds for the final-action captions that look similar.
for motion in ("ADOPT", "ADOPTION", "ADOPTION BY SUBSTITUTE", "ADOPT CCR",
               "ADOPT CONFERENCE COMMITTEE REPORT", "AGREE TO SENATE SUBSTITUTE",
               "PASSAGE BY SUBSTITUTE", "LOCAL CALENDAR", "POSTPONED LOCAL CALENDAR"):
    check("floor %s" % motion, required_yeas("lower", motion=motion), 91)

# --- officially passed at 90 yeas: pinned, not a looser rule ------------------
check("four exceptions", len(OFFICIAL_PASSED), 4)
check("2018 SB 317 Senate 36-17 official pass", vote_passed(
    36, 17, "Senate", True, "PASSAGE", 51980, "2018-01-18"), True)
check("2018 SB 317 House 107-50 still lost", vote_passed(
    107, 50, "House", True, "Local Calendar", 51980, "2018-02-14"), False)
for lid, day, yea, nay, label in [(57775, "2020-06-17", 90, 69, "HB 1029"),
                                  (57776, "2020-06-17", 90, 65, "HB 1030"),
                                  (62042, "2022-03-11", 90, 59, "HB 1331")]:
    check("%s official pass" % label,
          vote_passed(yea, nay, "House of Representatives", legislation_id=lid, date=day), True)
    check("%s bills casing" % label, bills_result(yea, nay, "lower", False, "PASSAGE", lid, day), "pass")
    check("%s votes casing" % label, votes_result(yea, nay, "House", False, "PASSAGE", lid, day), "Pass")
    # The pin is exact: another date, tally or bill falls back to the rule.
    check("%s other day" % label, vote_passed(yea, nay, "lower", legislation_id=lid, date="2020-01-01"), False)
    check("%s other tally" % label, vote_passed(yea, nay + 1, "lower", legislation_id=lid, date=day), False)
    check("%s without id" % label, vote_passed(yea, nay, "lower", date=day), False)
check("string id", vote_passed(90, 69, "lower", legislation_id="57775", date="2020-06-17T11:41"), True)

# --- detection: Georgia amendment vs US Constitution --------------------------
check("state amendment",
      is_state_constitutional_amendment(
          "A RESOLUTION proposing an amendment to the Constitution so as to authorize the General Assembly"), True)
check("state amendment w/ CA tag",
      is_state_constitutional_amendment("CA A RESOLUTION proposing an amendment to the Constitution of Georgia"), True)
check("US amendment excluded",
      is_state_constitutional_amendment(
          "A RESOLUTION proposing an amendment to the Constitution of the United States"), False)
check("US convention call excluded",
      is_state_constitutional_amendment("A RESOLUTION to call a convention under Article V"), False)
check("study committee", is_state_constitutional_amendment(
    "A RESOLUTION creating the Senate Addressing Felony Disenfranchisement in Georgia's Constitution Study Committee"), False)
check("empty", is_state_constitutional_amendment(None), False)

# --- both generators agree, in their own casing -------------------------------
for yea, nay, chamber, ca in [(99, 73, "lower", True), (49, 0, "upper", True),
                              (100, 50, "lower", False), (89, 73, "lower", False),
                              (10, 20, "upper", False), (28, 22, "upper", False)]:
    v = votes_result(yea, nay, "House" if chamber == "lower" else "Senate", ca)
    b = bills_result(yea, nay, chamber, ca)
    check("generators agree %s-%s" % (yea, nay), (v or "").lower(), b)
check("votes casing", votes_result(99, 73, "House", True), "Fail")
check("bills casing", bills_result(89, 73, "lower"), "fail")
check("votes no chamber default", votes_result(5, 3), "Pass")

# --- veto overrides need two-thirds whatever the bill ------------------------
check("override 94-77 lost (2026 HB 1192)", vote_passed(94, 77, "lower", False, "Veto Override"), False)
check("override 120 passes", vote_passed(120, 50, "lower", False, "Veto Override"), True)
check("senate override 37", vote_passed(37, 10, "upper", False, "VETO OVERRIDE"), False)

# --- legis.ga.gov LegislationType decides the kind of measure ----------------
LOCAL_EXEMPTION_WITH_CODE = ("A BILL to be entitled an Act to provide a homestead exemption from "
                             "Dade County school district ad valorem taxes; to provide for "
                             "applicability of Code Section 48-5-44 of the Official Code of Georgia")
check("CA type", requires_two_thirds("anything", True, legislation_type="CA"), True)
check("LOC exemption naming the Code", requires_two_thirds(LOCAL_EXEMPTION_WITH_CODE, False,
                                                           legislation_type="LOC"), True)
check("LOC exemption, no type: heuristic misses it",
      requires_two_thirds(LOCAL_EXEMPTION_WITH_CODE, False), False)
check("LOC non-exemption", requires_two_thirds("A BILL to amend the charter of Dalton", False,
                                               legislation_type="LOC"), False)
check("GEN exemption stays majority", requires_two_thirds(
    "A BILL to provide a homestead exemption from ad valorem taxes", False,
    legislation_type="GEN"), False)
check("PRIV never two-thirds", requires_two_thirds(
    "proposing an amendment to the Constitution", True, legislation_type="PRIV"), False)
check("type case/space folded", requires_two_thirds("x", True, legislation_type=" ca "), True)

# --- the passage classifier keeps final actions whatever the caption order ---
from lib.ga_passage import native_is_passage  # noqa: E402
for cap, want in [("SBs 234,  235,  & 336 Passage", True), ("Veto Override", True),
                  ("Uncontested House Resolutions", True),
                  ("CONSENT CALENDAR FOR SENATE STUDY COMMITTEES", True),
                  ("CONSENT CALENDAR EXPRESSING THE WILL OF THE SENATE", True),
                  ("RECEDE FROM SENATE AMENDMENT", True),
                  ("Recon SB 234,  235,  & 336", False), ("SB1 & SB2 RECON", False),
                  ("MOTION TO RECONSIDER LOCAL CONSENT CALENDAR", False),
                  ("Remove from Local Cal/Vote Separately", False), ("Attendance", False),
                  ("MORNING ROLL CALL", False),
                  ("ADOPTION OF AMENDMENT #1 BY THE SENATOR FROM THE 22ND", False),
                  ("MOTION FOR THE PREVIOUS QUESTION", False),
                  ("Local Calendar as a Whole", False), ("Local Calendar ", True),
                  ("Supplemental Local Calendar", True)]:
    check("passage %r" % cap, native_is_passage(cap), want)

if failures:
    print("FAIL (%d):" % len(failures))
    for f in failures:
        print("  " + f)
    sys.exit(1)
print("ok")
