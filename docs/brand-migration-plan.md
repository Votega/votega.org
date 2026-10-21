# Brand migration plan: Georgia Peach & Clay

Status: draft, 2026-10-21. Branch: `brand-identity-assets`.

Plan for moving the live site from the old identity (navy and civic blue, Lora and Open Sans, red-and-blue logo) to the new one described in `assets/img/brand/style-guide-peach.html` (and `.pdf`). The brand ships **all at once**: every step below is done locally on a branch and nothing is merged to `main` until the whole set is ready, so visitors never see a half-migrated site.

`docs/` is excluded from the Jekyll build (`_config.yml`), so this file is not published.

## 1. How the effort was measured

Every page, layout, include, stylesheet and script was scanned (heuristic text counts, not visual diffs):

- hard-coded hex colors, split into blue, red, other chromatic and neutral, plus a list of old brand blues (`#1a56a8`, `#008aff`, `#0085a1`, `#1a1a2e`, `#4f6edb`, `#e8f0fe`, `#2471a3`, `#3498db`, and a few others)
- inline `style=` attributes (including those inside JS template strings), `<style>` lines, `@media` queries, `font-family` declarations, emoji

Score = blue x2 + red x2 + other x1 + neutral x0.25 + old-brand blue x1.5 + emoji x3 + inline style x0.5 + media x1.5 + font-family x1 + style lines x0.05. Dependencies were traced (layout, `css:` front matter, `{% include %}` chains, `<script src>`) so shared files are charged once, not to every page that loads them.

**What the score cannot see:** `rgb()` and named colors, theme-variable use, and the judgment needed where a page mixes **party** blue and red (which stay) with **UI** blue (which becomes clay). That judgment is the real cost on the majority tracker, congress trades, results, race and ga-bills pages.

## 2. Phase 0: foundation (do once, first)

These move most of the site because the theme is driven by a handful of values.

| Change | File | Effect |
|---|---|---|
| Theme color tokens: `page-col`, `text-col`, `link-col`, `hover-col`, `navbar-col`, `navbar-text-col`, `navbar-border-col`, `footer-col`, `footer-text-col`, `footer-link-col`, `footer-hover-col`; `mobile-theme-col` is commented out today | `_config.yml` (lines ~180-200) | Body text, links, navbar, footer on every page |
| `--body-font` / `--header-font` to Public Sans | `assets/css/beautifuljekyll.css` (variables near the top; 54 hex, 22 media queries elsewhere in the file) | Type on every page |
| Replace the Lora and Open Sans Google Fonts links with Public Sans | `_layouts/base.html` | Font loading |
| Introduce a shared `assets/css/tokens.css` (clay, deep clay, tint, line, pine, party, semantic, Independent violet, Vacant gray) and load it from `_includes/head.html` | new + `head.html` | Single source for the brand values; later phases delete local colors in favor of these |
| Wire the favicon set and touch icons | `_includes/head.html` | New favicon; files already in `assets/img/brand/favicon/` |
| Add Public Sans (SIL OFL) | `THIRD-PARTY-NOTICES.md` | License notice |
| Regenerate the default share card | `tools/og-image/og-default.html`, `assets/img/og-default.png` | Still navy and blue today |
| Swap `logo.png` for the new horizontal lockup | `_config.yml` (`avatar`, `title-img`), `assets/img/logo.png` | Navbar logo; files are in `assets/img/brand/logo/` |

Leave alone: `bootstrap-social.css` (273 hex, social-button vendor colors) and `pygment_highlights.css` (code highlighting).

New first-party CSS and JS tags need the `?v={{ site.time | date: '%s' }}` suffix (see CLAUDE.md, Coding Patterns). Page CSS added through `css:` front matter is not cache-busted today (`index.html` has the same gap); decide whether to fix that in `head.html` as part of this phase.

## 3. Phase 1: verify-only pages

No custom colors, or only the shared cards stylesheet. After Phase 0, check each at 375 / 768 / 1280 px and move on.

| Page | Score | Note |
|---|---|---|
| `my-representatives.html`, `tags.html` | 0 | |
| `flock-safety.md`, `flock-covington.md` | 0.5 | |
| `results-latest.html` | 1.2 | Includes the result-status include |
| `about.md` | 1.5 | Add the "not affiliated" wording check (guide p.21) |
| `404.html` | 2.0 | |
| `about-the-data.md` | 5.0 | |
| `index.html` | 6.0 | Depends on `cards.css` |
| `search.html` | 6.5 | |

## 4. Phase 2: shared components

Do these before the pages that use them.

| Component | Score | Used by | Work |
|---|---|---|---|
| `assets/css/cards.css` | 72.8 (40 hex, 8 old blues) | `index`, `find-my-reps`, `elections-hub` | Clay Line border, 10px radius, Clay Tint hover; remove blues |
| `_layouts/election_results.html` | 58.6 (12 blue, 2 red, 9 old blues) | 6 results stubs: general, general runoff, primary, primary runoff, special, special runoff | Replace `--rep #c0392b` and `--dem #2471a3` with the guide's party colors; tabs and filters to clay; keep party color only on the party badge, card border and party bar; status notices per guide p.25 |
| `_includes/result-status.css` | 19.4 | `results`, `ga-ballot-measures`, race template, results layout | Unofficial = amber, Certified = pine, Upcoming = gray |
| `assets/css/topic-index.css` | 48.5 | `/local/topics/*` (3 pages) | Colors only |
| `assets/scripts/campaign-finance.js` | 24.0 | 4 entity templates | JS-built markup colors |
| `assets/scripts/votega-votes-table.js`, `assets/css/votes-table.css` | 12.5 / 8.8 | legislator templates | Party colors stay |
| `assets/scripts/entity-news.js` | 15.5 | 3 entity templates | Blues to clay |

