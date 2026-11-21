# GA legislator page permanence: design

Status: **Draft for review** (2026-11-13). Supersedes the build approach of D3 in `docs/ga-biennium-rollover-decisions.md` and reverses D4; see "Changes to the rollover decisions" below.

## Why

Since 2026-11-12, Georgia Commons links every bill sponsor to our legislator page (`votegaUrl`). Its bill pages are permanent, so every link is permanent too, and the exposure, traffic and SEO they bring are worth keeping. Two things break them today:

1. **The January 2027 rollover.** Legislator pages are built at deploy from the live roster. `update-ga-members --new-biennium` drops non-returning members, so their pages stop being built and their URLs 404. The slice builders also delete their per-member vote and sponsorship files.
2. **Members who left mid-biennium already have no page.** `NO_PAGE_STATUSES` in `scripts/lib/ga_legislator_pages.py` gives the 11 resigned members a null `votegaUrl`, so Georgia Commons has no link for them.

## The rule

**A legislator page URL, once published, never 404s.** It keeps serving that person's page, or redirects to that person's current URL. Every person gets one page, keyed on `legisGaGovId`, covering every biennium for which we hold data.

## Decisions (agreed 2026-11-12/13)

| | Decision |
|---|---|
| Former members | A full page, with record, votes and sponsorship from frozen data, plus a "Former member" banner. Not a thin stub. |
| Prior bienniums | One page per person with a **biennium switch**, built now (before 2027-01-11) so re-elected members and chamber movers keep their 2025-26 record. |
| Indexing | Former-member pages are **indexed** and in the sitemap. They're hidden from default site search and from current-member listings, and reachable from a Former Legislators directory. |
| The 11 resigned members | They get pages **now**, as the first use of the mechanism. |
| Scope | 2025-26 is the first frozen biennium. Earlier bienniums are possible later as a data change, not a code change. |

## Verified facts this relies on

- **`legisGaGovId` (legis.ga.gov `MemberId`) is person-level and survives chamber moves.** This was checked on 2026-11-13 against `GetMembersBySession` for 2019_20 through 2025_26 (367 members):
  - All 7 chamber movers kept one id, both ways: McLaurin, Moore, Setzler, Watson and Williams went House → Senate, and Au went Senate → House.
  - Moore kept his across a gap in service.
  - No name appears under two ids.
  - The per-term `legId` changes on a move, so nothing may key on it.
- No `legisGaGovId` appears twice in the 2025-26 roster, so no member changed chambers mid-biennium.
- Per-member data costs ~35 KB: `ga-votes/` is 3.6 MB and `ga-sponsorship/` 4.9 MB, across ~246 members.

## Data

### 1. Page ledger: `assets/data/ga-legislator-ledger.json` (committed, append-only)

```json
{
  "metadata": { "generatedAt": "...", "count": 258 },
  "people": {
    "4942": {
      "rosterId": "ocd-person/...",
      "urls": ["/ga-legislators/josh-mclaurin-senate-14/", "/ga-legislators/josh-mclaurin-house-51/"],
      "bienniums": ["2025_26"]
    }
  }
}
```

- `urls`: every permalink ever published for that person, newest first. The first entry is the live URL. The rest redirect.
- `bienniums`: every biennium with frozen data under `ga-bienniums/`.
- **Writer:** the roster producer (`generate_ga_members_soap.py`), which already computes `votegaUrl` through `assign_votega_urls`. If a member's computed URL is not already first in their list, it's prepended. Nothing is ever removed. The page builder runs at deploy and commits nothing, so it can only read the ledger.
- `rosterId` is recorded because `ga-member-votes` and the vote slices key on it; `legisGaGovId` is the key everywhere else.

### 2. Frozen bienniums: `assets/data/ga-bienniums/<tag>/` (committed, written once)

```
ga-bienniums/2025_26/
  ga-members.json            # roster records as frozen, plus metadata.biennium (as built: file names mirror the live files)
  ga-votes-index.json        # copy of the vote index the slices resolve against
  ga-votes/<slug>.json       # copy of each member's vote slice
  ga-sponsorship-index.json
  ga-sponsorship/<legisGaGovId>.json
  curated-ga-bill-votes.json # --all only
  # party-unity.json is NOT frozen (as built): the page computes party unity client-side from the vote slice.
```

