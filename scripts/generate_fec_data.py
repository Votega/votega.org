#!/usr/bin/env python3
"""
Generate ga-fec-data.json from FEC API for GA congressional candidates.
Requires FEC_API_KEY environment variable.

Flow:
  1. GET /v1/candidates/ for GA House + Senate, cycle 2026
  2. Attach bioguide_id to each FEC candidate (FEC API does not reliably return it
     in candidate list responses), in priority order:
       a. unitedstates/congress-legislators FEC->bioguide crosswalk (canonical,
          keyed on the FEC candidate_id itself, so it can never conflate a
          same-district same-surname challenger with an incumbent)
       b. surname + seat heuristic against current-members.json, for incumbents
          the crosswalk doesn't cover yet (e.g. just-seated members)
  3. GET /v1/committee/{id}/totals/ for each candidate's committee -- both the
     headline cards and the receipt-component breakdown (see FUNDING_FIELDS)
     come out of this one response. Normally the principal campaign committee,
     but see get_candidate_committees(): a candidacy can have more than one
     authorized committee and FEC adds them together, so the totals here are
     summed across the set and the entry records the principal's name and
     designation (plus contributingCommittees when there is more than one)
  4. GET /v1/schedules/schedule_a/by_employer/ for top donors by employer

Output: assets/data/ga-fec-data.json
  - candidates: keyed by FEC candidate_id. Each may carry `funding`, the
    composition of receipts (PAC, party, transfers, self-funding, itemized vs
    unitemized individual money) -- see FUNDING_FIELDS.
  - byBioguideId: bioguide_id -> candidate_id (for incumbent lookups; one filing,
    chosen by preferred_filing() when a member holds several this cycle)
  - byBioguideIdAll: bioguide_id -> [candidate_id, ...] (every filing, sorted — use
    this when the office matters, or when a join must cover all of a person's ids)
  - byNormalizedName: normalized "first last" -> candidate_id (name-based fallback;
    one filing, same preferred_filing() rule)
  - byNormalizedNameAll: normalized "first last" -> [candidate_id, ...]. A normalized
    name is NOT an identity: 16 of them currently cover more than one filing, which the
    single-valued index cannot express. A consumer that would otherwise trust an
    arbitrary pick should read this and treat a multi-id key as ambiguous.
  - byDistrict: "H10" or "S" -> [candidate_ids] (district-scoped last-name matching)

Lookup strategy in candidate.html (findFecId):
  1. bioguide ID (incumbents with enriched data)
  2. district key + last name match (handles formal vs. nickname mismatches)
  3. normalized full name (exact FEC name match, last resort)
"""

import json
from lib.atomic_io import write_json_atomic
import os
import re
import sys
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone

from lib.http import fetch_json

API_KEY     = os.environ.get('FEC_API_KEY')
BASE_URL    = "https://api.open.fec.gov/v1"
# Canonical, human-maintained bioguide<->FEC-ID crosswalk (public domain, CC0,
# no API key). unitedstates.github.io is the published JSON mirror — the repo
# itself commits only YAML on the main branch.
LEGISLATORS_URL = ("https://unitedstates.github.io/congress-legislators/"
                   "legislators-current.json")
OUTPUT_FILE = sys.argv[1] if len(sys.argv) > 1 else "assets/data/ga-fec-data.json"
RACES_FILE  = "assets/data/races.json"
FALLBACK_CYCLE = 2026  # only used if races.json can't be read
DELAY       = 1.0
TOP_N       = 10   # top employers/donors to store per candidate
FETCH_N     = 25   # fetch more from API to allow for filtered-out junk entries


def target_cycle():
    """Newest cycle present in races.json, so a new cycle is a data change not a code one.
    Mirrors generate_ga_campaign_finance.py's target_cycle() — same source of truth,
    kept in sync so the state and federal finance data never disagree on the cycle."""
    try:
        with open(RACES_FILE, encoding="utf-8") as f:
            cycles = [r.get("cycle") for r in json.load(f).get("races", []) if r.get("cycle")]
        if cycles:
            return max(cycles)
    except Exception as e:
        print(f"  (could not read {RACES_FILE}: {e})")
    return FALLBACK_CYCLE


CYCLE = target_cycle()


def fec_get(path, params=None, retries=3):
    query = {"api_key": API_KEY, "per_page": 100}
    if params:
        query.update(params)
    url = f"{BASE_URL}{path}?{urllib.parse.urlencode(query)}"
    # Delegates to lib.http. rate_limit_backoff=60 preserves this endpoint's
    # 60s/120s/180s ramp on 429 — the FEC rate limits per hour, so the generic
    # 5s ramp would be useless here. The gain is that 5xx and network errors are
    # now retried too; previously any non-429 error returned None on the first
    # attempt. See CODEBASE-REVIEW-2026-08-18.md 2.4.
    return fetch_json(
        url,
        retries=retries,
        rate_limit_backoff=60,
        redact=API_KEY,
        label=path,
    )