## 5. Phase 3: pages, least to most work

Own score includes exclusive dependencies. Pages already styled in the stash (the "trial pages WIP" stash: Public Sans and monospace stack for the two trial pages) are marked.

### Tier 2: light (10-33)

| Page | Score | Notes |
|---|---|---|
| `results.html` | 10.5 | Uses `result-status.css` |
| `executive-branch.html` | 20.1 | 151 `<style>` lines, few colors |
| `elections-hub.html` | 21.9 | **5 emoji icons** to Font Awesome: `list-check`, `check-to-slot`, `calendar-days` (guide p.12-13, p.25) |
| `ga-news.html` | 28.6 | |
| `sample-ballot.html` | 29.5 | |
| `ga-executive.html` | 31.4 | |
| `open-data.html` | 33.1 | |

### Tier 3: moderate (48-66)

| Page | Score | Notes |
|---|---|---|
| `federal-reps.html` | 48.5 | |
| `supreme-court.html` | 49.5 | 21 inline styles |
| `candidates.html` | 52.7 | |
| `justice` template (`_includes/entity/justice.html`) | 53.0 | 9 generated pages |
| `find-my-reps.html` | 53.8 | Shares `cards.css` |
| `ga-party-unity.html` | 54.6 | Party colors vs UI blue |
| `ga-voter-access.html` | 56.0 | |
| `ga-state-reps.html` | 60.3 | **Trial page, in the stash.** Move its overrides into tokens |
| `ga-ballot-measures.html` | 63.1 | Uses `result-status.css` |
| `ga-executive-orders.html` | 66.3 | **Trial page, in the stash.** Category dots are set in JS (`CATEGORY_DOT`, e.g. Appointment `#1a56a8`) |

### Tier 4: heavy (78-115)

| Page | Score | Notes |
|---|---|---|
| `elections.html` | 77.6 | 944 lines |
| `federal-executive` template | 87.4 | 20 generated pages, 283 `<style>` lines |
| `local.html` | 88.5 | **12 emoji icons** |
| `ga-congress-trades.html` | 95.3 | Party colors vs UI blue |
| `ga-majority-tracker.html` | 115.2 | 30 inline styles; adopt Independent violet and Vacant gray (guide p.10); party seats |

### Tier 5: largest (117-179), one template at a time

| Template | Score | Generated pages | Notes |
|---|---|---|---|
| `candidate.html` | 117.5 | 698 | Finance panel colors via `campaign-finance.js` |
| `place.html` | 126.8 | 51 | 14 old blues, 152 `<style>` lines; land-use green and ALPR red watch blocks (decide whether to keep as semantic) |
| `race.html` | 130.1 (+ `results-contest.js` 9.0) | 363 | Candidate cards, finance comparison tab |
| `ga-bills.html` | 155.6 | 1 (large) | 1,333 lines, 15 old blues |
| `federal-legislator.html` | 156.9 | 16 | 47 inline styles |
| `ga-legislator.html` | 179.2 | 236 | 61 inline styles, 345 `<style>` lines; Independent and Vacant badges |

## 6. Cross-cutting checklist (applies to every phase)

- [ ] Replace UI blue (`#1a56a8`, `#008aff`, `#0085a1`) with clay tokens; keep party blue and red for party data only (guide p.10)
- [ ] Party label wording: "Democratic", "Republican", "Independent"; Vacant uses gray (guide p.16)
- [ ] Emoji to Font Awesome (guide p.12-13)
- [ ] Empty / unavailable / known-gap messages standardized (amber and gray, not red `#c00`; guide p.17)
- [ ] Stray non-party accent `#1a56a8` for members who are neither Democratic nor Republican (`_includes/entity/ga-legislator.html`, ~line 1678)
- [ ] Breakpoints toward 600 / 768 / 1200 as each page is touched (guide p.22)
- [ ] Monospace stack `ui-monospace, 'SF Mono', Consolas, 'Liberation Mono', monospace` for IDs and order numbers
- [ ] Verify at 375 / 768 / 1280 px, check contrast ratios in the guide, check keyboard focus ring
- [ ] Verify entity pages on clean URLs (`/races/<slug>/`), not only `/race.html?id=` (see CLAUDE.md on `getBasePath()`)

## 7. Release

1. Complete phases 0-3 on one branch (or a chain of branches merged into one integration branch); nothing goes to `main` in between.
2. Final pass: full local build, spot-check the 6 entity types and one page per tier at three widths.
3. Merge once. After the deploy, purge the Cloudflare cache (JS and CSS are cached 4 hours at the edge; see the project notes) and check a returning-visitor view.
4. Regenerate `assets/img/og-default.png` as part of the same change so shared links match the site.

## 8. Open decisions that gate the work

Tracked on the last page of the style guide (page 26). The ones that block specific steps:

- Danger Red equals Rep. Active (`#b91c1c`): decide before standardizing error states
- A lighter "peach" token, and whether to keep the reversed-logo light clay `#e9a173`
- Whether to ship a web app manifest with the 192/512 and maskable icons
- Dark mode: yes or no (affects the token structure)
- Land-use and ALPR "watch" colors on place pages: keep as semantic or fold into the palette

## 9. Method notes

Counts were produced by a one-off script over the working tree (not committed). Re-run a scan after each phase to see the remaining old-brand colors: search for the old blues listed in section 1, for `#c00`, `#777` and `#666` (ad hoc grays in state messages), and for emoji in page and include files.
