# Budgets as a `/local/` topic — scope

**Status:** phase 0 complete on a 41-place corpus including Savannah. The lexicon
holds, and the one open risk turned out to be real: a boilerplate exclusion rule is
now **required**, not optional. See **Phase 0 results** below; §2.1 and §2.3 are
superseded by it.
**Scoped:** 2026-11-03 · **Last updated:** 2026-11-03 · **Scope owner:** Justin Mays
**Parent:** `docs/LOCAL-EXPANSION-SCOPE.md` (the `/local/` expansion this continues)

---

## The decision in one line

Retire the `millage-budget` tag and replace it with a narrower `budget` topic that
earns a page — the fifth alongside ALPR, data centers, land use and local taxes.

### Decisions taken

| # | Decision |
|---|---|
| 1 | **A topic page like the other four.** Narrowed lexicon, mentions feed, `/local/topics/budgets/`, per-place section. Not a predictive "budget season" tracker — that idea is recorded under *Deliberately not in scope* and stays open. |
| 2 | **Site only for now.** `ga-local-government` keeps its four-topic schema until the lexicon has been observed across several enrichment runs. Publishing a fifth feed is a later, separate change. |
| 3 | **`millage-budget` is retired, not kept beside `budget`.** Its millage keywords already live in `local-taxes`, so nothing is lost, and retiring it removes a tag that fires on 59 of 59 places, has no page, and needs a special-case exclusion in the hub card's ranking. |

---

## Phase 0 results — measured 2026-11-03

Run on the full-text corpus from `populate-meeting-text-cache.yml` run #5
(**975 documents, 41 places, 54.8 MB**), read through the repo's own `TextCache`.
Run #5 was a targeted `slug: savannah` dispatch on top of run #3's cache, taken
because Savannah is the one place whose agenda template could break the design, and
it is not reachable by the full run's first step (it is `agendaplus`, handled by the
Granicus enricher). This replaces the excerpt-window estimates in §2.3, which were a
biased floor.

### The lexicon holds

| | documents |
|---|---|
| Old `millage-budget` rule | 455 |
| Candidate, no exclusion rule | 302 |
| **Candidate + boilerplate exclusion** | **287**, across 39 places |
| Found that the old rule missed | 0 |

The candidate is a strict subset, as expected — every pattern contains the word
*budget*, which the old rule also matched. **The whole value is precision: 455 → 287,
a 37% cut, with the budget decisions kept.**

### Precision: 1% of spans, 0% of documents

Measured at **match level**, not document level. A document-level probe cannot
attribute the match — a document containing "budgeted" somewhere *and* a real budget
amendment elsewhere is correctly flagged, and counting it as a leak overstates the
problem badly (that probe reported an alarming "85% leak" for exactly this reason).

Of **2,379 spans** that fired across the corpus, **22 (0.9%)** are excluded as
boilerplate or money plumbing. Outside Savannah, no document had only noise spans.

Hand-read samples bear this out — 26 random matched spans read, all budget business:

> Paulding — "discuss action to **adopt the FY 2027 budget**"
> Walker — "approval of minutes for the special called **budget work session**"
> Atlanta — "to **amend the FY 2027 budget** by adding to anticipations and appropriations"
> Muscogee — "to authorize **the amendment of the 2025 capital improvements budget**"
> Columbia — "May 05, 2026 **budget public hearing**"

The two marginal cases are small budget resolutions for vehicle replacement
(Forsyth) — real budget amendments, just minor ones.

### Dropped documents are dropped correctly

> Banks — "2026 **millage rate** adoption resolution" — belongs to local-taxes, which keeps the `millage` keyword ✓
> Coweta — "acceptance of the **fiscal year** 2025 emergency management performance grant" — a grant ✓
> Fulton — "monetary transfers among **budget funds** per board resolution" — arguably budget business; a real, minor loss

### The proximity rule earns its place

| | documents |
|---|---|
| Phrases only | 37 |
| **Proximity only** | **58** |
| Both | 192 |

Proximity adds **58 documents (+25%)** over phrases alone — lower than the 43%
estimated from excerpts, and still decisive. The additions are the canonical
phrasings fixed phrases structurally cannot reach: *"amend the FY 2027 budget"*,
*"adopt the FY 2027 budget"*, *"amendment of the 2025 capital improvements budget"*.