def get_ga_candidates():
    """Fetch every GA House and Senate candidate for the cycle.

    The FEC list endpoint caps per_page at 100, so this must paginate — without it
    the results are silently truncated to the first 100 names alphabetically,
    dropping most incumbents (everything past ~'H') from the dataset.
    """
    candidates = []
    for office in ("H", "S"):
        office_total = 0
        page = 1
        while True:
            data = fec_get("/candidates/", {
                "state": "GA", "office": office, "cycle": CYCLE,
                "sort": "name", "per_page": 100, "page": page
            })
            if not data:
                print(f"    Warning: GA {office} page {page} failed — results may be incomplete")
                break

            results = data.get("results", [])
            candidates.extend(results)
            office_total += len(results)

            pagination  = data.get("pagination") or {}
            total_pages = pagination.get("pages") or 1
            if page >= total_pages or not results:
                break
            page += 1
            time.sleep(DELAY)

        print(f"  GA {office}: {office_total} candidates ({page} page{'s' if page != 1 else ''})")
        time.sleep(DELAY)
    return candidates


# Committee designations, best first. 'P' is the principal campaign committee,
# 'A' another authorized one. Nothing else is the candidate's own money.
DESIGNATION_RANK = {"P": 0, "A": 1}

# The designations that mean "this committee is the candidate's own". Everything
# else — 'D' leadership PAC, 'J' joint fundraiser, 'U' unauthorized — is money
# raised around a politician, not by their campaign, and never becomes the
# headline figure on their page.
AUTHORIZED_DESIGNATIONS = {"P", "A"}


def get_candidate_committees(candidate_id):
    """Every committee whose money is this candidacy's, plus a fallback pointer.

    Returns {"authorized": [ {id, name, designation}, ... ], "related": {...}|None}.
    `authorized` is P then A, newest filer first within a tier, and is EMPTY when
    FEC links only committees that are not the candidate's own; `related` then
    names the best of those so the page can link out without quoting its money
    (see noFilingHtml() in campaign-finance.js).

    Plural because a candidacy can have more than one authorized committee and
    FEC's candidate page adds them together -- its "Data is included from these
    committees" line. Mike Collins has MIKE COLLINS FOR SENATE (C00544684, P)
    and COLLINS FOR GA SENATE REPUBLICAN NOMINEE FUND 2026 (C00892000, A); FEC
    reports $10,249,716.29 and we reported $9,290,371.80, because we read the
    principal alone. A nominee fund is designation A, so it is absent from the
    list endpoint's `principal_committees` as well -- which is why this is now
    asked for every candidate rather than only when that field is missing.

    Only P and A qualify. Two earlier rules let other designations through and
    both put other people's money on candidate pages: taking the best-ranked
    committee of any designation (a leadership PAC's $4.7M landed on a live
    Senate candidate's page), and allowing one that had ever been designated P
    (/committee/{id}/history/ records designations over time but not whose
    candidate they answered to, so it measured committee age -- it accepted
    seven PACs and refused three committees that really were the candidate's).
    """
    data = fec_get(f"/candidate/{candidate_id}/committees/", {"cycle": CYCLE})
    results = (data or {}).get("results") or []
    if not results:
        return {"authorized": [], "related": None}

    results.sort(key=lambda c: (DESIGNATION_RANK.get(c.get("designation"), 9),
                                _newest_first(c.get("last_file_date")),
                                c.get("committee_id") or ""))
    authorized, others = [], []
    for c in results:
        row = {
            "id":          c.get("committee_id"),
            "name":        c.get("name") or "",
            "designation": c.get("designation") or "",
        }
        (authorized if row["designation"] in AUTHORIZED_DESIGNATIONS else others).append(row)

    if authorized:
        if len(authorized) > 1:
            names = ", ".join(f"{a['id']} [{a['designation']}]" for a in authorized)
            print(f"    {candidate_id}: {len(authorized)} authorized committees — {names}")
        return {"authorized": authorized, "related": None}

    best = others[0] if others else None
    if best:
        print(f"    {candidate_id}: no authorized committee; FEC links "
              f"{best['id']} ({best['name'] or '?'}, designation "
              f"{best['designation'] or '-'}) — recording it as a reference only")
    return {"authorized": [], "related": best}


def get_committee_totals(committee_id):
    data = fec_get(f"/committee/{committee_id}/totals/", {"cycle": CYCLE})
    if not data or not data.get("results"):
        return None
    return data["results"][0]