- The live slice builders never write here. That's the point: they clear their own output directories.
- **Writer:** a new `scripts/freeze_ga_biennium.py`:
  - `--members <legisGaGovId,...>` freezes named members now. Used for the 11 resigned members, and later for any mid-term departure.
  - `--all` is the final freeze before the session bump (Timing, below).
  - It refuses to freeze a member with no vote slice (a member who served but cast no recorded vote is listed with a note, not skipped silently).
  - It refuses to overwrite a different existing file without `--overwrite`.
  - Re-running it is idempotent.
- **Size:** about 0.4 MB now for the 11, and about 8.5 MB at each final freeze. Written once and never rewritten, so `.git` grows by about that much per biennium.

## Pages

### Which pages are built

`build_ga_legislators` builds one page per ledger person:

- **Sitting** (in the live roster): as today, with the current biennium from the live files.
- **Former** (in the ledger, not in the live roster): built from their most recent frozen `members.json` record.
- **Every non-first ledger URL** becomes a redirect page (`redirect_to`, via jekyll-redirect-from) to the first URL. If the old URL belongs to a different biennium than the person's current record, the redirect carries `?biennium=<YYYY-YYYY>`, so a reader arriving from a 2025-26 Georgia Commons bill sees the House record that matches the bill, not the person's later Senate one.

Former members must still be in `search-entities.json`, because the page builders read the set of pages from it (CLAUDE.md: never drop a record from that index). `generate_search_corpus.py` adds them from the ledger with the frozen record, and lists their ids under `retired['ga-legislator']` in `entity-urls.json`. That bucket only hides them from site search (`VoteGA.entityUrls.isRetired`, already generic). Unlike retired candidates, legislator pages do **not** get `noindex` or `sitemap: false`.

### The biennium switch

- `page.entity.bienniums` lists the bienniums available for that person: `"current"` if sitting, plus each frozen tag, newest first.
- The page's script (`_includes/entity/ga-legislator.html`) reads `?biennium=YYYY-YYYY`. The default is the newest. It loads the selected biennium's record, votes, sponsorship and scorecard from the live files ("current") or from `ga-bienniums/<tag>/`, always through `getBasePath()`. Any new script tags get the `?v=` suffix.
- **The switch shows only when there is more than one biennium.** A member with one sees a plain "2025–2026 General Assembly" label.
- **What follows the selection:** chamber, district, party, committees, leadership, key votes, voting history, sponsorship and scorecard. There are no cross-biennium totals (D10).
- **What shows only for a sitting member's current biennium:** contact details (D5) and "next election".
- If a frozen scorecard has no entry for the person (the 2025-26 one omits departed members; see D10), the panel is left out rather than showing zeros.

### Former-member banner and labels

- Fact and date only, worded by the rules in D6 and D9. For example: "Served in the Georgia House, District 63, in the 2025–2026 General Assembly. Resigned January 5, 2026." The facts come from the frozen record's `status` and `statusDate`.
- The banner links the seat's current holder (by chamber and district in the live roster, labelled with the plan) and the `Votega/ga-legislators` session archive.
- **A member who left the General Assembly for another office** (e.g. US House) gets the D6 label. If `id-crosswalk.json` ties the person to a bioguide id with a built `/us-congress/` page, the banner links it. It is never resolved by name.
- **A chamber mover is not a former member.** They get the D6 "Won the 2026 general election for …" label, not the banner.

### SEO

- JSON-LD `Person` with `jobTitle` "Former State Representative" or "Former State Senator".
- The title and description say "former", so the page doesn't read as a current officeholder in search results.
- A **Former Georgia Legislators** directory page lists former members, grouped by biennium and chamber, with name, party, district, how they left and the page link. It's a crawl path besides Georgia Commons and the D14 entry point. Also linked from `/find-my-reps` (D14).

## `votegaUrl`

