"""Pass/Fail rules for Georgia General Assembly roll calls.

One definition shared by generate_ga_bills_soap.py, generate_ga_votes_soap.py and
rederive_ga_vote_results.py, so the outputs cannot disagree about whether a vote passed.
check_ga_vote_status.py tests published results against legis.ga.gov's status history.

Rule, for the final-action roll calls the producers keep (lib/ga_passage):

  * Constitutional majority. "No bill shall become law unless it shall receive a
    majority of the votes of all the members to which each house is entitled"
    (Ga. Const. Art. III, Sec. V, Para. V). The count is of seats, not of members
    sitting or voting, so vacancies do not lower it: 91 of 180 in the House, 29 of 56
    in the Senate. legis.ga.gov's status history applies the same floor to the
    resolutions these roll calls carry (SR 854 at 26-22 in 2020 and SR 3 at 28-23 in
    2023 are both "Senate Lost"), and to concurrence and conference-report votes
    (HB 516 at 27-25 and SB 72 at 89-72 were lost and voted again). A bare majority of
    those voting is NOT enough: 85-83 is a lost bill (2017 SB 1).
  * Two-thirds of the members elected, 120 House / 38 Senate, for
      - a resolution proposing an amendment to the GEORGIA Constitution (Art. X,
        Sec. I, Para. II), and
      - a LOCAL act granting or changing a property-tax (homestead) exemption. Art. VII, Sec. II, Para. II(a)(1) sets two-thirds for exemptions,
        and the chambers hold local homestead acts to it: every one that missed 120 /
        38 is recorded as lost (2018's House local calendar at 107-50, 2023 HB 391 at
        37-14 in the Senate, 2026 SB 627 at 94-75, some 160 roll calls on the 2026
        special session's LHOST exemptions).
    Statewide exemption bills (those amending the Official Code) are NOT given
    two-thirds: the record is mixed (2026 HB 463 passed the Senate at 32-14, 2022
    SB 474 lost at 31-17) and the abstract does not say which kind each is, so the
    statewide ones that lost are pinned in OFFICIAL_LOST.
  * Questions decided by a majority of those voting: the few motions on a bill's text
    or calendar placement that the passage classifier keeps (adopting a committee
    substitute, agreeing to a committee report, removing a bill from the local
    calendar). They do not pass the bill, so Para. V does not reach them.
  * OFFICIAL_PASSED / OFFICIAL_LOST: roll calls where the official record contradicts
    the rule (three House votes passed at 90 yeas; a Senate homestead exemption passed
    at 36; two statewide exemptions lost). The journals were not read; the status
    history, and for passes the governor's signature, are the evidence. Each is pinned
    rather than bending the rule.

Veto overrides (two-thirds) are not modelled; they do not occur among passage votes.
"""

import re

