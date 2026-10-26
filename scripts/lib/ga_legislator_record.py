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


def voting_sentences(m, unity):
    """Participation and party-unity sentences from one ga-party-unity.json row."""
    if not unity or unity.get("presidingOfficer"):
        return []
    name, out = m.get("name") or "This member", []
    total, cast = unity.get("totalRollCalls"), unity.get("cast")
    rate = unity.get("participationRate")
    if total and cast is not None and rate is not None:
        out.append(f"In the current General Assembly, {name} cast a Yea or Nay on "
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


def sponsorship_sentence(m, counts):
    """counts is the [primary, cosponsored] pair from ga-sponsorship-index.json."""
    if not counts or len(counts) != 2 or counts[0] + counts[1] <= 0:
        return None
    primary, co = counts
    name = m.get("name") or "This member"
    if primary and co:
        return (f"{name} is the primary sponsor of {_count(primary, 'bill or resolution', 'bills and resolutions')} "
                f"and a cosponsor of {_count(co, 'other measure', 'other measures')} in the current biennium.")
    if primary:
        return (f"{name} is the primary sponsor of {_count(primary, 'bill or resolution', 'bills and resolutions')} "
                "in the current biennium.")
    return f"{name} is a cosponsor of {_count(co, 'bill or resolution', 'bills and resolutions')} in the current biennium."


def leadership_sentence(m):
    name = m.get("name") or "This member"
    bits = []
    if (m.get("leadershipRole") or "").strip():
        bits.append(f"holds the position of {m['leadershipRole'].strip()}")
    roles = _committee_roles(m)
    if roles:
        bits.append("serves as " + "; ".join(roles))
    if not bits:
        return None
    return f"{name} " + ", and ".join(bits) + "."


def legislator_record(m, unity, sponsorship_counts):
    """Paragraphs (list of str) summarising the member's record; [] if no data."""
    paras = []
    lead = leadership_sentence(m)
    if lead:
        paras.append(lead)
    v = voting_sentences(m, unity)
    if v:
        paras.append(" ".join(v))
    s = sponsorship_sentence(m, sponsorship_counts)
    if s:
        paras.append(s)
    return paras
