"""Re-derive a published roll call's Pass/Fail from its own record.

Every field the rule in lib/ga_vote_rules.py reads is already on a published vote
(yea, nay, chamber, motionText, date, and the legislationId in billUrl), so a result
can be recomputed without re-fetching anything except, for a closed biennium, which
resolutions propose constitutional amendments. The producers run this over the
sessions they carry forward (so a rule fix reaches them without a full refresh), and
rederive_ga_vote_results.py runs it over a published sessions/<biennium>/votes.json.
"""

import re

from lib.ga_vote_rules import STORED_ABSTRACT_MAX, requires_two_thirds, vote_passed

_LID_RE = re.compile(r"/legislation/(\d+)")
_RESOLUTION_RE = re.compile(r"^\s*(HR|SR)\s*\d", re.IGNORECASE)
#: Titles (GetLegislationForSession captions) worth an abstract lookup for the
#: property-tax-exemption two-thirds rule: "Ad valorem tax; ... exemption",
#: "Cobb County; homestead exemption; provide". An empty title is looked up too.
_TAX_TITLE_RE = re.compile(r"ad\s+valorem|homestead|exempt|propert", re.IGNORECASE)


def legislation_id(vote):
    """The legislationId of a published vote (from billUrl, else the voteId suffix)."""
    m = _LID_RE.search(vote.get("billUrl") or "")
    return int(m.group(1)) if m else None


def two_thirds_candidate_ids(votes):
    """legislationIds whose abstract could make them two-thirds votes: every resolution
    (a constitutional amendment) and every bill whose title reads like a property-tax
    exemption (or has no title). The abstract then decides."""
    return {lid for v in votes.values()
            if _RESOLUTION_RE.match(v.get("bill") or "")
            or not (v.get("title") or "").strip() or _TAX_TITLE_RE.search(v.get("title") or "")
            for lid in [legislation_id(v)] if lid is not None}


def amendment_ids_from_soap(lids, fetch=None):
    """The subset of `lids` whose legis.ga.gov abstract needs two-thirds
    (lib.ga_vote_rules.requires_two_thirds): a constitutional amendment, or a
    property-tax exemption bill. `fetch` defaults to lib.ga_soap.get_legislation_record.
    Raises RuntimeError when any lookup fails: an unknown abstract would silently apply
    the bare-majority floor to a two-thirds vote."""
    if fetch is None:
        from lib.ga_soap import get_legislation_record as fetch
    out, failed = set(), []
    for lid in sorted(lids):
        detail = fetch(lid)
        if detail is None:
            failed.append(lid)
        elif requires_two_thirds(detail.get("summary"),
                                 bool(_RESOLUTION_RE.match(detail.get("identifier") or ""))):
            out.add(lid)
    if failed:
        raise RuntimeError("GetLegislationDetail failed for %d resolution(s): %s"
                           % (len(failed), ", ".join(map(str, failed[:20]))))
    return out


def vote_result(vote, amendment_ids):
    """'Pass'/'Fail' for one published vote record, or None if it has no tally."""
    lid = legislation_id(vote)
    passed = vote_passed(vote.get("yea"), vote.get("nay"), vote.get("chamber"),
                         lid in amendment_ids, vote.get("motionText"), lid, vote.get("date"))
    if passed is None:
        return None
    return "Pass" if passed else "Fail"


def rederive_votes(votes, amendment_ids):
    """Set every vote's `result` under the current rule, in place. Returns the changes
    as [(voteId, old, new)] sorted by date, for a report or a CHANGES entry."""
    changes = []
    for vid, v in votes.items():
        new = vote_result(v, amendment_ids)
        if new is None or new == v.get("result"):
            continue
        changes.append((vid, v.get("result"), new))
        v["result"] = new
    changes.sort(key=lambda c: (votes[c[0]].get("date") or "", c[0]))
    return changes


def rederive_bill_passage_votes(bill):
    """Set the lower-case `result` of each of a ga-bills.json bill's passageVotes, in
    place. Returns the number changed. The amendment flag comes from the bill's own
    abstract, as generate_ga_bills_soap.map_bill does."""
    ca = requires_two_thirds(bill.get("abstract"), bill.get("billType") == "resolution",
                             STORED_ABSTRACT_MAX)
    changed = 0
    for pv in bill.get("passageVotes") or []:
        passed = vote_passed(pv.get("yea"), pv.get("nay"), pv.get("chamber"), ca,
                             pv.get("motionText"), bill.get("legislationId"), pv.get("date"))
        if passed is None:
            continue
        new = "pass" if passed else "fail"
        if pv.get("result") != new:
            pv["result"] = new
            changed += 1
    return changed