# Composition of receipts, for the "Where the money came from" panel.
#
# /committee/{id}/totals/ is already fetched for the headline cards, and its
# response carries the whole breakdown -- we were keeping four fields and
# discarding the rest. Total raised minus total from individuals was leaving a
# large unexplained remainder on the page (Clay Fuller: $1.85M raised, $1.08M
# from individuals, $766K unaccounted for), which is exactly the PAC/party/
# transfer money a reader most wants named. No extra API call: same endpoint,
# same response, more of it kept.
#
# Stored as raw components rather than pre-summed groups so the renderer can
# regroup without a data regeneration, and so the "Other" row can be derived
# as receipts - sum(components). That remainder is load-bearing: if the FEC
# renames or drops a field, the money lands in "Other" instead of silently
# vanishing from a breakdown that claims to account for all receipts.
FUNDING_FIELDS = (
    ("individualItemized",   "individual_itemized_contributions"),
    ("individualUnitemized", "individual_unitemized_contributions"),
    ("pac",                  "other_political_committee_contributions"),
    ("party",                "political_party_committee_contributions"),
    ("transfers",            "transfers_from_other_authorized_committee"),
    ("candidateSelf",        "candidate_contribution"),
    ("candidateLoans",       "loans_received_from_candidate"),
    ("otherLoans",           "other_loans_received"),
    ("offsets",              "offsets_to_operating_expenditures"),
    ("otherReceipts",        "other_receipts"),
)


def funding_breakdown(totals):
    """Receipt components from a committee/candidate totals response.

    Zero and absent components are omitted rather than stored as 0 -- across 266
    candidates most of these fields are empty, and the renderer treats a missing
    key and a zero identically. Returns {} when nothing is present, so callers
    can skip the key entirely.
    """
    out = {}
    for key, field in FUNDING_FIELDS:
        val = totals.get(field)
        if val:
            out[key] = round(val)
    return out


# Numeric fields read off a totals response. Summed across a candidacy's
# authorized committees; everything else in the response (cycle, ids, flags) is
# meaningless to add, so it is left alone rather than summed blindly.
SUMMABLE_FIELDS = (
    "receipts", "disbursements",
    "last_cash_on_hand_end_period", "cash_on_hand_end_period",
    "individual_itemized_contributions", "individual_unitemized_contributions",
) + tuple(field for _, field in FUNDING_FIELDS)


def sum_committee_totals(totals_list):
    """Add several committees' totals into one response-shaped dict.

    Matches how FEC's candidate page aggregates: a plain sum, with no attempt to
    net out transfers between the candidate's own committees. Verified against
    Mike Collins — $9,290,371.80 + $959,344.49 = $10,249,716.29, the figure his
    FEC page shows to the cent.

    coverage_end_date is a date, not an amount: the latest one wins, since that
    is the reporting date the combined figure runs through.
    """
    totals_list = [t for t in totals_list if t]
    if not totals_list:
        return None
    if len(totals_list) == 1:
        return totals_list[0]

    merged = {}
    for field in SUMMABLE_FIELDS:
        values = [t.get(field) for t in totals_list]
        present = [v for v in values if isinstance(v, (int, float))]
        if present:
            merged[field] = sum(present)
    ends = [t.get("coverage_end_date") for t in totals_list if t.get("coverage_end_date")]
    if ends:
        merged["coverage_end_date"] = max(ends)
    return merged

def get_candidate_totals(candidate_id):
    """Fallback when principal_committees is missing from the candidate list response.
    /candidate/{id}/totals/ returns per-cycle financials without needing a committee ID.
    Field names differ from committee totals (no last_cash_on_hand_end_period).
    """
    data = fec_get(f"/candidate/{candidate_id}/totals/", {"cycle": CYCLE})
    if not data or not data.get("results"):
        return None
    return data["results"][0]


# Employer strings are free text typed by individual donors, so one employer
# arrives in several spellings ("GOOGLE", "GOOGLE, INC.") and the FEC returns
# them uppercased. The old code called .title() and deduped on a key that kept
# commas and periods, which produced two visible defects on every finance panel:
# Ossoff's top-donor table listed "Google" and "Google, Inc." as separate rows,
# and .title() destroyed acronym casing ("Cvs", "Ibm", "At&T") while
# over-capitalizing small words ("University Of California").
#
# Nothing here expands an acronym into a company name: an employer field has no
# authoritative registry to resolve against, unlike a stock ticker. These are
# spelling and casing rules only.

_LEGAL_SUFFIX_RE = re.compile(
    r'\b(INC|INCORPORATED|LLC|LLP|LP|LTD|CO|COMPANY|CORP|CORPORATION|PLC|PC|PA)\b')

# Lowercased inside a name, never as its first word.
_SMALL_WORDS = {'of', 'and', 'the', 'for', 'at', 'in', 'on', 'to', 'a', 'an'}

# A personal name's suffix. "Jr" has no vowel, so the initialism rule below
# would otherwise shout it: "Benton J. Mathis, JR.". Roman numerals do carry a
# vowel and need the opposite nudge, since .title() flattens III to "Iii".
_NAME_SUFFIXES = {'jr': 'Jr', 'sr': 'Sr', 'ii': 'II', 'iii': 'III', 'iv': 'IV'}

