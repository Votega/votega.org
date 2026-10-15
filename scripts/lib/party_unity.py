#!/usr/bin/env python3
"""The CQ party-unity rule, in one place, for every scorecard that uses it.

`generate_party_unity.py` carried this inline, and its own docstring noted that
the methodology "mirrors, one-for-one, the client-side computation that
ga-member.html already shows". Two copies of a definition that decides a published
number about a named legislator is already one too many; the federal scorecard
(`generate_federal_party_unity.py`) would have been a third. It lives here now and
both generators call it.

A **party-line vote** is a roll call where a majority of one caucus voted opposite
a majority of the other. That is the CQ/Voteview definition, and it deliberately
ignores lopsided, bipartisan and unanimous votes, which say nothing about a
member's independence. **Party unity** is the share of those votes on which a
member sided with their own caucus; **participation** is the share of the roll
calls in their record on which they cast a Yea or Nay at all.

Four conditions exclude a roll call from the unity denominator, and each one fires
in the real federal record (1,591 roll calls, 119th Congress):

    no tally at all        1 — the Speaker election, whose votes are candidate names
    tied caucus            3 — "the party's position" is undefined
    lone own-party voter   0 federally, but possible in a small chamber: with one
                             voter, "the party's position" is just the member's
                             own vote, so unity would be 100% by construction
    both caucuses agree  275 — bipartisan, not a test of loyalty

What is deliberately NOT here: anything that knows where the votes came from.
Chamber filtering, the GA bundled-bill dedup, Open States vocabularies and roster
status all stay with their own generator. This module takes a member's votes and
the per-vote tallies already prepared, and answers the one question both
generators ask.

Import from a generator in scripts/ (sys.path[0] is scripts/ when run as
`python scripts/generate_x.py`):

    from lib.party_unity import score_unity, score_participation
"""

#: The two caucuses that can define a party line. A member of neither (an
#: independent, or a member whose party we do not know) has no defined opposite
#: and therefore no unity score — `None` here is what makes that fall out.
OTHER_PARTY = {"Democratic": "Republican", "Republican": "Democratic"}

#: The two vote values that decide a question, and so the only two that can agree
#: or disagree with a caucus. Unity is always measured on these.
CAST = ("Yea", "Nay")

#: The values that mean the member did NOT vote. Everything else recorded against
#: them is a ballot they cast.
#:
#: This exists because not every roll call asks a Yea/Nay question: a Speaker
#: election records the candidate's NAME as each member's vote ("Johnson (LA)",
#: "Jeffries"). Measuring participation as "cast a Yea or Nay" counts that as a
#: missed vote, which publishes a member as having skipped a vote they turned up
#: for — every Georgia House member was off by one before this.
#:
#: It is opt-in rather than the default because the GA record has no such value
#: (Open States yields Yea/Nay/Other only), so switching GA to it would change
#: "Other" from an absence into a cast vote and move published state figures.
ABSTENTIONS = ("Not Voting", "Present", "Absent", "Excused")


def _direction(bucket):
    """'Yea'/'Nay' for a caucus's majority, or None when it is silent or tied."""
    yea = bucket.get("yea", 0)
    nay = bucket.get("nay", 0)
    if yea + nay == 0 or yea == nay:
        return None
    return "Yea" if yea > nay else "Nay"


def party_line_direction(tally, party, other_party):
    """The member's own-caucus majority direction on a party-line roll call.

    Returns "Yea" or "Nay" when `tally` describes a party-line vote, and None when
    it does not — the caller treats None as "this roll call is not part of the
    unity denominator", never as a defection.

    `tally` is `{party: {"yea": int, "nay": int}}`; any other keys (the federal
    data carries an "other" count) are ignored.
    """
    if not tally:
        return None
    own = tally.get(party)
    opp = tally.get(other_party)
    if not own or not opp:
        return None
    # At least one OTHER same-party voter: with a single voter the "party
    # position" is just this member's own vote, and unity would be 100% by
    # construction rather than by agreement.
    if own.get("yea", 0) + own.get("nay", 0) < 2:
        return None
    own_dir = _direction(own)
    opp_dir = _direction(opp)
    if own_dir is None or opp_dir is None:
        return None
    if own_dir == opp_dir:
        return None  # both caucuses agreed — bipartisan, not a party-line vote
    return own_dir


def score_unity(votes_by_rollcall, tallies, party):
    """`(party_line_votes, voted_with_party)` for one member.

    `votes_by_rollcall` is `{rollCallKey: voteString}` for this member alone;
    `tallies` maps the same keys to per-caucus counts. A member of a caucus with
    no defined opposite scores `(0, 0)`, which the caller publishes as a null
    unity rather than as zero loyalty.
    """
    other_party = OTHER_PARTY.get(party)
    if not other_party:
        return 0, 0

    considered = 0
    aligned = 0
    for key, vote in votes_by_rollcall.items():
        # An absence is not a defection: a roll call the member did not vote on
        # cannot show whether they agreed with their caucus, so it is out of the
        # denominator entirely rather than counted against them.
        if vote not in CAST:
            continue
        own_dir = party_line_direction(tallies.get(key), party, other_party)
        if own_dir is None:
            continue
        considered += 1
        if vote == own_dir:
            aligned += 1
    return considered, aligned


def score_participation(votes_by_rollcall, abstentions=None):
    """`(total, cast, missed)` over the roll calls in this member's own record.

    The denominator is the member's OWN records, never the chamber's total. Both
    sources list only the members seated at the time, so a member who arrived
    mid-term is scored against the roll calls held since they arrived — deriving
    the denominator from the chamber instead would publish every mid-term arrival
    as having missed most of the term.

    By default a vote counts as cast only if it is a Yea or a Nay, which is the
    GA rule. Pass `abstentions` (normally ABSTENTIONS) to invert the test, so that
    anything recorded which is not an absence counts as cast — see ABSTENTIONS for
    why the federal record needs that and the GA record must not have it.
    """
    total = len(votes_by_rollcall)
    if abstentions is None:
        cast = sum(1 for vote in votes_by_rollcall.values() if vote in CAST)
    else:
        cast = sum(1 for vote in votes_by_rollcall.values() if vote not in abstentions)
    return total, cast, total - cast
