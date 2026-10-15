# Federal party-unity and participation scorecard — design

**Date:** 2026-10-15
**Status:** approved in chat; awaiting spec review
**Scope of this document:** one implementation plan's worth of work.

## Purpose

Publish, for each member of Georgia's congressional delegation, the two
most-requested legislator statistics — **party unity** and **participation** —
derived from the complete roll-call record of the current Congress, and surface
them on that member's profile page.

The Georgia General Assembly already has this (`scripts/generate_party_unity.py`
→ `assets/data/ga-party-unity.json` → `/ga-party-unity` and the GA legislator
panel). The federal delegation has no equivalent, and until 2026-10-14 could not
have one: `federal-member-votes.json` held only roll calls attached to bills that
became law — 216 of 1,591, 13.6% of the real universe — which gave a House member
a party-line denominator of 42.

That sample is now complete (1,591 roll calls: 676 House, 915 Senate), and the
denominators are 449 for a representative and 795 for a senator. This work is the
scorecard that completeness was a precondition for.

**The sample was biased, not merely small**, which is why this had to wait: on the
old enacted-law frame Carter read 100.0% party unity against 98.9% on the full
record, and Ossoff read 91.5% against 96.0%. A scorecard built on the old sample
would have published wrong numbers with every appearance of precision.

## Scope

**In:**
- A build-time generator producing `assets/data/federal-party-unity.json`.
- A scorecard panel on `/us-congress/<slug>/` showing the member's two figures
  with delegation context.
- Extraction of the shared party-unity rule into `scripts/lib/party_unity.py`,
  called by both the GA and federal generators.
- Offline tests, a structural validator, and workflow wiring.

**Out (deliberately, each its own task):**
- A dedicated `/federal-party-unity` comparison page. Panel first; the page is a
  clean follow-up once the numbers are live.
- Publishing the scorecard to `Votega/ga-federal-legislators`. Nothing about a
  named politician's loyalty leaves the site until the numbers have been seen in
  place.
- Removing the duplicated client-side methodology from the GA legislator page.
  This work stops creating new duplication; it does not clean up the old.
- Scoring all 435 House / 100 Senate members. Per-member vote records are
  Georgia-scoped by design.

## Methodology

Both definitions mirror the GA generator one-for-one. They are not re-invented
for the federal data, and any divergence between the two surfaces is a bug.

**Party unity.** Of the roll calls where a majority of the member's own party
voted opposite a majority of the other party (a "party-line vote"), the share on
which the member sided with their own caucus. This is the CQ/Voteview definition:
it deliberately ignores lopsided, bipartisan and unanimous votes, which say
nothing about a member's independence.

A roll call qualifies only when **all** of these hold:
- the member cast Yea or Nay (an absence is not a defection);
- their own caucus has at least two Yea/Nay voters — with one, "the party's
  position" is just the member's own vote;
- neither caucus is tied;
- the two caucus majorities point in opposite directions.

**Participation.** Of the roll calls held in the member's own chamber while they
were seated, the share on which they cast a Yea or Nay. "Other" (not voting,
present, absent, excused) counts against it. This is a floor-vote participation
rate, not attendance.

**The seated window is free, and that is load-bearing.** The denominator is the
member's own vote records, not the chamber's total. The chambers' roll-call XML
lists only members seated at the time, so a mid-Congress arrival is scored against
the votes held since they arrived: Fuller is scored against 205 roll calls and
Blair against 29, not 676. Any change that derives the denominator from the
chamber total instead would publish both as having missed most of the Congress.

**All recorded votes count, including nominations and procedural motions.** This
matches CQ and the GA generator. It was tested against the alternative and the
choice barely moves the headline figure, while a federal-specific exclusion rule
would diverge from the GA page for no measurable gain:

| member | all votes | excl. nominations | measures only |
|---|---|---|---|
| Ossoff (D) | 96.0% (n=795) | 95.6% (n=596) | 94.6% (n=387) |
| Warnock (D) | 94.9% (n=818) | 95.2% (n=608) | 95.2% (n=394) |
| Carter (R) | 98.9% (n=449) | 98.9% (n=449) | 98.9% (n=445) |

## Architecture

The computation is server-side; the page renders and computes nothing.

```
federal-member-votes.json ─┐
                           ├─> generate_federal_party_unity.py ─> federal-party-unity.json ─> entity panel
current-members.json ──────┘        (via lib/party_unity.py)
```

**Why not compute it in the browser.** The panel shows delegation context, which
needs all 16 members' votes. The entity page deliberately fetches only the
member's own ~7 KB slice plus a 3 KB key-votes sidecar; the full index is lazy.
Computing ranks client-side would mean 16 slice fetches or re-shipping the 1.2 MB
monolith — undoing the slicing work this depends on.

### `scripts/lib/party_unity.py`

The CQ rule in one place, as pure functions over already-prepared inputs:

- `party_line_direction(tally, party, other_party)` → `"Yea"`, `"Nay"` or `None`
  (None when the roll call is not a party-line vote by the four clauses above).
- `score_unity(member_votes, tallies, party, other_party)` →
  `(party_line_votes, voted_with_party)`.
- `score_participation(member_votes)` → `(total, cast, missed)`.

Deliberately NOT moved here, because they have no federal analogue: the
bundled-bill `rollcall_key` dedup (SOAP fans one floor vote out into a record per
bill), `chamber_from_motion` inference, `VOTING_CHAMBERS`, `DEPARTED_STATUSES`,
and the presiding-officer heuristic. Those stay in the GA generator.