# Stylings no rule can derive. Keyed by employer_key(). Deliberately tiny -- an
# entry belongs here only when a name actually in the data cannot be cased
# correctly by the rules below, not as a general alias list.
_STYLED_NAMES = {
    'ATT':   'AT&T',
    'FEDEX': 'FedEx',
    'IBM':   'IBM',
}


def employer_key(name):
    """Canonical key that merges spellings of one employer.

    Punctuation is dropped and a trailing legal suffix removed, so "Google",
    "Google, Inc." and "GOOGLE LLC" share a key. Used for merging and for the
    skip-list test, so "Self-Employed" and "SELF EMPLOYED" are one entry.
    """
    k = re.sub(r'[^A-Z0-9&\s]', ' ', (name or '').upper())
    k = _LEGAL_SUFFIX_RE.sub(' ', k)
    return re.sub(r'[\s&]', '', k)


def display_employer(name):
    """Title-case an employer name without mangling acronyms.

    A token with no vowel is an initialism (CVS, KPMG, DFCS, TD, BGR Group),
    so it stays uppercase. Small words lowercase unless they lead. The
    possessive that .title() capitalized -- "Buckhead'S Finest" -- and the
    "Mc" prefix it flattened -- "Mcmullen" -- are both restored.

    Known limit: an initialism that contains a vowel (IBM, AFGE, ACOG, CPAs)
    is indistinguishable by rule from a short word like Apple or Emory, so it
    title-cases to "Afge". Separating them needs a word list, which is a
    maintained artifact this deliberately does without; _STYLED_NAMES covers
    the whole-string cases worth pinning by hand.
    """
    styled = _STYLED_NAMES.get(employer_key(name))
    if styled:
        return styled

    words = []
    for i, token in enumerate((name or '').split()):
        letters = re.sub(r'[^A-Za-z]', '', token)
        if letters.lower() in _NAME_SUFFIXES:
            words.append(token.replace(letters, _NAME_SUFFIXES[letters.lower()]))
        elif letters and not re.search(r'[AEIOUY]', letters.upper()):
            words.append(token.upper())            # CVS, IBM, KPMG, TD
        elif i and token.lower() in _SMALL_WORDS:
            words.append(token.lower())            # University of California
        else:
            words.append(token.title())
    out = ' '.join(words)

    # .title() uppercases the letter after any apostrophe ("Buckhead'S").
    out = re.sub(r"(\w)'S\b", lambda m: m.group(1) + "'s", out)
    # ...and leaves a Scots-Irish prefix flat ("Mcmullen" -> "McMullen").
    out = re.sub(r'\bMc([a-z])', lambda m: 'Mc' + m.group(1).upper(), out)
    return out


def merge_top_employers(rows):
    """Collapse spellings of one employer into a single row, summing the money.

    The variant with the largest total supplies the display name -- its
    spelling is the one most donors used -- and the name itself breaks a tie so
    the result never depends on API ordering. Totals and donor counts are
    summed: the old code kept the first variant and silently discarded every
    later one, which dropped $86K of Ossoff's Google money and 240 of its
    donors rather than merging them.

    `rows` are {'employer', 'total', 'count'} dicts carrying raw upstream
    spellings. Returns display-cased rows re-sorted by total, since merging
    changes the ranking.
    """
    merged = {}
    for row in rows:
        key = employer_key(row['employer'])
        entry = merged.get(key)
        if entry is None:
            merged[key] = {'employer': row['employer'], 'total': row['total'],
                           'count': row['count'], 'best': row['total']}
            continue
        entry['total'] += row['total']
        entry['count'] += row['count']
        if (row['total'], row['employer']) > (entry['best'], entry['employer']):
            entry['employer'], entry['best'] = row['employer'], row['total']

    out = [{'employer': display_employer(e['employer']),
            'total': e['total'], 'count': e['count']} for e in merged.values()]
    out.sort(key=lambda e: (-e['total'], e['employer']))
    return out


def get_top_employers(committee_ids):
    """Top donor employers across ALL of a candidacy's authorized committees.

    Takes a list, because the money does: merging the raw rows before ranking
    means an employer that gave to both the principal committee and a nominee
    fund appears once with the combined total, rather than twice at half size or
    once at whichever committee happened to be read. merge_top_employers()
    already collapses spelling variants, so it collapses across committees too.
    """
    rows = []
    for committee_id in committee_ids:
        rows.extend(_employer_rows(committee_id))
    return merge_top_employers(rows)[:TOP_N]


