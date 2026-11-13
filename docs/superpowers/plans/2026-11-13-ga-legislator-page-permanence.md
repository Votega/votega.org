# GA Legislator Page Permanence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A published `/ga-legislators/<slug>/` URL never 404s. It keeps serving that person's page (sitting or former), or redirects to their current URL. Each person gets one page, with a biennium switch across every biennium we hold data for.

**Architecture:**
- An append-only **page ledger** keyed on `legisGaGovId`. The roster producer writes it.
- A **frozen per-biennium data tree** (`assets/data/ga-bienniums/<tag>/`), written by a freeze script and never touched by the live slice builders.
- The search corpus and page builder read both, to emit former-member pages and redirect stubs.
- The page script resolves every data URL through one `dataRoot(biennium)` helper.

**Tech Stack:** Python 3 stdlib (scripts and script-style tests run by `run-script-tests.yml`, which globs `scripts/test_*.py` with no pip packages) · Jekyll + jekyll-redirect-from · inline page JS in `_includes/entity/ga-legislator.html`.

**Spec:** `docs/superpowers/specs/2026-11-13-ga-legislator-page-permanence-design.md`

## Global Constraints

- The primary key is `legisGaGovId`, stringified for JSON object keys. The roster `id` is opaque: never parse it, and never key on the per-term `legId`.
- Biennium tags are `lib/ga_sessions` tags (`"2025_26"`). URLs and labels use `session_slug(tag)` (`"2025-2026"`). The query parameter is `?biennium=2025-2026`.
- Data writes go through `lib/atomic_io.write_json_atomic` (never bare `open()` + `json.dump`). Missing optional fields are `None`, never `""`. Generated JSON carries `metadata.generatedAt` and `count`.
- The frozen tree uses the **same file names as the live files**: `ga-members.json`, `ga-votes-index.json`, `ga-votes/<member_slug(id)>.json`, `ga-sponsorship-index.json`, `ga-sponsorship/<legisGaGovId>.json`, `curated-ga-bill-votes.json`. A frozen biennium therefore needs no new client parsing, only a different root.
- Former-member pages are indexed. They never get `noindex`, `sitemap: false` or `search: false`. They're hidden only from site search, via `retired['ga-legislator']` in `entity-urls.json`.
- Former-member wording is fact and date only (D6 and D9): no "lost" or "defeated", no evaluation.
- All client fetches go through `getBasePath()`. Any new first-party `<script>` tag carries `?v={{ site.time | date: '%s' }}`. Colors use role tokens only, and status messages pair an icon with a label (CLAUDE.md coding patterns).
- Never remove a record from `search-entities.json` to hide a page. The builder reads its page set back from that file.

## Review Focus

1. **A sitting member after the final freeze, but before the rollover.** Their frozen `2025_26` equals the live session, so they must not get a two-entry switch that shows the same biennium twice. This is pinned in Task 4 (`test_bienniums_dedupe_live_session`).
2. **An old URL whose person's newest slug was published in the same biennium** (a mid-biennium rename). The redirect must carry no `?biennium=`, or it lands on a frozen copy of current data. Pinned in Task 4 (`test_redirect_same_biennium_has_no_param`).
3. **A `?biennium=` value that's bogus or not this person's** (`?biennium=1999-2000`, `?biennium=<script>`). Fall back to the newest biennium and never put the raw parameter into the DOM. Pinned in Task 5 (`pickBiennium` cases).
4. **A second freeze run after the live vote index has grown.** The 11 are frozen now, and `--all` runs in December. The newer index must be accepted when its `voteIds` extend the frozen ones, and refused when they don't. Pinned in Task 2 (`test_index_superset_accepted` / `test_index_reorder_refused`).
5. **A roster run where a member's computed slug collides with a URL another person already owns in the ledger.** It must fail rather than hand over the URL. Pinned in Task 1 (`test_url_owned_by_other_person_raises`).

---

## File Structure