**Byte-identity guarantee.** Extracting this touches working GA code that
publishes numbers about real legislators. `assets/data/ga-party-unity.json` must
be byte-identical before and after the refactor, verified by regenerating and
diffing. If it is not, the extraction is wrong and gets reverted rather than
accepted — a changed number is a changed published claim.

### `scripts/generate_federal_party_unity.py`

Input `assets/data/federal-member-votes.json` and
`assets/data/current-members.json`; output `assets/data/federal-party-unity.json`,
written through `lib/atomic_io.write_json_atomic`.

Per member: filter to own-chamber roll calls, build participation from their own
records, and score unity against the per-vote `partyTally` the roll-call data
already carries (so no second pass over other members' votes is needed).

Ranks are computed within the member's **chamber delegation** — 14 in the House,
2 in the Senate — not within their party. Unity is "loyalty to one's own caucus"
and is comparable across parties; party is reported alongside the rank.

### Data shape

```json
{
  "metadata": {
    "generatedAt": "...", "congress": 119, "sessionName": "119th Congress",
    "source": "Derived from federal-member-votes.json (Clerk of the House + Senate.gov roll calls)",
    "scope": "Georgia's congressional delegation, every recorded roll call of the Congress",
    "methodology": { "partyUnity": "...", "participation": "..." },
    "count": 16, "scoredForUnity": 16, "withVotesButNotInRoster": 2
  },
  "members": {
    "<bioguideId>": {
      "chamber": "House", "party": "Republican",
      "totalRollCalls": 676, "cast": 636, "missed": 40,
      "participationRate": 0.9408, "missedRate": 0.0592,
      "partyUnity": 0.9889, "partyLineVotes": 449, "votedWithParty": 444,
      "independenceRate": 0.0111,
      "unityRank": 4, "participationRank": 9, "cohortSize": 14
    }
  },
  "delegation": {
    "House": { "cohortSize": 14, "medianUnity": 0.9712, "medianParticipation": 0.9633 },
    "Senate": { "cohortSize": 2, "medianUnity": 0.9545, "medianParticipation": 0.9781 }
  }
}
```

(Values above are illustrative of the shape; the real ones come from the run.)

**Rank 1 is the top of the metric, both times**: `unityRank: 1` is the member who
sided with their own caucus most often, `participationRank: 1` the one who cast
the largest share of their roll calls. Ties take the same rank, and the next rank
skips accordingly (standard competition ranking), so two members tied at rank 3
are followed by rank 5 — the panel must not imply a strict ordering the data does
not support.

`partyUnity` is `null`, with `partyLineVotes: 0`, for a member with no qualifying
roll calls. It is never `0` — those are different claims, and `0` reads as total
disloyalty.

### Panel

Top of the Voting History tab in `_includes/entity/federal-legislator.html`,
above the existing Yea/Nay/Other chart, which is a weaker version of the same
idea. Fetched through `getBasePath()`, cached like the other panel artifacts, and
rendered with `escHtml()` on every interpolated value.

**Rank is shown only when the cohort is ≥5.** For the 14-member House delegation
a rank is informative. For 2 senators "2nd of 2" is noise, so the panel renders a
direct peer comparison instead ("Ossoff 96.0% · Warnock 94.9%"), which is
genuinely more useful at n=2. The threshold is a named constant, not a magic
number, because the Senate cohort is 2 only until Georgia's delegation changes.

The panel carries its own dated provenance line from this file's own
`generatedAt`, per CLAUDE.md — it must not borrow the page's Congress.gov stamp,
which names the roster's source, not this one's.

## Error handling

Every failure mode degrades to saying less, never to asserting something false.

- Artifact missing or unfetchable → the Voting History panel renders exactly as it
  does today, with no scorecard block. A scorecard is an enhancement, not a
  precondition.
- Member absent from the artifact → no scorecard block for them. Never "0%".
- `partyUnity: null` (no party-line votes) → the panel prints the participation
  figure and says unity cannot be computed, rather than showing a zero.
- A member with vote records but no roster entry (`S001157`, `G000596` — departed
  mid-Congress) has no party and cannot be scored. They are excluded and counted
  in `metadata.withVotesButNotInRoster`, the same spirit as the existing
  `staleVoteRecords` reconciliation.

## Testing

`scripts/test_federal_party_unity.py` — fixture-based, no network, no repo
writes, and **no third-party imports**, so it runs under `run-script-tests.yml`,
which installs no pip packages (this is what broke that job on 2026-10-15).

Pins:
- each clause of the party-line rule: a tied caucus excluded, both caucuses
  agreeing excluded, a lone same-party voter excluded, an absence not counted as
  a defection;
- the seated window — a member present for only the last N roll calls is scored
  against N, not the chamber total;
- rank and median computation, including the ≥5 cohort threshold;
- `partyUnity` is `null` and not `0` when nothing qualifies.

Plus: the GA byte-identity check described above, and
`scripts/validate_federal_party_unity.py` — a structural check (every roster
member present, rates within 0..1, `votedWithParty <= partyLineVotes`,
`cast <= totalRollCalls`, no member scored against more roll calls than their
chamber held) wired into `update-federal-votes.yml` after the slice build, with
the artifact added to that workflow's commit and restore paths.

## Verification

Before this is called done: a local run producing real figures for all 16
members; the GA artifact proven byte-identical; the panel verified in the browser
on a clean `/us-congress/<slug>/` URL for both a representative (rank shown) and
a senator (peer comparison shown); and a member with a short seated window
(Blair, 29 roll calls) checked to confirm he is not reported as having missed the
Congress.