def _employer_rows(committee_id):
    """Raw, unmerged employer rows for one committee."""
    # schedule_a uses two_year_transaction_period, not cycle
    data = fec_get("/schedules/schedule_a/by_employer/", {
        "committee_id":              committee_id,
        "two_year_transaction_period": CYCLE,
        "per_page":                  FETCH_N,
        "sort":                      "-total",
        "sort_hide_null":            "true",
    })
    if not data:
        return []

    # Not employers: a donor who gave a job title, or no answer at all.
    _SKIP_RAW = {"NONE", "N/A", "NA", "NULL", "INFORMATION REQUESTED",
                 "NOT EMPLOYED", "UNEMPLOYED", "HOMEMAKER", "SELF",
                 "SELF-EMPLOYED", "RETIRED", "STUDENT", "VARIOUS",
                 "ATTORNEY", "ATTY", "CEO", "OWNER", "CITY", "CONSULTANT"}
    SKIP_EMPLOYERS = {employer_key(s) for s in _SKIP_RAW}

    rows = []
    for r in data.get("results", []):
        emp = (r.get("employer") or "").strip()
        if not emp or employer_key(emp) in SKIP_EMPLOYERS:
            continue
        rows.append({
            "employer": emp,
            "total":    round(r.get("total", 0)),
            "count":    r.get("count", 0),
        })

    return rows


def normalize_name(name):
    """Normalize FEC name to a lookup key matching JS normalizeName() in candidate.html.
    FEC names are typically 'LAST, FIRST MIDDLE' or 'LAST, FIRST "NICK"'.
    Skips single-char initials (e.g. "OSSOFF, T. JONATHAN" -> "jonathan ossoff").
    Note: FEC formal names often differ from display names (Michael vs Mike), so
    byNormalizedName is a last-resort fallback; byBioguideId and byDistrict are preferred.
    """
    n = name.lower()
    n = re.sub(r'["\'].*?["\']', '', n)                  # strip quoted nicknames
    n = re.sub(r'\b(jr|sr|ii|iii|iv|esq)\.?\b', '', n)   # strip suffixes
    n = re.sub(r'\b(dr|mr|mrs|ms)\.?\b', '', n)          # strip honorifics
    n = re.sub(r'[^a-z\s,]', '', n).strip()
    if ',' in n:
        last, first = n.split(',', 1)
        # Skip single-char initials so "T. JONATHAN" -> "jonathan", not "t"
        tokens = [t for t in first.strip().split() if len(t) > 1]
        first_name = tokens[0] if tokens else (first.strip().split() or [''])[0]
        n = f"{first_name} {last.strip()}"
    else:
        # "First Middle Last" -> "first last". Without this the two sides of the
        # mirror disagree on every display-style name: races.json carries
        # "Tricia R. Pridemore", which used to normalize to a three-token key
        # that no two-token index entry could ever match.
        # See CODEBASE-REVIEW-2026-08-18.md finding 1.3.
        tokens = n.split()
        if len(tokens) > 2:
            named = [t for t in tokens if len(t) > 1] or tokens
            n = f"{named[0]} {named[-1]}" if len(named) > 1 else (named[0] if named else '')
    return ' '.join(n.split())


def preferred_filing(cids, candidates):
    """Pick ONE filing from several for the same person, deterministically.

    A sitting House member running for Senate holds two live FEC candidate ids in
    the same cycle (2026: Buddy Carter C001103 and Mike Collins C001129 each have
    an H and an S filing, both pointing at the same principal committee). The
    single-valued byBioguideId/byNormalizedName indexes can hold only one, and
    assigning them in the fetch loop made the winner whichever the FEC listed
    last — i.e. a function of the `for office in ("H","S")` order and the API's
    name sort, not of anything about the candidate. Flip either and the published
    index silently changes meaning.

    The rule, in order: a filing with real activity beats a dormant registration;
    the later coverage end date beats an older one; the more recently filed
    candidacy beats one that has not filed since an earlier cycle; the smallest
    candidate id breaks what remains. The last step carries no meaning — it is
    there so the output is a function of the data alone. Callers that need the
    filing for a SPECIFIC office must not rely on this: use byBioguideIdAll /
    byDistrict and check `office` (as findFecMatch() in campaign-finance.js does).

    The lastFileDate step is what decides the dual-filer case, and nothing before
    it can: both ids draw their totals from the one shared committee, so activity
    and coverage end date are identical by construction. Without it the winner
    fell to the id sort, which picked Carter's House filing (H4GA01039 <
    S6GA00374) — the seat he is leaving, whose FEC page reads "nothing filed" for
    the cycle because every 2026 document is filed under the Senate candidacy.
    """
    def sort_key(cid):
        e = candidates.get(cid, {})
        active = e.get("totalRaised") is not None or bool(e.get("coverageEndDate"))
        return (0 if active else 1,
                _newest_first(e.get("coverageEndDate")),
                _newest_first(e.get("lastFileDate")),
                cid)
    return sorted(cids, key=sort_key)[0]


def _invert(text):
    """Sort an ISO date string descending inside an ascending tuple key."""
    return tuple(-ord(c) for c in text)