| File | Responsibility |
|---|---|
| `scripts/lib/ga_ledger.py` (new) | Ledger shape, update, append-only diff, ownership checks. Pure, no I/O except `load_ledger`/`save_ledger`. |
| `scripts/lib/ga_biennium_freeze.py` (new) | Copies one biennium's per-member data into `ga-bienniums/<tag>/` under the superset/identical rules. Pure apart from file I/O on paths passed in. |
| `scripts/freeze_ga_biennium.py` (new) | CLI over the freeze lib, and updates the ledger's `bienniums`. |
| `scripts/lib/ga_former.py` (new) | Which members are former, their biennium list, the banner sentence and the job title. Pure. |
| `scripts/validate_ga_legislator_ledger.py` (new) | Tier-1 gate: the ledger against `HEAD`, the roster and the frozen tree. |
| `scripts/lib/ga_legislator_pages.py` | `has_page` stops excluding departed members. |
| `scripts/generate_ga_members_soap.py` | Writes the ledger after `assign_votega_urls`. |
| `scripts/generate_search_corpus.py` | Emits former members (live-departed and frozen-only). |
| `scripts/build_entity_pages.py` | Former pages, the ledger-driven slug, redirect stubs, the retired bucket and the directory group. |
| `_includes/entity/ga-legislator.html` | `dataRoot`/`pickBiennium`, the switch, and no contact details off the live biennium. |
| `.github/workflows/update-ga-members.yml` | Runs the ledger validator and commits the ledger. |
| Docs | `docs/RECURRING-TASKS.md` §3, `CLAUDE.md` (schema and convention), `docs/georgia-civic-data-collaboration.md`. |

---

### Task 1: Page ledger library

**Files:**
- Create: `scripts/lib/ga_ledger.py`
- Test: `scripts/test_ga_ledger.py` (script style: `check(name, got, want)`, exit 1 on failure, copying `test_ga_legislator_pages.py`)

**Interfaces:**
- Produces:
  - `LEDGER_PATH: str` = `assets/data/ga-legislator-ledger.json`
  - `class LedgerError(Exception)`
  - `empty_ledger() -> dict` returns `{"metadata": {"generatedAt": None, "count": 0}, "people": {}}`
  - `load_ledger(path=LEDGER_PATH) -> dict` returns `empty_ledger()` when the file is absent
  - `save_ledger(ledger, path=LEDGER_PATH, generated_at=None) -> None` sets `metadata.count = len(people)` and writes atomically with sorted keys and indent=2
  - `update_ledger(ledger: dict, members: list[dict], session_tag: str) -> list[str]` mutates the ledger and returns change lines
  - `add_biennium(ledger: dict, gid: str, tag: str) -> None` keeps `bienniums` newest first, with no duplicates. Raises `LedgerError` if `gid` isn't in the ledger: a person must have a URL before they can have frozen data.
  - `current_path(ledger, gid) -> str | None`
  - `owner_of(ledger, path) -> str | None`
  - `append_only_violations(old: dict, new: dict) -> list[str]`
- **Person entry:** `{"rosterId": str, "urls": [{"path": "/ga-legislators/<slug>/", "biennium": "<tag first published under>"}], "bienniums": [tag, ...]}`. `urls[0]` is current.

- [ ] **Step 1: Write the failing tests**

```python
m = lambda gid, slug, **kw: dict({"legisGaGovId": gid, "id": f"ocd-person/{gid}",
        "votegaUrl": f"https://www.votega.org/ga-legislators/{slug}/"}, **kw)

def test_seed():
    L = empty_ledger(); update_ledger(L, [m(4942, "josh-mclaurin-senate-14")], "2025_26")
    check("seeded", L["people"]["4942"]["urls"],
          [{"path": "/ga-legislators/josh-mclaurin-senate-14/", "biennium": "2025_26"}])
def test_rename_prepends():          # old path kept, new first, new entry tagged with run's session
def test_return_to_old_url_moves_it_first():   # no duplicate entry, list length unchanged
def test_member_without_url_or_gid_ignored():  # votegaUrl None / legisGaGovId None -> no person
def test_url_owned_by_other_person_raises():   # LedgerError naming both gids
def test_person_absent_from_members_is_kept(): # update never deletes
def test_append_only_violations():  # removed person, removed path, removed biennium -> 3 lines; unchanged -> []
def test_add_biennium_newest_first(): # add 2025_26 then 2027_28 -> ["2027_28","2025_26"]; re-add is a no-op
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `python scripts/test_ga_ledger.py`
Expected: FAIL, `ModuleNotFoundError: lib.ga_ledger`

- [ ] **Step 3: Implement `scripts/lib/ga_ledger.py`**

Strip `SITE_URL` (import it from `lib.ga_legislator_pages`) from `votegaUrl` to get `path`. `update_ledger` raises `LedgerError` before mutating anything if any member's path is owned by a different gid. `rosterId` is set on first sight and refreshed only if it was missing.

- [ ] **Step 4: Run the tests to make sure they pass**

Run: `python scripts/test_ga_ledger.py`
Expected: `All checks passed.`

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/ga_ledger.py scripts/test_ga_ledger.py
git commit -m "Add append-only GA legislator page ledger library"
```