- `has_page` no longer excludes Resigned, Removed or Deceased members: anyone with a voting-chamber seat and a `legisGaGovId` has a page. On the next roster run, the 11 get URLs.
- `votegaUrl` is the ledger's first URL for that person. The roster producer writes both from one computation, so they can't disagree.
- The frozen roster in `Votega/ga-legislators` `sessions/2025-2026/` keeps each member's `votegaUrl`. That URL keeps working, whether as the page or as a redirect.

## Edge cases

| Case | Handling |
|---|---|
| Re-elected, same seat | One URL. The switch shows 2027–28 (current) and 2025–26 (frozen). |
| Changes chambers (Wade, Romman, Draper, Reese in 2027) | The new slug is prepended. The old URL redirects to the new one with `?biennium=2025-2026`. One page. |
| Name or district change | The same mechanism as a chamber move. |
| Leaves, returns in a later biennium | The ledger still has the person. The roster producer computes a URL: if it matches an old one, that URL becomes first again; if not, the new one is prepended. Frozen data is kept. |
| Two seats in one biennium (mid-term special election to the other chamber) | Not present today. The freeze and the validator refuse it, so it fails loudly until it is designed. |
| Two people computing the same slug | The existing collision rule in `assign_votega_urls`. A person's URL, once in the ledger, is never handed to someone else; the validator fails if two people share one. |

## Validation and tests

- `scripts/validate_ga_legislator_ledger.py`, run by `update-ga-members` and on PRs:
  - Compared with `HEAD`, no person, URL or biennium has been removed.
  - No URL belongs to two people.
  - Every sitting member's `votegaUrl` equals their first ledger URL.
  - Every biennium in the ledger has the frozen files for that person.
- A test in the style of `test_ga_legislator_pages.py` runs the real page builder against fixtures, then checks:
  - Every ledger URL is either built as a page or built as a redirect.
  - A redirect's target is that person's first URL, with the right `?biennium=`.
  - Former members appear in `retired['ga-legislator']` and in the sitemap, and have no `noindex`.
- Freeze-script tests:
  - It refuses a member with no slice.
  - It refuses to overwrite a changed file.
  - Re-running it is idempotent.
- Browser check on clean `/ga-legislators/<slug>/` URLs (not `ga-member.html`):
  - a former member;
  - a sitting member with one biennium (no switch);
  - a fixture member with two bienniums (switch, deep link `?biennium=`);
  - an old URL redirecting.
  - Checked at 375 and 1280 wide.

## Rollout

1. **Now:**
   - The ledger, seeded from today's `votegaUrl`s.
   - `freeze_ga_biennium.py --members` for the 11 resigned members.
   - Former-member pages, the banner and the directory.
   - The `has_page` change, so the 11 get `votegaUrl`.

   Georgia Commons then links them on their next pass. Nothing about the switch is visible yet, because nobody has two bienniums.
2. **Before 2027-01-11:**
   - The biennium switch, tested with a two-biennium fixture.
   - `freeze_ga_biennium.py --all` added to the rollover procedure in `docs/RECURRING-TASKS.md` §3, after certification and the final `freeze-ga-roster` and before the session bump, together with the frozen scorecard (D10).
3. **At the rollover:** the `--new-biennium` run. The validator confirms that no ledger URL dropped.

## Out of scope

- Bienniums before 2025-26 (D7).
- Federal members (D12). The same ledger-plus-frozen-data shape should carry over to `/us-congress/` later.
- Moving the page's 178 KB inline script into an external file. That's worth doing (CLAUDE.md, Scaling) but isn't needed here: former pages add about 13 MB of built site per biennium against the 1 GB cap.
- Using Georgia Commons text (still blocked on a license).

## Changes to the rollover decisions

- **D3:** decided as this design: one page per person, a biennium switch, data frozen for every member rather than only former ones.
- **D4:** reversed. Former-member pages are indexed and in the sitemap.
- **D7:** unchanged.
- **D8:** unchanged for site search. The directory and sitemap are now in.
- **D13:** Georgia Commons links are already live. Tell them former-member URLs are preserved once rollout step 1 ships.
