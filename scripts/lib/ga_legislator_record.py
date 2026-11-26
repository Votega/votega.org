"""Prose summary of a GA legislator's record, baked into the static page.

The interactive profile fills in votes, sponsorship and committee roles by
JavaScript, so the HTML a crawler first sees used to be the same boilerplate on
every legislator page. This turns the generated data files into a few sentences
that differ per member. Pure: callers pass already-loaded rows, nothing is read
or written here, so it is testable offline.

Numbers are rounded (whole percents, integer counts) so a page's content hash,
and therefore its sitemap lastmod, does not churn on every data refresh.
Each sentence is emitted only when its data exists; a missing figure is left
out, never rendered as zero.

`past` is None for a sitting member and the biennium's label ("2025–2026") for a former
one, whose sentences are then in the past tense and name that General Assembly.
"""
from __future__ import annotations

# Roles on a committee worth naming. "Member"/"Ex-Officio" are not distinctive.
_LEADING_ROLES = ("Chairman of Subcommittee", "Vice-Chairman of Subcommittee",
                  "Chairman", "Vice Chairman", "Secretary")


def _pct(x):
    return f"{round(x * 100)}%"


def _count(n, one, many):
    return f"{n:,} {one if n == 1 else many}"


def _committee_roles(m):
    """['Chairman of Rules', 'Secretary of Ethics'] from m['committeeRoles']."""
    out = []
    for r in m.get("committeeRoles") or []:
        role, name = (r.get("role") or "").strip(), (r.get("name") or "").strip()
        if role in _LEADING_ROLES and name:
            out.append((_LEADING_ROLES.index(role), f"{role} of {name}"))
    return [t for _, t in sorted(out)]


def voting_sentences(m, unity, past=None):
    """Participation and party-unity sentences from one ga-party-unity.json row."""
    if not unity or unity.get("presidingOfficer"):
        return []
    name, out = m.get("name") or "This member", []
    total, cast = unity.get("totalRollCalls"), unity.get("cast")
    rate = unity.get("participationRate")
    if total and cast is not None and rate is not None:
        out.append(f"In the {past or 'current'} General Assembly, {name} cast a Yea or Nay on "
                   f"{cast:,} of {total:,} passage roll calls in their own chamber "
                   f"({_pct(rate)} participation).")
    plv, with_party = unity.get("partyLineVotes"), unity.get("votedWithParty")
    if unity.get("partyUnity") is not None and plv:
        party = (m.get("party") or "").strip()
        caucus = f"the {party} caucus" if party else "their caucus"
        out.append(f"On {_count(plv, 'party-line vote', 'party-line votes')}, where the two parties' majorities "
                   f"voted opposite ways, {name} voted with {caucus} {_pct(unity['partyUnity'])} "
                   f"of the time ({with_party:,} of {plv:,}).")
    return out


def sponsorship_sentence(m, counts, past=None):
    """counts is a member's row in ga-sponsorship-index.json: [primary, cosponsored,
    Senate sponsor, House sponsor]. Frozen indexes from before the last two carry only
    the first pair."""
    if not counts or len(counts) not in (2, 4) or sum(counts) <= 0:
        return None
    primary, co, senate, house = (list(counts) + [0, 0])[:4]
    name = m.get("name") or "This member"
    verb = "was" if past else "is"
    when = f"in the {past} General Assembly" if past else "in the current biennium"
    roles = []
    if primary:
        roles.append(f"the primary sponsor of {_count(primary, 'bill or resolution', 'bills and resolutions')}")
    if co:
        nouns = ("other measure", "other measures") if primary else ("bill or resolution", "bills and resolutions")
        roles.append(f"a cosponsor of {_count(co, *nouns)}")
    if senate:
        roles.append(f"the Senate sponsor of {_count(senate, 'House measure', 'House measures')}")
    if house:
        roles.append(f"the House sponsor of {_count(house, 'Senate measure', 'Senate measures')}")
    said = roles[0] if len(roles) == 1 else ", ".join(roles[:-1]) + " and " + roles[-1]
    return f"{name} {verb} {said} {when}."


def leadership_sentence(m, past=None):
    name = m.get("name") or "This member"
    bits = []
    if (m.get("leadershipRole") or "").strip():
        bits.append(f"{'held' if past else 'holds'} the position of {m['leadershipRole'].strip()}")
    roles = _committee_roles(m)
    if roles:
        bits.append(("served as " if past else "serves as ") + "; ".join(roles))
    if not bits:
        return None
    return f"{name} " + ", and ".join(bits) + (f" in the {past} General Assembly." if past else ".")


def legislator_record(m, unity, sponsorship_counts, past=None):
    """Paragraphs (list of str) summarising the member's record; [] if no data."""
    paras = []
    lead = leadership_sentence(m, past)
    if lead:
        paras.append(lead)
    v = voting_sentences(m, unity, past)
    if v:
        paras.append(" ".join(v))
    s = sponsorship_sentence(m, sponsorship_counts, past)
    if s:
        paras.append(s)
    return paras
