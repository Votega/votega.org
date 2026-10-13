# Scope: session toggle on the GA legislator vote history

Follow-up to the incremental-fetch work. The premise behind this request was: if the
producer only pulls the active session and preserves the closed ones, the UI needs a way
to view each session so nothing is lost as one session gives way to the next.

That premise is right **within a biennium**, and the toggle below delivers it. There is
one boundary where it does not hold, and it is worth separating before building.

## First: preservation does not put data at risk

Worth stating plainly, since it motivated the question. Carrying closed sessions forward
instead of re-fetching them does **not** make the stored file a single point of failure:

- The upstream SOAP service publishes every session back to **2001-2002** (23 sessions in
  `assets/data/ga-legis-sessions.json`), so closed-session votes are always re-derivable.
- `--full-refresh` is the rebuild path, and the producer **aborts rather than publish** a
  file short a preserved session — so a lost or corrupted file fails loudly and is
  recoverable, rather than silently shipping a gap.
- Every session is independently archived to `Votega/ga-legislators` under
  `sessions/<slug>/votes.json`, which is append-only ("never overwritten once a new
  session begins", `scripts/publish_ga_legislators.py:8-11`).

So the toggle is a **navigation** improvement, not a safeguard. Nothing is lost without it.

## The boundary that actually loses data from the site

Two different things are being conflated by "as we move from session to active session":

**Within a biennium** (today: `2025_26` regular + `2026_ss` special) — both sessions live
in `ga-member-votes.json` and its derived `ga-votes-index.json`. Preservation keeps the
closed one. A toggle surfaces both. **This is Scope A, and it works.**

**Across a biennium rollover** — `SESSION_NAMES` resets to the new biennium, so
`preserved_session_ids()` returns nothing, `preserve` is empty, and the prior biennium
**leaves the site's own data files entirely**. It persists only in the sibling archive
repo. After the 2027-2028 rollover, a visitor on votega.org would see a member's
2027-2028 votes and would have to go to GitHub for 2025-2026.

A session toggle does not fix that, because the data is not in the file the page reads.
That is **Scope B**, and it is a materially bigger piece of work. If "we shouldn't lose
anything" means across bienniums too, Scope A alone will not satisfy it.

---

## Scope A — session toggle within the biennium

### Precedent to copy, not invent

`ga-bills.html` already implements exactly this control and it is live today:

- `ga-bills.html:398-400` — `<label class="sr-only">` + `<select id="billSession">` with an
  `All sessions` option, `display:none` by default.
- `ga-bills.html:918-933` (`buildSessionDropdown`) — builds options from
  `metadata.sessions`, counts records per session from the data actually present, and
  **reveals the control only when more than one session has records**
  (`multiSession = present.length > 1`). Option labels carry counts: `2026 Special Session (176)`.
- `ga-bills.html:819` — the filter predicate: `if (sessionFilter && (b.session || '') !== sessionFilter) return false;`

Being data-driven off `metadata.sessions` is the important part: the control appeared on
its own when the special session opened, and will disappear at a rollover when only one
session is present. Mirror that rather than hardcoding.

### What changes on the legislator page

`_includes/entity/ga-legislator.html` already **groups** by session — it just cannot
filter. `:1379-1394` builds `bySession`, orders it by `metadata.sessions`, and renders a
labeled `<h3>` per session with a vote count, all sections expanded.

The pieces already in place:

| Need | Already there |
|---|---|
| Session tag per vote | `votesIndex[voteId].session` (`:1384`) |
| Session display names | `sessionNames` from `metadata.sessions` (`:1296-1297`) |
| Render order | `order`, regular-first per metadata (`:1387-1388`) |
| Per-session grouping and counts | `bySession`, rendered at `:1392-1394` |
| Active session id | `activeSession` (`:1298`) |

So the change is: add the select, and make `votesTablesHtml` render the selected group
instead of all groups. The grouping logic is reusable as-is.

### The real reason to do it

The vote table has **no pagination, no cap, no collapse** — `renderRows` (`:1347`) maps
the entire list into one `innerHTML` write.

- Median member: **1,353 rows on one page** (measured across all 246 shards)
- Split: roughly **1,109 regular + 244 special**
- 230 of 246 members span both sessions; 12 are regular-only (departed mid-biennium),
  4 special-only (new arrivals)

Be honest about what filtering buys: regular-session-only is 1,353 → ~1,109, an 18% cut.
**The length problem is mostly inside the regular session, not between sessions.** A
session toggle is the right navigation control; it is not a page-weight fix.

If page weight is the goal, defaulting to the **active** session is the lever: 1,353 → 244,
an 82% cut, and it matches what a visitor most likely wants (the recent record) with
`All sessions` one click away. That is a product decision, not a technical one — and it
is the one decision in Scope A worth making deliberately rather than by default.

### The thing that will break if unattended

**The summary figures above the table are biennium-wide.** `buildParticipationSummary`
(`:1078`) and `buildPartyLoyaltySummary` (`:1144`) are computed from the member's full
`memberVotes`, as is `buildVoteChart` (`:1324`). Filter the table to the special session
and those three still describe the whole biennium — a visitor reading "participation 94%"
directly above 244 special-session rows will reasonably read it as the special session's
figure.

Three options, in increasing cost:

1. **Label them** as biennium-wide and leave them unfiltered. Cheapest, honest, slightly
   unsatisfying.
2. **Recompute on filter change.** Participation and the chart recompute cleanly from the
   filtered list. Party loyalty is the catch: it reads `partyVoteIndex` built from
   `partyTally` per vote (`:1329-1332`), which is per-roll-call and so does filter
   correctly — but `generate_party_unity.py`'s published scorecard does not, see below.
3. **Scope the scorecard too.** `ga-party-unity.json` records have **no `session` field**
   (keys: `totalRollCalls`, `cast`, `missed`, `participationRate`, `partyUnity`, …) —
   figures are pooled across the biennium. Per-session scorecards mean changing
   `generate_party_unity.py` and the `sessions/<biennium>/scorecard.*` archive layout.
   Real work, and it would make the scorecard link at `:1343` session-aware too.

Recommend **(2) for the member page, with the scorecard link labelled biennium-wide**.
(3) is a separate project; do not let it block the toggle.

### Smaller details

- **Deep links.** `ga-bills.html` holds `sessionFilter` in a JS variable, not the URL, so
  its filter is not shareable. If a shareable "my rep's special-session record" link is
  wanted, that is a `?session=` param — and worth adding to both pages at once for
  consistency rather than diverging.
- **The `incomplete` banner is dormant.** `:1304` reads
  `metadata.paginationComplete === false`, which the SOAP source never sets (`:1299-1303`
  documents it as a legacy Open States guard). So the banner cannot fire and does not
  need session-scoping. One less interaction.
- **Empty-state copy.** `:1288` already says "in our data for this session" — singular,
  and written when one session was the only option. Reword for the filtered case.
- **The 12 regular-only members** are exactly the departed members from the votes-producer
  scope doc. Their pages would show an empty active-session view. The data-driven reveal
  handles it (only one session present → no control), but it is the case to test.

### Effort

Small — a select, a predicate, and re-rendering the selected group, following a pattern
that already exists in the repo. The cost is concentrated in the summary-figures decision
above, not the toggle. Comparable to a focused afternoon, assuming option (2).

---

## Scope B — cross-biennium history (sketch, not costed)

If the goal is that a visitor never loses access to a prior biennium **on the site**, the
options are:

1. **Read the archive from the page.** `Votega/ga-legislators` has a root `latest.json`
   that "indexes every session and names its files" (`_data/open_data.yml:46`), with
   `sessions/<slug>/votes.json` per session. The member page could offer prior bienniums
   as additional toggle options, fetched on demand from the archive. Keeps the site's own
   payload flat; adds a cross-origin runtime dependency on GitHub for historical views.
2. **Keep prior bienniums in the site's data.** Simplest conceptually, but it grows
   `ga-votes-index.json` and the 246 shards without bound — directly against the payload
   findings in the audit (§4). Would need the index/detail split first.
3. **Per-biennium static pages.** Publish a frozen vote-history page per biennium at
   rollover. No runtime dependency, no payload growth, but a new publishing step and the
   pages go stale by design (which is correct for an archive).

(1) is the most consistent with how the repo already treats archives — the scorecard link
at `ga-party-unity.html:236` already points into `sessions/<biennium>/` in that repo. But
it is the first time a page would depend on the sibling repo at runtime, which deserves a
deliberate decision rather than being smuggled in under "add a toggle".

## Suggested order

1. Scope A toggle, defaulting to the active session, with participation and the chart
   recomputing on change and the scorecard link labelled biennium-wide.
2. `?session=` deep links on both the legislator page and `ga-bills.html`.
3. Decide Scope B explicitly at — or before — the next biennium rollover. It is not
   urgent until then, but it is much easier to decide while the archive layout is fresh
   than to retrofit after a rollover has already dropped a biennium off the site.