def _newest_first(date_text):
    """Ascending sort key that puts the newest date first and no date last.

    _invert() alone can't do this: an absent date inverts to the empty tuple,
    which sorts ahead of every real one, so a filing with no date would beat a
    filing that has one. The leading flag keeps the unknowns at the back.
    """
    return (0, _invert(date_text)) if date_text else (1, ())


def normalize_last(name):
    """Extract normalized last name from FEC 'LAST, FIRST' format.
    Used for bioguide enrichment and the byDistrict lastName field.
    """
    last = name.split(',')[0] if ',' in name else name.split()[-1] if name.split() else ''
    return re.sub(r'[^a-z]', '', last.lower())


def district_key(office, district):
    """Normalize a seat to ('H', '13') / ('S', '') so member and FEC records compare.
    FEC returns districts zero-padded ('08') and uses '00'/'' for Senate seats.
    """
    office = (office or '').upper()[:1]
    d = str(district if district is not None else '').strip().lstrip('0')
    if office == 'S':
        d = ''
    return (office, d)


def load_fec_bioguide_crosswalk():
    """Return {fec_candidate_id: bioguide_id} from congress-legislators.

    congress-legislators is a canonical, human-maintained mapping of each
    member's bioguide ID to their FEC candidate IDs (id.fec is a list — one per
    office/campaign across a career). Inverting it gives a deterministic
    FEC->bioguide lookup keyed on the FEC candidate_id, which is strictly better
    than the surname+seat heuristic in load_bioguide_map(): because the key is
    the candidate ID itself, a challenger (who has their own distinct FEC ID)
    can never inherit an incumbent's bioguide, no matter how names or districts
    line up.

    Returns {} on any failure, so the build degrades to the heuristic rather
    than breaking. The crosswalk is an accuracy upgrade, not a hard dependency.
    """
    data = fetch_json(LEGISLATORS_URL, label="congress-legislators")
    if not data:
        print("  (congress-legislators unavailable -- FEC ID crosswalk skipped)")
        return {}
    crosswalk = {}
    for person in data:
        ids = person.get("id") or {}
        bioguide = ids.get("bioguide")
        if not bioguide:
            continue
        for fec_id in (ids.get("fec") or []):
            crosswalk[fec_id] = bioguide
    print(f"  Loaded FEC->bioguide crosswalk: {len(crosswalk)} FEC IDs "
          f"from congress-legislators")
    return crosswalk


def load_bioguide_map():
    """Build (office, district, last-name) -> bioguide_id map for GA members.

    The FEC API does not return bioguide_id in candidate list responses, so we cross-
    reference against our own Congress member data to enrich incumbent candidates.

    Keyed by seat as well as surname: Georgia currently seats two Representatives
    named Scott (Austin, GA-8 and David, GA-13). A surname-only map collapsed them,
    stamped one bioguide onto every "Scott" in the FEC file — including challengers —
    and left the last one written wins, so David Scott's page showed a challenger's
    fundraising totals.
    """
    members_path = os.path.join(os.path.dirname(OUTPUT_FILE) or '.', '..', 'assets', 'data', 'current-members.json')
    for path in [members_path, 'assets/data/current-members.json']:
        if os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
            result = {}
            for m in data.get('members', []):
                # current-members.json stores state as full name ("Georgia"), not abbreviation
                if m.get('state') not in ('GA', 'Georgia'):
                    continue
                last = re.sub(r'[^a-z]', '', (m.get('lastName') or '').lower())
                bioguide = m.get('bioguideId') or ''
                if not (last and bioguide):
                    continue
                terms   = (m.get('terms') or {}).get('item') or []
                chamber = (terms[-1].get('chamber') if terms else '') or ''
                office  = 'S' if 'senate' in chamber.lower() else 'H'
                o, d = district_key(office, m.get('district'))
                result[(o, d, last)] = bioguide
            print(f"  Loaded bioguide map: {len(result)} GA members from {path}")
            return result
    print("  (current-members.json not found -- bioguide enrichment skipped)")
    return {}


