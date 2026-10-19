# What the meeting-text corpus taught us about the ALPR lexicon

Findings from the first measured pass over the local-government agenda corpus
(1,220 documents, 38 places, 70.4 MB of text, built 2026-10-19 by
`.github/workflows/populate-meeting-text-cache.yml`).

Most of the *reasoning* behind individual keywords lives in comments beside them in
`scripts/lib/meeting_topics.py`. This file records the things that are **expensive
to rediscover**: the empirical shape of the corpus, the traps that produced
plausible-but-wrong conclusions, and the methodology that settled them. Read it
before widening or narrowing any topic rule.

---

## 1. The measurement loop (use it; do not guess)

The enrichers discard text after classifying — right for the repo, fatal for
iteration, because a keyword could not be checked against documents we had already
read. `scripts/lib/text_cache.py` keeps that text on disk and out of git.

```
populate once (CI, ~800 fetches)   .github/workflows/populate-meeting-text-cache.yml
score freely (local, offline)      python scripts/score_topic_lexicon.py --topic alpr
re-tag history (local, offline)    enrich_*.py --reclassify --from-text-cache
```

The scorer's value is the **diff against the committed sidecars**: `WOULD NEWLY
MATCH` is where false positives surface before they reach the site, `WOULD STOP
MATCHING` is where recall is being lost. A lexicon edit should be measured, not
argued about.

Three things about this loop that cost time to learn:

- **The populate workflow must restore the committed sidecars before scoring.** The
  enrichers run with `--reclassify`, which rewrites the sidecars in the runner's
  checkout; scoring then compares the corpus against tags just regenerated from
  that same corpus with that same lexicon. The first run duly reported 0 newly
  matching and 0 stopped across 1,220 documents — agreement by construction,
  carrying no information. Fixed with a `git checkout -- assets/data` step.
- **`.gov` egress is blocked in the agent sandbox.** CI is the measurement surface:
  the populate job prints a full scoring report to its log, which is readable
  without downloading anything. The artifact (≈11 MB zip, 15 MB on disk) is only
  needed for interactive digging.
- **Corpus coverage is not uniform.** See §6 — the Granicus places are
  under-represented, so counts there understate reality.

### The asymmetry that decides when a change reaches the site

- **Removals take effect on regeneration.** `generate_topic_mentions` intersects
  each meeting's committed `matchedTerms` with `ALPR_TERMS`, so narrowing the
  lexicon narrows the output immediately.
- **Additions do not.** `matchedTerms` is committed data, so a new keyword only
  matches after meetings are re-classified.

A lexicon addition that is never re-tagged is invisible. With the corpus the
re-tag is free and offline; without it, it costs ~800 downloads.

---

## 2. Georgia agendas do not use the national ALPR vocabulary

The single most useful finding, and it inverts the obvious expansion strategy.

Across all 1,220 documents, **every spelled-out plate phrase matched nothing**:
`license plate reader`, `license plate recognition`, `automated/automatic license
plate`, `plate reader`, `plate recognition`, `license-plate`, `license plate
camera`, `lpr system`, `plate scanner`, `plate capture`, `plate reading`,
`plate-reader`, `number plate recognition`, `tag recognition` — all zero.

What does carry documents: **vendor names** (`flock` alone covered 18), and the
Georgia vernacular **`tag reader`**. Georgia says *tag* where the national
vocabulary says *plate*.

Consequences:

- Expanding by inventing euphemisms is low-yield. 26 candidate phrases measured at
  **zero documents** (`flockos`, `aerodome`, `vehicle fingerprint`, `hotlist`,
  `public safety camera`, `camera registry`, `video analytics`, `safe city`,
  `safety as a service`, `vehicle detection system`, `gunfire alert`, …). They are
  listed in `TOPIC_RULES['alpr']`'s comments so the same guesses are not re-made.
- Vendor coverage is where the recall is.
- `ALPR_HIGH_TERMS`' plate half contributes nothing today; the tier is effectively
  vendor- and capability-driven.

### The bare acronym `alpr` appears as a word in ZERO of 1,220 documents

Its six substring occurrences are all **inside other words**: `mALPRactice`
(malpractice insurance), `ALPRazolam` (a controlled-substances schedule), and the
URL `ricefinancialproducts.com`. The `\balpr\b` word-boundary rule — originally
motivated by `AppraisalPro` — is doing real work. A substring rule would flag
opioid schedules and insurance clauses as surveillance.

---

## 3. Two keyword traps that look like hits

Both produced confident-but-wrong conclusions until the text was read.

**NDAA §889 prohibition boilerplate.** `hikvision` and `dahua` matched *only*
contract-packet language certifying the government does **not** buy that equipment
("shall not procure equipment produced by … Hangzhou Hikvision … or Dahua
Technology Company"). The keyword matched the exact opposite of a purchase. Both
removed. This is the one case a recall-favoured policy does *not* rescue: there was
no true positive to trade for. Revisit only if a place is seen debating **removal**
of such gear, which would be a genuine policy item.

**Reseller / facility-security context.** `avigilon` matched only Comcast-resold
"Eagle Eye Avigilon video management hardware" for the **Douglas County landfill**.
It was removed on that evidence, then deliberately **restored** — Avigilon ships LPR
analytics and sits in the Motorola portfolio alongside Vigilant, and the publisher's
policy (§4) is to tolerate that noise. The lesson is not "exclude Avigilon"; it is
that a brand name tells you a vendor was paid and leaves you to assume what for,
whereas a self-describing phrase ("video surveillance equipment") is evidence on its
own. That distinction is why bare `axon enterprise` carries **no vendor label** and
so stays medium confidence: of the 12 documents it adds, 2 are plainly tasers and
~5 are unspecified umbrella agreements.

General-purpose VMS brands that ship no plate reading (**Milestone, Eagle Eye
Networks, Spot AI**) stay out and are pinned quiet. Bare `axon` stays out at 32
documents — far too broad.

---

## 4. Standing policy decisions (publisher's calls, not inferences)

Recorded so they are not re-litigated by the next agent reading the code:

- **Recall-favoured.** False positives are tolerated to avoid missing true ones. A
  missed ALPR contract is a story the public never learns; a stray facility-camera
  item is noise a reader sees through in one click to the source. The bar an
  ALPR-capable vendor must clear is "this brand sells the capability", not "every
  match in today's corpus was clean".
- **Scope**: cameras, plate readers, drones, gunshot detection — plus police
  **body-worn, in-car and fleet** cameras (added 2026-10; in-car "fleet" cameras
  often read plates themselves). Facility surveillance is **in** scope.
- **Out of scope**: phone forensics (Cellebrite, GrayKey, Magnet Forensics), phone
  interception (cell-site simulators, IMSI catchers), data-broker/fusion platforms
  (Peregrine, Palantir, Babel Street, Fog), and records analytics with no sensor
  (`predictive policing`). Each was *removed* rather than never added — re-adding
  any is a scope decision about what the page is for, and fails a guard test first.
- **Broad matching, selective publishing.** Rather than a `confidence: "low"` tier
  in the published data, the topic page **ranks**: jurisdictions with a
  high-confidence meeting render normally, keyword-only ones drop into a collapsed
  "possible mentions" section, fully sourced. This is what lets the lexicon keep
  widening without degrading what a resident sees first. `ALPR_HIGH_TERMS` is the
  dividing line and must be kept current as scope widens — when body cams and
  drones were added, the tier was not, and Atlanta's forty-million-dollar
  fleet-and-body-camera amendment sorted into "possible". Backwards.

---

## 5. Multi-word keywords were silently broken across line breaks

PDF text layers break lines mid-phrase and carry the indentation along:

```
'... purchase of Skydio Drone as First\n                Responder ...'
```

a real Gwinnett item the rule already had a keyword for. Fixed by matching
multi-word keywords with `\s+` between words (`_PHRASE_RE` in `meeting_topics.py`),
done as a regex over the original text rather than by normalising it first, because
`topic_excerpts` needs offsets valid in the text it **quotes**.

Recovered **11 documents across five topics** (comprehensive-plan +4,
special-land-use +3, millage-budget +2, alpr +1, data-center +1).

**End-of-line hyphenation (`read-\ner`) does NOT occur** — collapsing it recovered
zero documents across the whole corpus. Do not build it.

---

## 6. Extraction: two ways to silently read less of a document

**Hybrid PDFs.** `extract_text` applied one document-level floor (200 characters)
and accepted the PDF whole. A packet whose body is scanned images but which carries
one machine-generated page clears that, so the scanned body is never OCR'd — a
Paulding agenda read 7,352 characters where OCR of the same PDF had found 11,884,
and the rezoning and variance items lived only in the skipped part. Now also
decided **per page** (`mostly_empty_pages`).

**Granicus serves two different documents at one URL.** Barrow answers some
meetings with a JS shell that strips to tens of thousands of characters of markup
residue, and others with the real agenda:

| Barrow stored `html` records | chars | matched |
| --- | --- | --- |
| 14 records | 29k–50k | **nothing** — not even `contract` or `budget` |
| 9 records | under 2,600 | real tags |

So for those meetings the **shorter** PDF reading is the real agenda. This is the
trap: a "the re-read got much shorter, keep the old one" guard keyed on **length**
would have preserved the garbage and discarded the fix. `text_regressed` therefore
fires only when a substantially shorter reading **also drops a finding** the
previous one supported. Losing characters is not the harm; losing a sourced tag is.

Per-place representation (one 40-meeting window): barrow mixed 16 html / 24 pdf;
catoosa and spalding always pdf; cherokee always html. Because the corpus caught
Barrow's thin PDFs, **Granicus places are under-represented in it** and their counts
understate reality.

Still open: nothing *detects* a JS-shell response at fetch time. HTML that strips
to tens of thousands of characters yet matches no agenda vocabulary is not an
agenda, and could be a visible failure rather than a quiet one.

---

## 7. Legistar is deliberately different

`enrich_legistar_meetings.py` has a `--text-cache` write path but **no
`--from-text-cache`**, and that is not an oversight:

- it keeps no incremental cache and re-reads every event from a cheap structured
  API on each run, so a taxonomy change already re-tags those places for free;
- it classifies each agenda **item** separately, which is what makes per-item topic
  counts, land-use records and roll-call votes possible. Re-classifying a joined
  blob would flatten all three.

Practical consequence: an offline re-tag does not cover `dekalb`, `fulton`,
`muscogee`. They keep the tags from their last networked run, so findings in their
documents can sit in the corpus without appearing on the site until
`update-local-government.yml` runs.

---

## 8. Result of the first measured pass

| | before | after |
| --- | --- | --- |
| ALPR mentions | 26 | 74 |
| ALPR jurisdictions | 9 | 22 |
| Distinct vendors | 4 | 7 |
| Data-center mentions | 101 | 131 |
| Land-use mentions | 494 | 712 |

Thirteen jurisdictions appeared for the first time. Nothing was lost.
