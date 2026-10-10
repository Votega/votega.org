"""Pass/Fail rules for Georgia General Assembly roll calls.

One definition shared by generate_ga_bills_soap.py and generate_ga_votes_soap.py so
the two outputs cannot disagree about whether a vote passed.

Rule: a roll call passes on a simple majority of those voting (yea > nay) — this is
what Open States' `result` reproduced on every vote in the biennium — EXCEPT a
resolution proposing an amendment to the GEORGIA Constitution, which needs two-thirds
of the members ELECTED to the chamber (Ga. Const. Art. X, Sec. I, Para. II): 120 of
180 in the House, 38 of 56 in the Senate. A tally like 99-73 is a majority but a
failed amendment vote, and 31-14 in the Senate is the same.

Other supermajority and present-majority rules (veto overrides, procedural motions)
are deliberately not modelled; they do not occur among passage votes today.
"""

import re

#: Yeas needed to propose a state constitutional amendment, keyed by chamber.
CONST_AMENDMENT_REQUIRED_YEAS = {"lower": 120, "upper": 38}

#: "A RESOLUTION proposing an amendment to the Constitution so as to …" — the abstract
#: GA writes for a state amendment. The negative lookahead excludes resolutions that
#: propose an amendment to the United States Constitution (a convention call or a
#: ratification), which pass by simple majority.
_STATE_AMENDMENT_RE = re.compile(
    r"proposing\s+an\s+amendment\s+to\s+the\s+Constitution(?!\s+of\s+the\s+United\s+States)",
    re.IGNORECASE,
)

_CHAMBER_ALIASES = {
    "lower": "lower", "house": "lower",
    "upper": "upper", "senate": "upper",
}


def is_state_constitutional_amendment(abstract):
    """True when a bill's abstract/summary proposes a Georgia constitutional amendment."""
    return bool(_STATE_AMENDMENT_RE.search(abstract or ""))


def vote_passed(yea, nay, chamber=None, constitutional_amendment=False):
    """True/False for a roll call's outcome, or None if the tally is absent.

    `chamber` is 'lower'/'upper' (or 'House'/'Senate'). A constitutional amendment
    with an unknown chamber falls back to the simple-majority rule rather than guessing
    a threshold.
    """
    if yea is None or nay is None:
        return None
    if constitutional_amendment:
        required = CONST_AMENDMENT_REQUIRED_YEAS.get(_CHAMBER_ALIASES.get(str(chamber).lower()))
        if required is not None:
            return yea >= required
    return yea > nay