---

### Task 2: Freeze a biennium, and freeze the 11 resigned members

**Files:**
- Create: `scripts/lib/ga_biennium_freeze.py`, `scripts/freeze_ga_biennium.py`
- Test: `scripts/test_ga_biennium_freeze.py` (builds a temp `data_dir` with a fake roster, index and slices; no network)
- Generated (committed): `assets/data/ga-bienniums/2025_26/**`, `assets/data/ga-legislator-ledger.json`

**Interfaces:**
- Consumes: `lib.ga_ledger` (`load_ledger`, `save_ledger`, `add_biennium`). `member_slug` is a copy of the regex in `build_member_votes_slices.member_slug`. Import it from there, and don't re-implement it.
- Produces:
  - `FROZEN_ROOT: str` = `assets/data/ga-bienniums`
  - `class FreezeError(Exception)`
  - `freeze(tag: str, gids: list[str], data_dir: str, out_root: str, *, overwrite=False, no_votes_ok=()) -> dict` returns a report `{"frozen": [gid], "unchanged": [gid], "replacedIndexes": [name]}`
  - CLI: `python scripts/freeze_ga_biennium.py <tag> (--members GID,GID | --departed | --all) [--overwrite] [--no-votes-ok GID,...]`. `--departed` means roster members whose status is in `NO_PAGE_STATUSES`; `--all` means every voting-chamber member with a `legisGaGovId`.

**Rules (copy exactly):**
- **`<tag>/ga-members.json`:** `{"metadata": {"biennium": tag, "session": <roster metadata.session>, "generatedAt", "count", "source": "frozen from assets/data/ga-members.json"}, "members": [...]}`. Members are merged by `legisGaGovId`. A different record for an already-frozen gid is refused unless `overwrite`.
- **`ga-votes-index.json`:** written if absent. Replaced if the new `voteIds` starts with every frozen `voteIds` entry, in order. Otherwise refused.
- **`ga-sponsorship-index.json`:** written if absent. Replaced if every frozen `members` key is still present. Otherwise refused.
- **Per-member slices:** copied. If one already exists with different bytes, it's refused unless `overwrite`.
- **A member with no vote slice:** `FreezeError`, unless their gid is in `no_votes_ok`. Then they're recorded under `metadata.noVotes` with no slice.
- **`curated-ga-bill-votes.json`:** copied whole on `--all` only (key votes for the closed biennium, D15).
- **Ledger:** `add_biennium(ledger, gid, tag)` for each frozen gid, saved once at the end. The CLI does nothing at all (no files written) if `freeze` raises.

- [ ] **Step 1: Write the failing tests**

