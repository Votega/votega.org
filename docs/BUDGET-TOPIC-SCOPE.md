# Budgets as a `/local/` topic — scope

**Status:** scoped, not started.
**Scoped:** 2026-11-03 · **Scope owner:** Justin Mays
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

**Phase 0 — measure.** Populate the text cache, score the candidate lexicon, read
every WOULD NEWLY MATCH quote. Tune until precision holds on a hand-read sample.
Nothing ships. *This phase decides whether the rest is worth doing.*

**Phase 1 — the lexicon and the proximity mechanism.** Add `budget` to `TOPIC_RULES`
with the phrases, add the proximity rule type, teach `classify`, `matched_terms` and
`_tag_matches` about it. Retire `millage-budget` (§5). Tests: proximity matching, the
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