def main():
    if not API_KEY:
        print("Error: FEC_API_KEY environment variable not set")
        sys.exit(1)

    print(f"\nLoading FEC->bioguide crosswalk (congress-legislators)...")
    fec_crosswalk = load_fec_bioguide_crosswalk()

    print(f"\nLoading GA member bioguide map...")
    bioguide_map = load_bioguide_map()

    print(f"\nFetching GA congressional candidates from FEC (cycle {CYCLE})...")
    raw_candidates = get_ga_candidates()
    print(f"  Total: {len(raw_candidates)} candidates found")
    if not raw_candidates:
        print("Error: no candidates returned -- aborting to avoid overwriting good data")
        sys.exit(1)

    output_candidates = {}
    # Keyed to LISTS while we fetch: one person can hold several filings in a cycle
    # (a House member running for Senate), and which one a single-valued index should
    # publish is a decision for preferred_filing(), not for whatever order the FEC
    # happened to return. Reduced after the loop.
    by_bioguide_all = {}
    by_name_all     = {}
    # byDistrict maps "H{n}" or "S" -> [candidate_ids], keyed off the API's `district`
    # field so a candidate who changed districts lands in the seat they now contest.
    # candidate.html and member.html use this for district-scoped last-name matching, which
    # handles formal vs. nickname differences (e.g. FEC "MICHAEL" matching display name "Mike").
    by_district  = {}
    unbucketed   = []   # House candidates the FEC gives no district for
    matched_crosswalk = 0   # bioguide resolved via congress-legislators
    matched_heuristic = 0   # bioguide resolved via surname+seat fallback

    for i, c in enumerate(raw_candidates, 1):
        cid      = c.get("candidate_id")
        if not cid:
            continue

        name       = c.get("name", "")
        office     = c.get("office", "")        # "H" or "S"
        district   = c.get("district", "")
        bioguide   = c.get("bioguide_id") or ""

        # Always ask, rather than trusting the list response's
        # `principal_committees`: that field carries only P-designated
        # committees, so an authorized nominee fund (designation A) is invisible
        # in it, and reading it alone is what under-reported Mike Collins by
        # $959,344.49. One call per candidate buys the complete set.
        time.sleep(DELAY)
        found = get_candidate_committees(cid)
        authorized = found["authorized"]
        related = found["related"]
        committee = authorized[0] if authorized else None   # the principal, for identity
        committee_id = committee["id"] if committee else None

        # FEC doesn't return bioguide_id in list responses; enrich it ourselves.
        # Primary: the congress-legislators crosswalk, keyed on the FEC candidate_id
        # itself — deterministic, and structurally immune to same-surname conflation.
        if not bioguide and fec_crosswalk:
            bioguide = fec_crosswalk.get(cid, "")
            if bioguide:
                matched_crosswalk += 1
        # Fallback: seat + surname against current-members.json, for incumbents the
        # crosswalk doesn't cover yet (e.g. a just-seated member not in it). Keyed on
        # seat as well as surname so same-surname members aren't conflated.
        if not bioguide and bioguide_map:
            o, dnum = district_key(office, district)
            bioguide = bioguide_map.get((o, dnum, normalize_last(name)), "")
            if bioguide:
                matched_heuristic += 1

        print(f"  [{i}/{len(raw_candidates)}] {name} ({cid}){' -> ' + bioguide if bioguide else ''}")

        entry = {
            "candidateId": cid,
            "name":        name,
            "office":      office,
            "district":    district,
            "lastName":    normalize_last(name),   # stored for district+lastName lookup in candidate.html
            "fecUrl":      f"https://www.fec.gov/data/candidate/{cid}/",
            # Date of this filing's most recent FEC document. Two filings for the
            # same person share a committee and therefore share every dollar
            # figure, so this is the only field that tells the live candidacy from
            # the dormant one — see preferred_filing().
            "lastFileDate": c.get("last_file_date") or "",
        }
        if bioguide:
            entry["bioguideId"] = bioguide
        if committee_id:
            entry["committeeId"] = committee_id
            # Carried so the page can name the filer when it is not the
            # candidate's own principal campaign committee — see
            # get_candidate_committees() and filingCommitteeNote() in
            # campaign-finance.js.
            if committee.get("name"):
                entry["committeeName"] = committee["name"]
            if committee.get("designation"):
                entry["committeeDesignation"] = committee["designation"]
            # Only when the figures span more than one committee, so the page can
            # say so the way FEC's own candidate page does ("Data is included
            # from these committees"). Absent for the ordinary single-committee
            # candidate, which is nearly all of them.
            if len(authorized) > 1:
                entry["contributingCommittees"] = [{
                    "id":          a["id"],
                    "name":        a["name"],
                    "designation": a["designation"],
                    "fecUrl":      f"https://www.fec.gov/data/committee/{a['id']}/",
                } for a in authorized]
        elif related:
            # No campaign money to show, but we know where FEC files what money
            # there is. noFilingHtml() turns this into a link rather than leaving
            # the reader with a statewide search box.
            entry["relatedCommittee"] = {
                "id":          related["id"],
                "name":        related["name"],
                "designation": related["designation"],
                "fecUrl":      f"https://www.fec.gov/data/committee/{related['id']}/",
            }

        if committee_id:
            per_committee = []
            for a in authorized:
                time.sleep(DELAY)
                per_committee.append(get_committee_totals(a["id"]))
            totals = sum_committee_totals(per_committee)
            if totals:
                entry["totalRaised"]      = totals.get("receipts")
                entry["totalSpent"]       = totals.get("disbursements")
                entry["cashOnHand"]       = (totals.get("last_cash_on_hand_end_period")
                                             or totals.get("cash_on_hand_end_period"))
                entry["coverageEndDate"]  = totals.get("coverage_end_date", "")
                # individual_itemized + individual_unitemized = total from individuals
                itemized   = totals.get("individual_itemized_contributions") or 0
                unitemized = totals.get("individual_unitemized_contributions") or 0
                if itemized or unitemized:
                    entry["totalIndividual"] = round(itemized + unitemized)
                funding = funding_breakdown(totals)
                if funding:
                    entry["funding"] = funding

            time.sleep(DELAY)
            entry["topEmployers"] = get_top_employers([a["id"] for a in authorized])
        else:
            # principal_committees missing from list response — fall back to candidate totals
            time.sleep(DELAY)
            totals = get_candidate_totals(cid)
            if totals:
                entry["totalRaised"]     = totals.get("receipts")
                entry["totalSpent"]      = totals.get("disbursements")
                # candidate totals uses cash_on_hand_end_period; try both field variants
                entry["cashOnHand"]      = (totals.get("last_cash_on_hand_end_period")
                                            or totals.get("cash_on_hand_end_period"))
                entry["coverageEndDate"] = totals.get("coverage_end_date", "")
                # /candidate/{id}/totals/ carries the same receipt-component
                # field names as the committee endpoint, so the same breakdown
                # is available on this fallback path.
                funding = funding_breakdown(totals)
                if funding:
                    entry["funding"] = funding
            entry["topEmployers"] = []

        output_candidates[cid] = entry

        if bioguide:
            by_bioguide_all.setdefault(bioguide, []).append(cid)

        key = normalize_name(name)
        if key:
            by_name_all.setdefault(key, []).append(cid)

        # Bucket by the seat the candidate is actually contesting, taken from the API's
        # `district` field. The FEC candidate ID encodes a district too, but it is the seat
        # they first filed under and does not change when they switch districts — e.g.
        # Marjorie Taylor Greene's ID encodes 06 while she sat for GA-14, which filed her in
        # the wrong bucket and broke the district+surname fallback in candidate.html.
        o, dnum = district_key(office, district)
        if o == "S":
            dist_key = "S"
        elif o == "H" and dnum:
            dist_key = f"H{dnum}"
        else:
            # No usable district (FEC reports "00" for filings without one). Leaving them
            # out is deliberate: the old ID-derived key put them in a real district's
            # bucket, where a surname match could attribute them to someone else's seat.
            dist_key = None
            unbucketed.append(f"{name} ({cid}, district={district!r})")
        if dist_key:
            by_district.setdefault(dist_key, []).append(cid)

    # Reduce the multi-filing keys to the published single-valued indexes, and keep
    # the full lists too: a person's OTHER filings are real and downstream joins need
    # them (build_id_crosswalk.py records every FEC id a person holds, so a dual filer
    # cannot end up with two vgIds depending on which id each code path picked).
    by_bioguide = {b: preferred_filing(cids, output_candidates)
                   for b, cids in by_bioguide_all.items()}
    by_name     = {k: preferred_filing(cids, output_candidates)
                   for k, cids in by_name_all.items()}
    by_bioguide_sorted = {b: sorted(cids) for b, cids in by_bioguide_all.items()}
    by_name_sorted     = {k: sorted(cids) for k, cids in by_name_all.items()}

    multi = {b: c for b, c in by_bioguide_sorted.items() if len(c) > 1}
    if multi:
        print("")
        print(f"{len(multi)} member(s) hold more than one FEC filing this cycle "
              f"(byBioguideId publishes the preferred one; byBioguideIdAll has all):")
        for b, cids in sorted(multi.items()):
            picks = ", ".join(f"{c} [{output_candidates[c].get('office','?')}]" for c in cids)
            print(f"  - {b}: {picks} -> {by_bioguide[b]}")

    output = {
        "metadata": {
            "generatedAt":    datetime.now(timezone.utc).isoformat(),
            "cycle":          CYCLE,
            "source":         "FEC API (api.open.fec.gov)",
            "totalCandidates": len(output_candidates),
        },
        "candidates":       output_candidates,
        "byBioguideId":     by_bioguide,
        "byBioguideIdAll":  by_bioguide_sorted,
        "byNormalizedName": by_name,
        "byNormalizedNameAll": by_name_sorted,
        "byDistrict":       by_district,
    }

    print(f"\nbioguide matches: {matched_crosswalk} via congress-legislators crosswalk, "
          f"{matched_heuristic} via surname+seat fallback ({len(by_bioguide)} incumbents total)")

    if unbucketed:
        print(f"\n{len(unbucketed)} House candidate(s) had no usable district and are absent "
              f"from byDistrict (name lookup still finds them):")
        for u in unbucketed:
            print(f"  - {u}")

    write_json_atomic(OUTPUT_FILE, output, indent=2)

    size_kb = os.path.getsize(OUTPUT_FILE) // 1024
    print(f"\nDone. {len(output_candidates)} candidates | {size_kb} KB -> {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