```python
def test_freeze_copies_member_record_and_slices():   # files exist, members.json has 1 record, metadata.biennium == "2025_26"
def test_missing_vote_slice_refused():               # FreezeError mentions gid
def test_no_votes_ok_records_note():                 # metadata.noVotes == ["123"]
def test_rerun_is_idempotent():                      # second identical run -> report["unchanged"] == [gid], bytes identical
def test_changed_slice_refused_without_overwrite():
def test_index_superset_accepted():                  # frozen voteIds [a,b], live [a,b,c] -> replaced
def test_index_reorder_refused():                    # frozen [a,b], live [b,a,c] -> FreezeError
def test_sponsorship_index_dropping_member_refused():
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `python scripts/test_ga_biennium_freeze.py`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: Implement the lib and the CLI** to the rules above. Fold the ledger into the CLI, not the lib, so the lib tests need no ledger.

- [ ] **Step 4: Run the tests to make sure they pass**

Run: `python scripts/test_ga_biennium_freeze.py`
Expected: `All checks passed.`

- [ ] **Step 5: Commit** (tooling only; the real freeze runs in Task 3, once the 11 have URLs)

```bash
git add scripts/lib/ga_biennium_freeze.py scripts/freeze_ga_biennium.py scripts/test_ga_biennium_freeze.py
git commit -m "Add GA biennium freeze tool"
```

---

### Task 3: Former members get URLs and search records

**Files:**
- Create: `scripts/lib/ga_former.py`, `scripts/test_ga_former.py`
- Modify:
  - `scripts/lib/ga_legislator_pages.py` (`has_page`; delete `NO_PAGE_STATUSES` from the page rule but keep the constant, now named `DEPARTED_STATUSES`, imported by `ga_former`)
  - `scripts/generate_ga_members_soap.py:452` (write the ledger)
  - `scripts/generate_search_corpus.py:117-161`
  - `scripts/test_ga_legislator_pages.py`

**Interfaces:**
- Consumes: `lib.ga_ledger`, the frozen tree from Task 2.
- Produces (`lib/ga_former.py`):
  - `DEPARTED_STATUSES = ("Resigned", "Removed", "Deceased")`
  - `load_frozen(root=FROZEN_ROOT) -> dict[str, dict[str, dict]]`, i.e. `{tag: {gid: record}}`
  - `former_records(live_members: list[dict], frozen: dict) -> list[tuple[dict, str]]`, i.e. `(record, tag)` for each former member. A live member with a departed status uses the live record and the tag `"current"`. A frozen-only gid uses its newest frozen record and that tag.
  - `is_former(m: dict, in_live: bool) -> bool`
  - `bienniums_for(gid: str, live_session_tag: str | None, frozen: dict) -> list[str]` returns `["current", *frozen tags newest first]` for a sitting member, **dropping a frozen tag equal to `live_session_tag`**, and the frozen tags alone for a frozen-only member
  - `departure_sentence(m: dict, tag: str) -> str`
  - `job_title(m: dict, former: bool) -> str`, e.g. `"Former State Representative"`

**`departure_sentence` copy (exact):** `"Served in the Georgia {House|Senate}, District {n}, in the {YYYY–YYYY} General Assembly."` Then, when `status` and `statusDate` are both set, append `" {Resigned|Removed from office|Died} {Month D, YYYY}."` (Deceased → "Died"). Use an en dash in the years. With no status (a frozen-only member who didn't return), append nothing more.

- [ ] **Step 1: Write the failing tests**

```python
def test_live_resigned_is_former_with_current_tag():
def test_frozen_only_member_uses_newest_frozen_record():
def test_bienniums_dedupe_live_session():     # sitting, frozen {"2025_26"}, live "2025_26" -> ["current"]
def test_bienniums_after_rollover():          # sitting, frozen {"2025_26"}, live "2027_28" -> ["current","2025_26"]
def test_departure_sentence_resigned():       # "... District 63, in the 2025–2026 General Assembly. Resigned January 5, 2026."
def test_departure_sentence_no_status():
def test_job_title():
```

Also, in `test_ga_legislator_pages.py`, change the "members without a page get null" check: the resigned members now **have** a URL. Add `check("departed members get a url", all(m["votegaUrl"] for m in derived if m.get("status") in DEPARTED_STATUSES and m.get("legisGaGovId")), True)`.

- [ ] **Step 2: Run them to make sure they fail**

Run: `python scripts/test_ga_former.py; python scripts/test_ga_legislator_pages.py`
Expected: both FAIL

- [ ] **Step 3: Implement**
- **`has_page`:** an `ocd-person/` or `legis-` id, a voting chamber, and a `legisGaGovId`. Status no longer matters.
- **Roster producer:** after `assign_votega_urls(members)`, `L.update_ledger(ledger, members, tag)` then `L.save_ledger(...)`. If `LedgerError` is raised, print it and `return 1` before writing `ga-members.json`.
- **Search corpus:** keep the existing loop for sitting members (skip departed). Then, for each `(record, tag)` in `former_records(...)`, add one record with `category="GA Legislator"`, `url=f"ga-member.html?id={quote(record['id'], safe='')}"` and `desc="Former {Representative|Senator}, District N, Party"`, plus a new key `"former": tag`. A frozen-only record is added only if its `id` isn't already present.

- [ ] **Step 4: Run the tests to make sure they pass**

Run: `python scripts/test_ga_former.py; python scripts/test_ga_legislator_pages.py; python scripts/test_ga_ledger.py`
Expected: all `All checks passed.` (The page-builder agreement check passes only after Task 4. If `test_ga_legislator_pages.py` fails on "derived urls equal the page builder's permalinks", do Task 4 and re-run both before committing; Tasks 3 and 4 may land in one commit.)

- [ ] **Step 5: Re-derive `votegaUrl`, seed the ledger, and freeze the 11** (offline: this rewrites only `votegaUrl` in the committed roster, the same field the next `update-ga-members` run would write, so `test_ga_legislator_pages.py` check 3 agrees)

```bash
python -c "import sys,json; sys.path.insert(0,'scripts'); from lib.atomic_io import write_json_atomic; from lib.ga_legislator_pages import assign_votega_urls; from lib import ga_ledger as L; p='assets/data/ga-members.json'; d=json.load(open(p,encoding='utf-8')); assign_votega_urls(d['members']); write_json_atomic(p,d,indent=2,ensure_ascii=False); led=L.load_ledger(); L.update_ledger(led,d['members'],'2025_26'); L.save_ledger(led)"
git diff --stat assets/data/ga-members.json
python scripts/freeze_ga_biennium.py 2025_26 --departed
python scripts/generate_search_corpus.py
```

Expected:
- the `ga-members.json` diff touches only 11 `votegaUrl` lines. If `write_json_atomic`'s formatting changes other lines, match the producer's own write call (`grep -n write_json_atomic scripts/generate_ga_members_soap.py`) and redo it;
- the ledger has 247 people;
- the freeze reports 11 frozen, and `assets/data/ga-bienniums/2025_26/ga-members.json` has `count: 11`;
- `du -sh assets/data/ga-bienniums` is under 3 MB.

If a resigned member has no vote slice, stop and report it. Don't pass `--no-votes-ok` without the user's say.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/ga_former.py scripts/test_ga_former.py scripts/lib/ga_legislator_pages.py scripts/generate_ga_members_soap.py scripts/generate_search_corpus.py scripts/test_ga_legislator_pages.py assets/data/search-entities.json assets/data/ga-members.json assets/data/ga-legislator-ledger.json assets/data/ga-bienniums
git commit -m "Give departed GA legislators URLs, search records and frozen 2025-26 data"
```