#: Seats per chamber (Ga. Const. Art. III, Sec. II, Para. II) and the constitutional
#: majority of them: a bill passes on at least this many yeas.
CHAMBER_SEATS = {"lower": 180, "upper": 56}
MAJORITY_REQUIRED_YEAS = {c: n // 2 + 1 for c, n in CHAMBER_SEATS.items()}   # 91 / 29

#: Two-thirds of the members elected, keyed by chamber (see requires_two_thirds).
TWO_THIRDS_REQUIRED_YEAS = {"lower": 120, "upper": 38}
CONST_AMENDMENT_REQUIRED_YEAS = TWO_THIRDS_REQUIRED_YEAS   # older name

#: Length generate_ga_bills_soap.py cuts ga-bills.json abstracts to (its ABSTRACT_MAX).
STORED_ABSTRACT_MAX = 500

#: "A RESOLUTION proposing an amendment to the Constitution so as to …" — the abstract
#: GA writes for a state amendment. The negative lookahead excludes resolutions that
#: propose an amendment to the United States Constitution (a convention call or a
#: ratification), which do not need two-thirds.
_STATE_AMENDMENT_RE = re.compile(
    r"proposing\s+an\s+amendment\s+to\s+the\s+Constitution(?!\s+of\s+the\s+United\s+States)",
    re.IGNORECASE,
)

#: A property-tax exemption in a bill's abstract: "a homestead exemption from Cobb
#: County school district ad valorem taxes", "an exemption of $10,000.00 from certain
#: ad valorem taxes", "the maximum income for a senior homestead exemption". Clauses are
#: ';'-separated, so the two halves of the second and third forms must share one.
_AD_VALOREM_EXEMPTION_RE = re.compile(
    r"homestead\s+exemption|exempt\w*\b[^;]{0,200}?ad\s+valorem|ad\s+valorem[^;]{0,80}?exempt",
    re.IGNORECASE)
#: A general bill amends the Code; a local act amends or creates an Act for one place.
_GENERAL_LAW_RE = re.compile(r"Official\s+Code\s+of\s+Georgia", re.IGNORECASE)

#: Kept captions that decide a question about the bill's text or calendar placement,
#: not the bill itself, so a majority of those voting carries them.
_MAJORITY_OF_VOTING_MOTION_RE = re.compile(
    r"^\s*(adopt(ion\s+of)?\s+(the\s+)?(committee\s+)?sub|agree\s+to\s+committee\s+report|"
    r"remove\s+from)",
    re.IGNORECASE,
)

#: Officially passed below the floor: (legislationId, chamber, date, yea, nay) -> note.
#: The three 90-yea House votes were each followed within the minute by a House Notice
#: to Reconsider, then passed the Senate and were signed, so the House treated them as
#: passed; the journal's own count was not checked. The tally is in the key so a
#: corrected tally drops out.
OFFICIAL_PASSED = {
    (57775, "lower", "2020-06-17", 90, 69): "2019-20 HB 1029: House Passed/Adopted, Act 415",
    (57776, "lower", "2020-06-17", 90, 65): "2019-20 HB 1030: House Passed/Adopted, Act 416",
    (62042, "lower", "2022-03-11", 90, 59): "2021-22 HB 1331: House Passed/Adopted, Act 727",
    # Two short of two-thirds on a local homestead exemption, yet "Senate Passed/Adopted"
    # (the same bill then lost in the House at 107-50 and passed later; Act 485).
    (51980, "upper", "2018-01-18", 36, 17): "2017-18 SB 317: Senate Passed/Adopted, Act 485",
}

#: Officially lost although the rule passes them: statewide property-tax exemptions,
#: which the rule cannot tell from the statewide exemptions that passed by a majority.
OFFICIAL_LOST = {
    (61902, "upper", "2022-03-04", 31, 17): "2021-22 SB 474 (statewide aircraft exemption): Senate Lost",
    (65535, "upper", "2024-03-20", 33, 18): "2023-24 HB 808 (statewide personal property exemption): Senate Lost",
}

_CHAMBER_ALIASES = {
    "lower": "lower", "house": "lower", "house of representatives": "lower",
    "upper": "upper", "senate": "upper",
}


def chamber_key(chamber):
    """'lower'/'upper' for any of the chamber spellings the data uses, else None."""
    return _CHAMBER_ALIASES.get(str(chamber or "").strip().lower())


def is_state_constitutional_amendment(abstract):
    """True when a bill's abstract/summary proposes a Georgia constitutional amendment."""
    return bool(_STATE_AMENDMENT_RE.search(abstract or ""))


def is_local_tax_exemption(abstract, truncated_at=None):
    """True when a bill's abstract is a local act granting or changing a property-tax
    (homestead) exemption. A referendum is not required in the abstract: 2021 HB 797
    (Athens-Clarke) never names one and still lost at 108-56. `truncated_at` is accepted
    for callers reading cut-off abstracts; the test reads the opening clauses only."""
    a = abstract or ""
    return bool(_AD_VALOREM_EXEMPTION_RE.search(a)) and not _GENERAL_LAW_RE.search(a)


def requires_two_thirds(abstract, is_resolution, truncated_at=None):
    """True when a bill or resolution needs two-thirds of the members elected: a
    resolution proposing a Georgia constitutional amendment, or a local property-tax
    exemption act. `truncated_at` as for is_local_tax_exemption."""
    if is_resolution:
        return is_state_constitutional_amendment(abstract)
    return is_local_tax_exemption(abstract, truncated_at)


def required_yeas(chamber, two_thirds=False, motion=None):
    """Yeas a roll call needs to carry, or None when the rule is a majority of those
    voting (a text/calendar motion) or the chamber is unknown."""
    key = chamber_key(chamber)
    if key is None:
        return None
    if motion and _MAJORITY_OF_VOTING_MOTION_RE.search(motion):
        return None          # even on a two-thirds bill (2020 HB 1167, Remove from Local Calendar)
    if two_thirds:
        return TWO_THIRDS_REQUIRED_YEAS[key]
    return MAJORITY_REQUIRED_YEAS[key]


def official_exception(legislation_id, chamber, date, yea, nay):
    """(passed, note) when this roll call is pinned in OFFICIAL_PASSED / OFFICIAL_LOST,
    else None."""
    try:
        lid = int(legislation_id)
    except (TypeError, ValueError):
        return None
    key = (lid, chamber_key(chamber), (date or "")[:10], yea, nay)
    if key in OFFICIAL_PASSED:
        return True, OFFICIAL_PASSED[key]
    if key in OFFICIAL_LOST:
        return False, OFFICIAL_LOST[key]
    return None


def vote_passed(yea, nay, chamber=None, two_thirds=False, motion=None,
                legislation_id=None, date=None):
    """True/False for a roll call's outcome, or None if the tally is absent.

    `chamber` is 'lower'/'upper' (or 'House'/'Senate'/'House of Representatives').
    `two_thirds` is requires_two_thirds() for the bill. `motion` is the caption;
    `legislation_id` and `date` identify the roll call for the official pins. Yeas
    must also outnumber nays, so an unknown chamber falls back to that alone rather
    than guessing a threshold.
    """
    if yea is None or nay is None:
        return None
    pinned = official_exception(legislation_id, chamber, date, yea, nay)
    if pinned:
        return pinned[0]
    required = required_yeas(chamber, two_thirds, motion)
    return yea > nay and (required is None or yea >= required)