### The Savannah risk was real — and it is the most important finding here

Savannah's agenda template carries
`PUBLIC COMMENTS ARE ACCEPTED ONLY FOR HEARINGS (Alcohol, Public, Zoning, and Budget)`
on every meeting, which trips the proximity rule's `hearing … budget`. Measured on
its 40 documents:

| | documents |
|---|---|
| Contain the boilerplate | 18 |
| Flagged by the candidate rule | 18 |
| **Flagged ONLY because of the boilerplate** | **15** |
| Genuinely budget business | 3 |

**Savannah would have shown `Budgets 18` on its hub card when 3 are real** — the
worst possible failure for a change whose whole purpose was to make the card's
numbers mean something. An earlier probe reported this pattern CLEAN purely because
Savannah was absent from the corpus; absence read as evidence of safety.

#### The fix, and what it costs

A span is rejected when `budget` is the last item of a parenthesised comma list — a
category menu, never a decision. Written generically rather than hardcoding
Savannah's wording:

```
\([^)]{0,80}?,[^)]{0,40}?\band\s+budget\b[^)]{0,10}\)
```

It is **surgical**: it removes exactly 15 documents across the whole corpus, all of
them Savannah boilerplate, and changes **no other place's count at all**. Savannah
goes 18 → 3.

#### This changes the design: §2.1 is wrong

§2.1 concluded that a phrase-only lexicon "needs no new machinery". That was correct
about `budgeted` and wrong in general. **Phase 1 now needs two new rule types in the
taxonomy, not one** — proximity *and* exclusion — and the exclusion is what makes the
counts trustworthy on the hub card.

### What is still untested

**The corpus covers 41 of the 62 visible places.** Still missing: atkinson, baker,
camden, conyers, effingham, fort-oglethorpe, gordon, houston, **lafayette**, liberty,
lowndes, milledgeville, newton, oconee, palmetto, rockdale, rossville, thomas,
thomasville, tift, whitfield.

**Lafayette cannot be fetched by this workflow at all.** It is the one `sharepoint`
place, `lib/sharepoint.py` imports Playwright, and the workflow installs only
`pyyaml` — so every run fails it with `ModuleNotFoundError: No module named
'playwright'` and skips it. That is a permanent hole in the corpus, not a transient
failure, and it is worth fixing independently of this scope.

**Savannah taught the general lesson: a place's agenda template can manufacture a
topic.** The remaining 21 places have not been checked for their own boilerplate.
Before Phase 2 puts counts on cards, each should be scanned for a string that repeats
across most of its meetings.

### Lexicon changes this run justifies

Only three terms still earn nothing, down from nine on the excerpt corpus —
confirming the earlier counts were a floor:
`tentative budget`, `public hearing on the budget`, `adoption of the budget`.
They stay for now: all three are ordinary phrasings that 21 unmeasured places may
well use.

Terms the full corpus rescued, which the excerpt measurement would have wrongly
dropped: `annual budget` (26), `operating budget` (27), `capital budget` (15),
`budget ordinance` (14), `budget transfer` (13), `budget calendar` (8),
`recommended budget` (4), `balanced budget` (4), `budget retreat` (2),
`amendment to the budget` (2), `adopt the budget` (2), `budget message` (2),
`draft budget` (1).

**`approved budget` is resolved.** §2.3 flagged it as a false positive to solve. At
span level it is 1% of matches and never the only match in a document, so it needs no
special handling — dropping `approv` from the proximity verbs would cost more than it
saves.

---

## 1. Why — what the tag flags today

`millage-budget` is `['millage', 'ad valorem', 'tax rate', 'budget', 'fiscal year']`.
Two of those five match any sentence that mentions money, which is why the tag is on
**59 of 59** flagged places and carries no information.

Measured over the committed sidecars:

| | meetings |
|---|---|
| Tagged both `millage-budget` and `local-taxes` | 396 |
| Tagged `millage-budget` only | 228 |
| Tagged `local-taxes` only | 97 |
| `millage-budget` total | 624 (552 with an agenda-action excerpt) |

Of the 228 that carry `millage-budget` alone — the ones no existing page can reach —
**209 matched on `budget` and 55 on `fiscal year`, against 5 on `millage`.** The tag
marks budget business, not millage.

