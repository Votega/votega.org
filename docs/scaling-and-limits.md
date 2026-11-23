# Scaling & GitHub limits

Moved out of `CLAUDE.md` (verbatim, no edits) so the always-loaded file stays short. `CLAUDE.md` points here.


Measured from a clean `build_entity_pages.py` + `jekyll build` on `main`:
built `_site` = **312 MB**, **3,151 files**, **1,484 HTML pages** (1,411 generated
entity pages), **27 s** Jekyll build.

**The 2026-09 baseline that stood here was ~111 MB and its figures were ~3x low,
so re-measure before trusting any projection in this section.** It also carried
one assumption that is now false: it said bandwidth risk came "not from HTML
(tiny)". HTML is now **74% of the site**.

Composition: **HTML 231 MB (74%)** | JSON 48 MB | images + PDF 26 MB.

Where the caps are, and how close we are:
- **Published site size — 1 GB hard. At 312 MB (31%)**, not the "~11%" previously
  recorded. Still comfortable, but now roughly one election cycle of candidate and
  race pages from half the cap — and those are the two heaviest directories.
- **Single file — 100 MB.** Largest is `assets/data/ga-bills.json` at 6.8 MB. Fine.
- **Build time / Actions minutes.** Deploy is via GitHub Actions
  (`actions/jekyll-build-pages` + `deploy-pages`), so the legacy "10 builds/hour"
  Pages soft limit does not apply; public repo => unlimited minutes. 27 s. Fine.
- **`.git` — 98 MB** against GitHub's ~5 GB warning. Fine; the delta-compression
  reasoning from the previous revision still holds.

### Page weight is the driver now, not page count

| Directory | Pages | HTML | Avg/page |
|---|---|---|---|
| `candidates` | 700 | 114.5 MB | **167 KB** |
| `races` | 363 | 52.6 MB | **148 KB** |
| `ga-legislators` | 236 | 51.2 MB | **222 KB** |
| `us-congress` | 16 | 2.9 MB | 188 KB |
| `local` | 68 | 3.9 MB | **59 KB** |
| `federal-executives` | 19 | 1.1 MB | 64 KB |
| `justices` | 9 | 0.3 MB | 44 KB |

A new section of pages is cheap; a heavy template is expensive. For scale: adding
a sub-page to all 68 `/local/` pages costs ~4 MB, while trimming 50 KB off the
legislator template recovers ~12 MB.

### REVISIT (live item): ~85% of a heavy entity page is ONE inline `<script>`

Measured on a 219.5 KB legislator page:

| | |
|---|---|
| inline `<script>` | **187.5 KB (85%)** — only 2.3 KB of it JSON-LD |
| inline `<style>` | 13.7 KB (6%) |
| markup + text | 18.2 KB (8%) |

It is a **single 177.7 KB block** of application JavaScript — it opens
`const DATA_URL = ... 'assets/data/ga-members.json'` and carries an embedded
county-to-district lookup table — inlined into every one of the 236 pages.
Candidate pages have the same shape: one 126.5 KB block, 83% of a 167 KB page.

**`/local/` pages already do this correctly.** They load
`/assets/scripts/local-meetings.js`, `local-subjects.js` and `html-escape.js` as
external files, which is why they are 59 KB rather than 200.

Moving those two blocks to `assets/scripts/*.js` would:
1. cut roughly **130 MB from a 312 MB site** (700 x 127 KB + 236 x 178 KB),
   taking it from 31% of the hard cap to about 18%;
2. make the code **cacheable across pages** — today it is re-downloaded in full on
   every page navigation, which is also the outstanding **Core Web Vitals** item.

Not yet investigated, and it decides whether this is an afternoon or a refactor:
**is either block genuinely per-page (templated with that entity's data) or
identical across pages?** If identical, this is a move. If templated, the fix is
to split the static code out and leave only the small per-page data inline.
Answer that first.

### First ceilings we would actually hit, in order

1. **Site size**, if the inline script above is not addressed before the next
   candidate cohort lands. This has overtaken bandwidth as the nearest ceiling.
2. **Bandwidth — 100 GB/month soft.** Better than previously recorded: the
   `ga-member-votes.json` monolith named as the worst offender **is no longer
   shipped at all**, having been sliced into `assets/data/ga-votes/`,
   `federal-votes/`, `ga-sponsorship/` and `federal-sponsorship/`. The remaining
   large client-fetched files are `ga-bills.json` (6.8 MB) and
   `current-members.json` (1.4 MB); slicing the former the same way is the next
   mitigation if needed. GitHub warns before throttling.
3. **Git history bloat.** `.git` is 98 MB; revisit only if it trends toward the
   ~5 GB warning.

Bottom line: no immediate risk, but the previous "not a concern" verdict rested on
a stale measurement. **Re-measure after any large page-count or template change,
and treat the inline-script finding as the live item.**