---

### Task 4: Page builder — former pages, ledger slugs, redirect stubs

**Files:**
- Modify: `scripts/build_entity_pages.py:913-1011` (`build_ga_legislators`)
- Test: `scripts/test_ga_legislator_permanence.py` (new; runs the real builder with `B.load`, `B.write_page`, `B.add_card` and `B.resolve_lastmod` monkeypatched, the same way `test_ga_legislator_pages.builder_urls` does, so it captures every written page's front matter and body)

**Interfaces:**
- Consumes: `lib.ga_ledger.load_ledger` / `current_path`, and `lib.ga_former.*`.
- Produces, for the page script (Task 5): the body script becomes `window.VOTEGA_ENTITY = {"id": <rosterId>, "bienniums": [...], "former": <null | {"biennium": tag, "status": str|null, "statusDate": str|null}>};`. The `entity` front matter gains `"former"` (same object) and `"bienniums"`.

**Behavior:**
- **Members map:** live members, plus frozen-only records (newest tag) for `former` search records.
- **Slug:** `current_path(ledger, gid)` when present. Otherwise the computed slug as today, plus a printed warning (a fresh member before their first roster run).
- **Former page:**
  - `urls["retired"]["ga-legislator"][rosterId] = True`;
  - JSON-LD `jobTitle = job_title(m, True)`;
  - `share-title` gets the prefix `"Former "` before the role phrase;
  - phone, website and nextElection are `None`;
  - card badge `"Former Officeholder"`;
  - a server-rendered banner `<p class="former-member-banner"><i class="fa-solid fa-clock-rotate-left" aria-hidden="true"></i> {departure_sentence} {successor link}</p>` sits before the `{% include %}`. The successor is the live sitting member with the same chamber and district, rendered as "The seat is now held by <a href=…>Name</a>." and omitted when there is none.
  - Directory: `_dir_add("legislators", f"Former Georgia Legislators ({session_slug(tag)})", 2, (district, name), …)`.
  - **No** `noindex`, `sitemap` or `search` keys.
- **Redirect stubs:** for every ledger person and every `urls[i]` with `i > 0`, `write_page("ga-legislators", <old slug>, {"permalink": old, "redirect_to": target, "sitemap": "false"}, "")`. Here `target = SITE_URL + urls[0].path`, plus `"?biennium=" + session_slug(entry.biennium)` **only when** `entry.biennium != urls[0].biennium`.
- **Ledger and pages must agree:** a ledger person with no built page and no redirect stub raises `SystemExit("ledger person <gid> has no page")`. This must fail the deploy, because it's exactly the 404 this work exists to prevent.

- [ ] **Step 1: Write the failing tests** (fixture roster + ledger + frozen tree in a temp dir, `B.SRC_DIR` pointed at it)

```python
def test_former_live_resigned_page_built_indexed():     # page exists, fm has no "noindex"/"sitemap", retired bucket has id
def test_frozen_only_member_page_built():
def test_banner_text_and_successor_link():
def test_former_has_no_contact_or_next_election():
def test_slug_comes_from_ledger_not_name():             # ledger path differs from computed -> ledger path used
def test_redirect_carries_biennium_when_different():    # old entry 2025_26, current 2027_28 -> "?biennium=2025-2026"
def test_redirect_same_biennium_has_no_param():
def test_bienniums_dedupe_live_session():               # VOTEGA_ENTITY.bienniums == ["current"]
def test_ledger_person_without_page_fails():
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `python scripts/test_ga_legislator_permanence.py`
Expected: FAIL

- [ ] **Step 3: Implement** the behavior above in `build_ga_legislators`. Keep the existing sitting-member output byte-identical apart from the new `VOTEGA_ENTITY` keys, so the sitemap `lastmod` doesn't churn for 236 pages. Add `former` and `bienniums` to `entity` only when they're non-default (`former` set, or more than one biennium), the same rule as `entity.retired` on candidates.

- [ ] **Step 4: Run all related tests**

Run: `python scripts/test_ga_legislator_permanence.py; python scripts/test_ga_legislator_pages.py; python scripts/test_ga_former.py`
Expected: all pass

- [ ] **Step 5: Build for real and check counts**

Run: `python scripts/build_entity_pages.py 2>&1 | tail -20`
Expected: legislator count = 247 (236 + 11). There are no redirect stubs yet, because no ledger person has a second URL.

- [ ] **Step 6: Commit**

```bash
git add scripts/build_entity_pages.py scripts/test_ga_legislator_permanence.py
git commit -m "Build former GA legislator pages and ledger redirect stubs"
```

---

### Task 5: Page script — biennium data root and switch

**Files:**
- Modify: `_includes/entity/ga-legislator.html`:
  - the constants at 429, 1157, 1304-1305, 1744-1746;
  - contact rendering at 1009-1013;
  - add `.former-member-banner` and `.biennium-switch` styles (role tokens: `--color-warning-tint`/`--color-warning-line` for the banner, since it's a status message and has an icon and a label).
- Test: `scripts/test_ga_legislator_biennium_js.py` (extracts `pickBiennium` and `dataRoot` from the include by marker comments, and runs them with `node -e` if `node` is on PATH; otherwise prints `skip` and passes, since the CI job has no Node guarantee). Mark both functions with `// BEGIN biennium-helpers` / `// END biennium-helpers`.

**Interfaces:**
- Consumes: `window.VOTEGA_ENTITY.bienniums` / `.former` (Task 4).
- Produces (in the include, between the markers):
  - `pickBiennium(available: string[], param: string|null) -> string`: `param` "2025-2026" maps to the tag "2025_26". It returns that tag if it's in `available`, else `available[0]`, else `'current'`. It accepts only `/^\d{4}-\d{4}$/`.
  - `dataRoot(b: string) -> string`: `getBasePath() + 'assets/data/'` for `'current'`, else `getBasePath() + 'assets/data/ga-bienniums/' + b + '/'`.
  - `const SELECTED_BIENNIUM`, `const IS_LIVE = SELECTED_BIENNIUM === 'current'`.

**Behavior:**
- `DATA_URL`, `CURATED_BILLS_URL`, `SPON_INDEX_URL`, `sponSliceUrl` and the votes `INDEX_URL`/`SLICE_URL` all build on `dataRoot(SELECTED_BIENNIUM)`. `RACES_URL` and `FINANCE_URL` stay live.
- **Contact details** (phone, email, website, office) render only when `IS_LIVE`.
- **The switch** renders only when `bienniums.length > 1`: a `<nav class="biennium-switch" aria-label="General Assembly">` of plain links (`?biennium=YYYY-YYYY`, or the bare URL for `current`), with `aria-current="page"` on the selected one. Link labels: "2027–2028 (current)" and "2025–2026", from the roster's `metadata.session` and `session_slug`. Navigating reloads the page; there's no in-page re-render.
- **With one biennium**, the page shows a plain label `"{YYYY–YYYY} General Assembly"` in the same spot.
- **The legacy shell** (`/ga-member.html?id=`) has no `VOTEGA_ENTITY.bienniums`, so it behaves exactly as today (`'current'`).

- [ ] **Step 1: Write the failing test**

```python
cases = [ (["current","2025_26"], None, "current"), (["current","2025_26"], "2025-2026", "2025_26"),
          (["2025_26"], None, "2025_26"), (["current"], "1999-2000", "current"),
          (["current"], "<script>", "current"), ([], None, "current") ]
# plus dataRoot("current") endswith "assets/data/", dataRoot("2025_26") endswith "assets/data/ga-bienniums/2025_26/"
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python scripts/test_ga_legislator_biennium_js.py`
Expected: FAIL (markers not found)

- [ ] **Step 3: Implement** the helpers, constants, switch, label and contact guard.

- [ ] **Step 4: Run the test to make sure it passes**

Run: `python scripts/test_ga_legislator_biennium_js.py`
Expected: pass (or `skip` only if Node is absent locally; check with `node --version` first)

- [ ] **Step 5: Verify in the browser** on clean URLs (CLAUDE.md: not `ga-member.html`). Build with `build_entity_pages.py` + `jekyll build`, then serve via a `.claude/launch.json` entry if none exists. Check at 375 and 1280 wide, in light and dark:
  - one of the 11 at `/ga-legislators/<slug>/`: banner, votes and sponsorship load from `ga-bienniums/2025_26/` (check `read_network_requests`), no contact block, no switch, plain label;
  - a sitting member: unchanged, no switch, no console errors;
  - a two-biennium member, using a temporary local ledger and frozen tag `2023_24` copied from `2025_26` (**don't commit it**): the switch shows, `?biennium=2023-2024` loads the frozen files, and `?biennium=bogus` falls back to current;
  - console clean on all three.

  Take a screenshot of the former page for the user.

- [ ] **Step 6: Commit**

```bash
git add _includes/entity/ga-legislator.html scripts/test_ga_legislator_biennium_js.py
git commit -m "Legislator page: biennium data root, switch, and former-member banner styles"
```

---

### Task 6: Ledger validator and workflow gate

**Files:**
- Create: `scripts/validate_ga_legislator_ledger.py`, `scripts/test_validate_ga_legislator_ledger.py`
- Modify: `.github/workflows/update-ga-members.yml` (a validation step after the existing `validate_ga_members.py` step; add `assets/data/ga-legislator-ledger.json` to the paths it commits)

**Interfaces:**
- Consumes: `lib.ga_ledger.append_only_violations`, `owner_of`, `current_path`; `lib.ga_former.load_frozen`.
- Produces: CLI `python scripts/validate_ga_legislator_ledger.py [--ledger PATH] [--roster PATH] [--frozen-root PATH] [--base-ref HEAD]`, which exits 1 on any tier-1 violation and prints tier-2 notes.

**Tier 1 (gates):**
- Any violation of `append_only_violations(HEAD version, working version)`. Use `git show <ref>:<path>`, read as **bytes** and decoded as UTF-8 (memory: Windows locale decoding fakes corruption). Treat a missing file at `HEAD` as an empty ledger.
- A path owned by two gids.
- A sitting roster member whose `votegaUrl` path isn't their `current_path`.
- A ledger `bienniums` tag with no frozen `ga-members.json` record for that gid.
- A gid with two different (chamber, district) records inside one frozen biennium (the mid-biennium move case in the spec).

**Tier 2 (reports):** people added, URLs added (renames), new bienniums.

- [ ] **Step 1: Write the failing tests** (temp git repo, created with `git init` in a temp dir **inside the repo's scratch area**; memory: a fixture outside the repo makes `git show HEAD:` silently fail, so assert that the base read succeeded):

```python
def test_clean_passes():
def test_removed_url_fails():
def test_shared_url_fails():
def test_votegaurl_mismatch_fails():
def test_biennium_without_frozen_record_fails():
def test_base_read_failure_is_an_error_not_a_pass():   # bad ref -> exit 1 with message
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `python scripts/test_validate_ga_legislator_ledger.py`
Expected: FAIL

- [ ] **Step 3: Implement the validator and wire the workflow step.** Then `grep -n "sys.exit\|SystemExit" scripts/generate_ga_members_soap.py` to confirm the producer's `LedgerError` exit (Task 3) runs before the validator, so a failure is reported once and with the producer's message (memory: a gate duplicated upstream).

- [ ] **Step 4: Run it against the real files**

Run: `python scripts/test_validate_ga_legislator_ledger.py && python scripts/validate_ga_legislator_ledger.py`
Expected: tests pass, and the real run exits 0 and reports 247 people.

- [ ] **Step 5: Commit**

```bash
git add scripts/validate_ga_legislator_ledger.py scripts/test_validate_ga_legislator_ledger.py .github/workflows/update-ga-members.yml
git commit -m "Gate the GA legislator page ledger in update-ga-members"
```

---

### Task 7: Docs, rollover procedure, and the full test sweep

**Files:**
- Modify:
  - `docs/RECURRING-TASKS.md` §3: a new step between the final `freeze-ga-roster` and the session bump: `python scripts/freeze_ga_biennium.py 2025_26 --all`, commit, then `validate_ga_legislator_ledger.py`. State that it must run before the `--new-biennium` run, because the slice builders delete departed members' slices.
  - `CLAUDE.md`:
    - a short `ga-legislator-ledger.json` + `ga-bienniums/` schema section beside `ga-members.json`;
    - a convention bullet: "a legislator URL never 404s; the ledger is append-only; never delete from `ga-bienniums/`";
    - change the `id` paragraph's claim that departed members have no page.
  - `docs/georgia-civic-data-collaboration.md`: step A.4 now says departed members have URLs too.
  - `docs/superpowers/specs/2026-11-13-ga-legislator-page-permanence-design.md`: file names in the frozen-tree listing now mirror the live names (as built). Party-unity isn't frozen, because the page computes it from the vote slice.

- [ ] **Step 1: Make the doc edits above.**

- [ ] **Step 2: Run every script test, as CI does**

Run: `for t in scripts/test_*.py; do python "$t" >/dev/null 2>&1 || echo "FAIL $t"; done`
Expected: no `FAIL` lines. If a failure was already there before this branch, confirm it with `git stash` and report it; don't fix it here.

- [ ] **Step 3: Run the workflow validator** (CLAUDE.md: required when workflows change)

Run: `python scripts/validate_workflow_triggers.py`
Expected: exit 0

- [ ] **Step 4: Commit**

```bash
git add docs/RECURRING-TASKS.md CLAUDE.md docs/georgia-civic-data-collaboration.md docs/superpowers/specs/2026-11-13-ga-legislator-page-permanence-design.md
git commit -m "Document the legislator page ledger and the biennium freeze step"
```

---

## Not in this plan (deliberately)

- Running `freeze_ga_biennium.py --all`. That's the December rollover step, after certification and the final `freeze-ga-roster`.
- The D6 classifier and the "Won the 2026 general election for …" labels for movers and those who won another office. That's the separate D6 work. This plan's banner covers status and date only.
- A frozen party-unity scorecard (D10), and the `/find-my-reps` "Former Legislators" card (D14). The directory group in Task 4 is the crawl path for now.
- Telling Georgia Commons. Do it after Task 4 deploys and their 11 links resolve.