### What that looks like in the documents

Real budget accountability, and the reason this deserves a page:

> **Banks, 2026-06-18** — "BANKS COUNTY BOARD OF COMMISSIONERS MEETING - PUBLIC
> HEARING FY2027 PROPOSED BUDGET"

> **Lumpkin, 2026-10-15** — "PUBLIC COMMENT ON PROPOSED 2027 BUDGET"

> **Gordon, 2026-06-16** — "Consideration of Resolution to adopt FY2027 Budget."

> **Walker, 2026-06-11** — "Chairwoman Teems will Call to Order the Budget Workshop
> … Department Presentations"

> **Effingham, 2026-03-03** — "Consideration to approve Resolution 026-006 to amend
> the Fiscal Year 2026 Budget"

And the noise — **221 of the 552 excerpts (40%) match no budget-decision pattern at
all**:

> **Bibb** — "Douglass Theatre roof replacement, in the amount of $194,200.00, to be
> paid from the facilities management budget" — a purchase

> **Walton** — "Contracts & Budgeted Purchases of $25,000 or Greater" — a standing
> consent-agenda line, on every meeting

> **Savannah** — "PUBLIC COMMENTS ARE ACCEPTED ONLY FOR HEARINGS (Alcohol, Public,
> Zoning, and Budget)" — page boilerplate, on every meeting

> **Newton** — "Award amount: $96,217.00 Budgeted: Yes" — a grant acceptance

> **Camden** — "could the change … adversely affect market values and/or tax rates of
> nearby properties" — a rezoning criteria checklist, caught by `tax rate`

> **Spalding** — "Capital Improvements Element Annual Update Report for Fiscal Year
> 2026" — a comprehensive-plan filing, which is land use

**The conclusion: the tag cannot become a page as it stands.** A narrower lexicon is
the whole of the work.

---

## 2. The lexicon problem, and why it needs one new mechanism

### 2.1 There is no exclusion mechanism, so `budget` cannot be a keyword

`TOPIC_RULES` matches substrings and `TOPIC_WORD_RULES` matches whole words
(`lib/meeting_topics.py`). Neither can express "budget but not budgeted", and
`budgeted` is the single largest false-positive source ("Budgeted: Yes", "budgeted
amount", "Budgeted Purchases").

**So the lexicon must be phrases, never the bare word.** That needs no new machinery
— `_find_kw` already matches a multi-word keyword across any whitespace run.

### 2.2 But fixed phrases miss the canonical Georgia phrasing

Georgia agendas almost always put the fiscal year *between* the verb and the noun:

- "proposed **FY 2026-2027** budget" (Meriwether)
- "public hearing (**FY27** budget)" (Houston)
- "worksession - **FY2027** budget" (Banks)
- "amend the **FY 2026** budget" (Bibb)
- "Resolution to adopt **FY2027** Budget" (Gordon)

No fixed phrase catches any of these. Measured on the excerpt corpus, a proximity
rule — a budget verb within ~45 characters of the word *budget*, no sentence break
between — **adds 72 meetings over the fixed phrases, +43% recall**.

| approach | meetings matched |
|---|---|
| Fixed phrases only | 167 (across 40 places) |
| Proximity rule only | 215 |
| Union | 239 |

**This is the one piece of new machinery the topic needs:** a third rule type beside
`TOPIC_RULES` and `TOPIC_WORD_RULES` for a small number of proximity patterns. It
must be added to the one taxonomy in `lib/meeting_topics.py`, and `classify`,
`matched_terms` and `_tag_matches` (which supplies excerpt offsets) all have to learn
it, or the topic gets badges with no quotes behind them.

### 2.3 Candidate lexicon

Phrases, measured on the excerpt corpus. Hit counts are a floor, not an estimate —
see §3.

| term | hits | | term | hits |
|---|---|---|---|---|
| `budget amendment` | 74 | | `budget presentation` | 9 |
| `budget resolution` | 22 | | `budget hearing` | 5 |
| `proposed budget` | 18 | | `budget adoption` | 4 |
| `budget work session` | 12 | | `budget public hearing` | 4 |
| `budget workshop` | 8 | | `amend the budget` | 3 |
| `capital budget` | 3 | | `budget transfer` | 3 |
| `operating budget` | 2 | | `budget calendar` | 2 |
| `budget ordinance` | 1 | | | |

Zero hits on this corpus, to be re-scored against full text before being dropped:
`draft budget`, `tentative budget`, `recommended budget`, `public hearing on the
budget`, `budget retreat`, `amendment to the budget`, `adopt the budget`, `adoption
of the budget`, `balanced budget`. Several of these are near-certainly real and are
missing only because of the FY-token problem in §2.2.

Proximity patterns, as a starting point:

```
(adopt|approv|amend|propos|consider)\w*  …≤45 chars, no sentence break…  budget
budget  …≤45 chars…  (adopt|approv|amend|hearing|public comment)\w*
```

**A known false positive to solve before shipping:** "included in the FY 2026-2027
**approved budget** in the amount of $80,990" (Covington) is a skid-steer purchase.
`approved budget` as a noun phrase names a funding source, not a decision. Either
drop `approv` from the proximity verbs or require a decision word elsewhere in the
item.

---

## 3. How this gets measured properly

**The numbers above are a biased floor and must not be quoted as the topic's size.**
They come from the 240-character excerpt each sidecar stores, and that window is
centred on the *old* match (`budget` / `fiscal year` / `millage`). A candidate phrase
only registers if it happens to fall inside that window, so real recall against full
text will be higher — and precision is unmeasured, because the corpus here is already
filtered to meetings the old tag matched.

The repo already owns the right tool, and the scope deliberately does not reinvent it:

```
1. populate once   python scripts/enrich_ocr_meetings.py --reclassify \
                          --text-cache .cache/meeting-text
2. score freely    python scripts/score_topic_lexicon.py --topic budget
```

`score_topic_lexicon.py` classifies every cached document with the lexicon as it
stands now and diffs it against the tags the committed sidecar recorded, printing
**WOULD NEWLY MATCH** (where false positives appear before they reach the site) and
**WOULD STOP MATCHING** (where recall is silently lost), with the quote that moved
each one. Phase 0 is not optional: the ALPR lexicon was tuned this way
(`docs/audits/2026-10-19-alpr-lexicon-corpus-findings.md`) and the budget lexicon is
a harder case, because its vocabulary is ordinary English rather than vendor names.

---

## 4. Phases

**Phase 0 — measure. DONE for 41 places including Savannah; see Phase 0 results
above.** Precision holds once the boilerplate exclusion is applied. Outstanding:
scan the 21 unmeasured places for their own repeating agenda boilerplate before
Phase 2 puts counts on cards.

**Phase 1 — the lexicon, the proximity mechanism and the exclusion mechanism. DONE.**
`budget` is in `TOPIC_RULES` with 26 phrases and no bare `budget` keyword;
`TOPIC_PROXIMITY_RULES` and `TOPIC_EXCLUDE_RULES` are the two new rule types, combined
in one place by `topic_spans()` so `classify`, `matched_terms` and the excerpt finder
cannot disagree. `millage-budget` is retired and `tax rate` moved to `local-taxes`.

Verified against the 975-document corpus: the shipped engine reproduces the Phase 0
measurement exactly — **287 documents across 39 places, Savannah 3 of 40** — and
Savannah's excerpts quote real budget items rather than the boilerplate. Diffing the
old module against the new over every corpus document, the change **adds one document
to `local-taxes` (`hall/1901`, a hotel-motel excise rate — the `tax rate` move) and
removes nothing from any existing topic.**

`scripts/test_meeting_topics_budget.py` pins the decisions that must fire, the money
plumbing that must not, and Savannah's boilerplate, including the check that the
boilerplate still trips a proximity rule *before* the exclusion — without it the
exclusion test would pass even if proximity had silently died. Retire `millage-budget` (§5). Tests: proximity matching, the
`budgeted` exclusion, the FY-token cases, and a regression pinning that each noise
sample quoted in §1 does **not** match.

**Phase 2 — the surfaces.** `budget` in `_data/topics.yml` with blurb and definition,
`TOPICS` in `generate_topic_mentions.py`, the `/local/topics/budgets/` index, the
per-place section, and `budgetItems` in `build_summary` + `budgetCount` in
`flag_entry`. The topic then ranks on the hub card like any other, and the
millage special case in `local.html` is deleted.

**Phase 3 — explainer, optional.** A `/local-budgets/` page on how a Georgia local
budget is adopted, mirroring `/property-tax/`. Budget pairs naturally with the millage
work already shipped: millage is the rate, the budget is what it pays for.

**Phase 4 — publish, deferred by decision 2.** A fifth topic feed in
`publish_ga_local_government.py`. Not before the lexicon has run clean for several
cycles.

---

## 5. Retiring `millage-budget` — the blast radius

Small, and fully enumerated:

| file | what changes |
|---|---|
| `scripts/lib/meeting_topics.py` | `TOPIC_RULES['millage-budget']` removed; `MILLAGE_TERMS` removed; `millage_meetings` / `millageCitations` in `build_summary` become `budget_items` / `budgetCitations`; `millageCount` in `flag_entry` becomes `budgetCount`. |
| `local.html` | `budget` joins `TOPIC_PILLS` and ranks normally. **The whole "millage is excluded from ranking" special case goes away** — that exclusion existed only because the tag was too broad to rank. |
| `scripts/test_flag_entry_counts.py` | Pins `budget` and `fiscal year` as millage-budget lexicon terms and asserts millage outscores land use. Both assertions are about the broad tag and are replaced by the Phase 1 precision tests. |
| `scripts/test_meeting_topics_local_taxes.py` | Carries a millage-budget regression; re-point at `local-taxes`, which keeps the `millage` keyword. |
| `scripts/test_pdf_hybrid_and_regression.py` | One assertion on the tag. |
| `docs/LOCAL-EXPANSION-SCOPE.md` | The hard-won fact about millage never being ranked is superseded by this document. |

**Nothing else.** `millage-budget` has no entry in `_data/topics.yml`, no page, no
pill, no place-page section, and is not in the sibling publisher's `TOPICS`. It was
measured earlier in this work and confirmed unread, which is why its sourced-items
list was removed in `c411925`.

**No millage content is lost.** `millage` and `ad valorem` are in the `local-taxes`
lexicon too, so those meetings already carry the `local-taxes` tag and reach the
Local taxes & referenda page, whose definition names millage rates explicitly.

---

## 6. Risks

- **Ordinary-English vocabulary.** Every other topic keys on proper nouns (Flock,
  Verkada) or terms of art (SPLOST, rezoning). "Budget" is a word every agenda uses
  for every purpose. This topic has a materially worse precision ceiling than the
  other four, and Phase 0 exists to find out where that ceiling is.
- **A badge marks discussion, not action** — already the standing caveat on
  `/local/`, and it matters more here. "Paid from the parks budget" is not budget
  business, and some of that will get through.
- **Recurring boilerplate inflates counts.** Savannah's hearing-list header and
  Walton's standing consent line fire on *every* meeting. With counts now on the hub
  cards, a place whose agenda template contains the word would rank high on nothing.
  Worth an explicit test.
- **The proximity mechanism is new taxonomy machinery**, and the taxonomy is shared
  by three enrichers. It must land with tests before any lexicon depends on it.

---

## 7. Deliberately not in scope

- **A budget-season tracker** — which counties are in budget season now, which have
  adopted. Georgia requires an advertised public hearing before a local budget is
  adopted, which makes the cycle predictable, and this would be the first
  *prospective* thing on `/local/` rather than another archive. Genuinely the
  stronger idea, and the reason it is deferred is that it needs the lexicon to be
  trustworthy first. **Revisit after Phase 2.**
  *The statutory detail (O.C.G.A. § 36-81-5 / § 36-81-6 — preparation, public
  availability, advertised hearing, adoption before the fiscal year) is recorded here
  from memory and is **unverified**. Verify against the Code before any of it reaches
  a page, per the standard set by `/property-tax/`.*
- **School-district budgets and ESPLOST.** A board of education adopts its own budget
  and its own millage. That belongs with the school-board work in the parent scope,
  not here.
- **Actual dollar figures.** Extracting budget totals is a different and much harder
  problem than detecting that a budget was discussed. Not now.

---

## 8. Sources

Every figure in this document was measured on the committed enriched sidecars
(`assets/data/local-*-meetings-enriched.json`, generated 2026-11-02) on 2026-11-03.
The quotes are the sidecars' own `topicExcerpts`, which are captured from the poppler
text layer only, never OCR.
