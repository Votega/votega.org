#!/usr/bin/env python3
"""
Parse an official Georgia SoS "Total Votes Results" CSV export into the
`SECTIONS` JSON structure consumed by the shared election-results layout
(_layouts/election_results.html).

This is the single builder for every results page (primary, runoff, special,
general). Presentation — status labels, unofficial/certified, notice text — is
declared per page in front matter, NOT here; this script only shapes the data.

Usage:
    python scripts/build_results_json.py <csv_path> <data_key>

    <data_key> is the base name written to _data/election_results/<data_key>.json
    and referenced by a page's `results_data:` front matter.

Examples:
    python scripts/build_results_json.py _sources/election_results/ga-primary-results-official.csv ga-primary-results
    python scripts/build_results_json.py _sources/election_results/ga-primary-runoff-results.csv ga-primary-runoff-results
    python scripts/build_results_json.py _sources/election_results/ga-special-2026-results-official.csv ga-special-2026-results

CSV columns: Office Name, Contest ID, Ballot Name, Choice ID, Party, Total.
Jungle/nonpartisan special contests: leave the Party column blank and keep the
"(Dem)"/"(Rep)" suffix in the ballot name — the contest renders as one
non-partisan card with party labels on each candidate.
"""

import csv
import json
import zipfile
import xml.etree.ElementTree as ET
from lib.atomic_io import write_json_atomic
import os
import re
import sys
from collections import Counter, OrderedDict
from datetime import datetime, timezone

HERE = os.path.dirname(__file__)
OUT_DIR = os.path.join(HERE, '..', '_data', 'election_results')
# data_key -> {epoch, iso} build time, read by _layouts/election_results.html
# for the "Last updated" stamp. The layout renders `epoch`; see
# record_build_time() for why it lives here and why the integer is the one used.
STAMP_PATH = os.path.join(HERE, '..', '_data', 'results_updated.json')

# Statewide race display names, in desired order
STATEWIDE_ORDER = [
    'US Senate', 'Governor', 'Lieutenant Governor', 'Secretary of State',
    'Attorney General', 'Commissioner of Agriculture', 'Commissioner of Insurance',
    'State School Superintendent', 'Commissioner of Labor', 'PSC - District 3',
    'PSC - District 5',
]
STATEWIDE_MAP = {
    'us senate': 'US Senate', 'governor': 'Governor',
    'lieutenant governor': 'Lieutenant Governor', 'secretary of state': 'Secretary of State',
    'attorney general': 'Attorney General', 'commissioner of agriculture': 'Commissioner of Agriculture',
    'commissioner of insurance': 'Commissioner of Insurance',
    'state school superintendent': 'State School Superintendent',
    'commissioner of labor': 'Commissioner of Labor',
    'psc - district 3': 'PSC - District 3', 'psc - district 5': 'PSC - District 5',
}


def classify(office_name):
    on = office_name.lower()
    for key in STATEWIDE_MAP:
        if on.startswith(key):
            return 'statewide'
    if on.startswith('psc'):
        return 'statewide'
    if 'us house of representatives' in on:
        return 'us-house'
    if 'state senate' in on:
        return 'state-senate'
    if 'state house of representatives' in on:
        return 'state-house'
    if ('judge' in on or 'justice' in on or 'court of appeals' in on or
            'supreme court' in on or 'district attorney' in on):
        return 'courts'
    # Statewide ballot questions. The names are the Secretary of State's own, taken
    # from the 2024 general export: "Proposed Constitutional Amendment 1" and
    # "Statewide Referendum Question A", each with Yes/No ballot options and, unhelpfully,
    # contestType "Candidate" — so the office name is the only thing to key on.
    # Without this they fell into the `return None` below with the party straw polls,
    # and three constitutional amendments on the 2026 ballot would have reported no
    # result at all while every other contest filled in.
    if on.startswith('proposed constitutional amendment') or on.startswith('statewide referendum'):
        return 'measures'
    return None  # county party questions etc. — skip


def base_display_name(office_name):
    name = re.sub(r'\s*/.*', '', office_name).strip()
    return re.sub(r'\s*-\s*(Rep|Dem)\s*$', '', name, flags=re.IGNORECASE).strip()


def district_number(display_name):
    m = re.search(r'District\s+(\d+)', display_name, re.IGNORECASE)
    return int(m.group(1)) if m else 0


def statewide_display(office_name):
    on = office_name.lower()
    for key, display in STATEWIDE_MAP.items():
        if on.startswith(key):
            return display
    return base_display_name(office_name)


def courts_display(office_name):
    name = base_display_name(office_name)
    return re.sub(r'^(Judge|Justice)\s*-\s*', '', name, flags=re.IGNORECASE).strip()


def parse_candidate_name(ballot_name):
    incumbent = bool(re.search(r'\(I\)', ballot_name))
    name = re.sub(r'\s*\(I\)\s*', ' ', ballot_name)
    return re.sub(r'\s+', ' ', name).strip(), incumbent


def party_from_csv(party_str):
    p = (party_str or '').strip().upper()
    return {'REP': 'rep', 'DEM': 'dem'}.get(p, 'np')


# --- Reading the export ------------------------------------------------------
# The Secretary of State's "Total Votes Results" export is an XLSX WORKBOOK, not
# a CSV: three sheets ("Total Votes", "Total Votes by Group", "County Results"),
# of which the first has exactly the six columns this script has always parsed.
# The CSVs in _sources/election_results/ are that sheet saved out by hand, which
# is why four elections shipped without this mattering — and why election night
# would have been the first time anyone discovered it, with the file in hand and
# polls closed.
#
# Read with the standard library (zipfile + ElementTree) rather than openpyxl,
# because everything under scripts/ runs on a bare runner with no pip install
# (see .github/workflows/run-script-tests.yml) and the publish path must not be
# the one thing that needs a dependency installed at 9pm.
XLSX_NS = {
    'main': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
    'rel': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'pkgrel': 'http://schemas.openxmlformats.org/package/2006/relationships',
}
RESULTS_SHEET = 'Total Votes'


def _col_index(ref):
    """'C7' -> 2. Cells are addressed, not ordered: a blank cell is simply absent
    from the XML, so reading cells in document order shifts every later column
    left and silently puts vote totals in the Party column."""
    letters = ''.join(ch for ch in ref if ch.isalpha())
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch.upper()) - 64)
    return n - 1


def _shared_strings(zf):
    try:
        root = ET.fromstring(zf.read('xl/sharedStrings.xml'))
    except KeyError:
        return []
    out = []
    for si in root.findall('main:si', XLSX_NS):
        out.append(''.join(t.text or '' for t in si.iter(f'{{{XLSX_NS["main"]}}}t')))
    return out


def _sheet_part(zf, want):
    """Resolve a sheet NAME to its part path. Sheet order in the zip is not the
    workbook's tab order, so picking 'sheet1.xml' is a guess; the county sheet
    has the same first columns and would parse into plausible nonsense."""
    wb = ET.fromstring(zf.read('xl/workbook.xml'))
    rels = ET.fromstring(zf.read('xl/_rels/workbook.xml.rels'))
    target = {r.get('Id'): r.get('Target') for r in rels.findall('pkgrel:Relationship', XLSX_NS)}
    sheets = []
    for sh in wb.findall('main:sheets/main:sheet', XLSX_NS):
        rid = sh.get(f'{{{XLSX_NS["rel"]}}}id')
        sheets.append((sh.get('name'), target.get(rid)))
    for name, part in sheets:
        if (name or '').strip().lower() == want.strip().lower() and part:
            break
    else:
        name, part = sheets[0] if sheets else (None, None)
        if not part:
            raise ValueError('workbook has no readable sheet')
        print(f"  WARNING: no '{want}' sheet; reading '{name}' instead")
    if part.startswith('/'):
        return part.lstrip('/')
    return part if part.startswith('xl/') else f'xl/{part}'


def rows_from_xlsx(path, sheet=RESULTS_SHEET):
    with zipfile.ZipFile(path) as zf:
        strings = _shared_strings(zf)
        part = _sheet_part(zf, sheet)
        root = ET.fromstring(zf.read(part))
        for row in root.iter(f'{{{XLSX_NS["main"]}}}row'):
            cells = {}
            for c in row.findall('main:c', XLSX_NS):
                ref = c.get('r') or ''
                idx = _col_index(ref) if ref else len(cells)
                if c.get('t') == 's':
                    v = c.find('main:v', XLSX_NS)
                    try:
                        text = strings[int(v.text)] if v is not None and v.text else ''
                    except (ValueError, IndexError):
                        text = ''
                elif c.get('t') == 'inlineStr':
                    is_el = c.find('main:is', XLSX_NS)
                    text = ''.join(t.text or '' for t in is_el.iter(f'{{{XLSX_NS["main"]}}}t')) if is_el is not None else ''
                else:
                    v = c.find('main:v', XLSX_NS)
                    text = (v.text or '') if v is not None else ''
                cells[idx] = text.strip()
            if not cells:
                continue
            width = max(cells) + 1
            yield [cells.get(i, '') for i in range(width)]


def detect_delimiter(path):
    """Sniff delimiter — handles both tab-separated exports and comma CSV."""
    with open(path, newline='', encoding='utf-8-sig') as f:
        sample = f.read(4096)
    return '\t' if sample.count('\t') > sample.count(',') else ','


def is_xlsx(path):
    """By content, not extension: an export saved with the wrong suffix is the
    kind of thing that happens once, at speed, on a deadline."""
    try:
        with open(path, 'rb') as fh:
            return fh.read(4) == b'PK\x03\x04' and zipfile.is_zipfile(path)
    except OSError:
        return False


def read_rows(path):
    """Every row of the export, as lists of strings, whatever it was saved as."""
    if is_xlsx(path):
        print(f"  Reading XLSX sheet '{RESULTS_SHEET}'")
        yield from rows_from_xlsx(path)
        return
    with open(path, newline='', encoding='utf-8-sig') as f:
        yield from csv.reader(f, delimiter=detect_delimiter(path))


PARTY_SUFFIX = {'rep': 'Rep', 'dem': 'Dem'}
PARTY_SUFFIX_RE = re.compile(r'\((?:rep|dem|republican|democrat(?:ic)?)\w*\)', re.IGNORECASE)


def normalize_mixed_party(contest):
    """A GENERAL-election contest holds both parties under ONE Contest ID — make it read that way.

    In a primary export each party runs its own contest ("US Senate - Rep" /
    US2R, "US Senate - Dem" / US2D), so a contest IS a party and the card's
    party badge and bar colors come straight off the first row. A general
    export does not work that way: Ossoff and Collins share one contest ID,
    with the Party column distinguishing them row by row.

    Read naively, the contest took the party of whichever row the Secretary of
    State happened to list first, so the US Senate card would have been badged
    (and bar-colored) REPUBLICAN with the Democrat inside it — on every federal,
    statewide and legislative race on the November ballot. The primary pages
    never caught it because a primary contest genuinely has one party.

    So: a contest whose rows carry more than one party becomes non-partisan
    (`np`, the neutral card the layout already renders for jungle specials and
    ballot questions) and each candidate keeps their own party as a "(Dem)" /
    "(Rep)" suffix on the ballot name. That is the convention this script's
    docstring already documents for jungle contests, and it is safe for the two
    places that match these names: both `nameKeys()` in
    _layouts/election_results.html and `normalize()` in scripts/lib/race_winners.py
    strip parenthetical suffixes before matching, so candidate-page links and
    winner proposals are unaffected.
    """
    seen = {c.get('party') for c in contest['candidates']} - {'np'}
    if len(seen) < 2:
        return
    contest['party'] = 'np'
    # WHAT 'np' MEANS HERE, which the page has to say differently. A contest with
    # one party is a primary and the card's party badge describes it exactly. A
    # general-election contest has no single party, so it renders as the neutral
    # card — but it is NOT a nonpartisan race, and labelling 274 D-versus-R
    # contests "Nonpartisan" states something false about every race on the
    # ballot. These two fields let the layout tell the difference: drop the badge
    # where the parties are on the candidates instead, and let the Republican and
    # Democrat filters match a card that has one of each on it.
    contest['multiParty'] = True
    order = {'rep': 0, 'dem': 1}
    contest['parties'] = sorted(seen, key=lambda p: (order.get(p, 2), p))
    for cand in contest['candidates']:
        suffix = PARTY_SUFFIX.get(cand.get('party'))
        if suffix and not PARTY_SUFFIX_RE.search(cand['name']):
            cand['name'] = f"{cand['name']} ({suffix})"


def backfill_total_votes(contest):
    """No "Total Votes" row? Sum the candidates rather than report nothing.

    `contest.totalVotes` is not cosmetic: ResultsContest.status() returns
    'no-results' for any contest with a falsy totalVotes, so a contest without
    it renders "Awaiting Results" with the counts hidden — no percentages, no
    bars — however many votes its candidate rows carry. The certified primary
    exports all carry a per-contest "Total Votes" row (554 of them in the May
    export), which is why this has never bitten.

    Election night is the night it would. The unofficial feed is a different
    export from the certified one, and a missing summary row would have failed
    SILENTLY and uniformly: every race on the page reading "Awaiting Results"
    at 9pm while the file on disk held the whole count, with nothing to
    distinguish it from votes not yet reported.

    Summing the candidate rows is also the right denominator, not just a
    fallback: Georgia's majority test (50% + 1, or a December runoff) runs on
    votes cast for candidates, which is what these rows are. A real "Total
    Votes" row always wins — this only fills a zero.
    """
    if contest['totalVotes']:
        return
    summed = sum(c['votes'] for c in contest['candidates'])
    if summed:
        contest['totalVotes'] = summed


# --- The JSON feed ------------------------------------------------------------
# https://results.sos.ga.gov/cdn/results/Georgia/export-<MMDDYYYY><Name>.json
#
# The same results as the XLSX, at a STABLE URL — which is the whole difference
# on election night: the workbook is a generated download with a fresh GUID in
# its name every time, so it can only be fetched by hand, while this can be
# fetched by the publish workflow on a button press. It also carries `createdAt`,
# the moment the Secretary of State built the data, which is a better answer to
# "how old are these numbers" than the moment we built the page from them.
#
# Two differences from the workbook, both handled rather than assumed away:
#   * No per-contest "Total Votes" row — the candidate rows are summed, which is
#     backfill_total_votes()'s job and the right denominator anyway.
#   * It can be SHORT A RACE. Measured on the 11:17pm feed: 273 contests against
#     the workbook's 274, missing District Attorney - Waycross Judicial Circuit.
#     That is exactly what --fill-missing-from is for, and why the election-night
#     workflow leaves it on: the race keeps reading "Awaiting Results" instead of
#     disappearing from the page.
JSON_MARKER_KEYS = {'electionDate', 'results'}


def is_json_export(path):
    try:
        with open(path, 'rb') as fh:
            return fh.read(64).lstrip()[:1] == b'{'
    except OSError:
        return False


def county_reporting(payload):
    """How many of Georgia's 159 counties have reported anything yet.

    WHAT THE FEED DOES NOT HAVE: precincts. `precinctsParticipating` and
    `precinctsReporting` are null on every contest, all night, so the "X% of
    precincts reporting" line every broadcaster runs cannot be built from this
    source at all. The statewide `reportingStatuses` is no better — it still
    read "Not Reported" for all four voting groups with more than a million
    votes already counted, so it is not maintained.

    WHAT IT DOES HAVE: per-county status. Each of the 159 entries in
    `localResults` carries its own four groups (Election Day, Advance Voting,
    Absentee by Mail, Provisional), each Not Reported / Partially Reported /
    Fully Reported / Election Night Complete. A county counts as reporting once
    any group has moved off "Not Reported", or once any vote is counted in it —
    the union, because the two disagree slightly in both directions at the
    edges: measured at 1:16am, 109 counties by status and 107 by votes, the two
    extra being Quitman and Taliaferro, which had marked a group reported before
    any vote landed.

    COUNTIES ARE NOT VOTES, and the page says counties for that reason. Fulton
    alone holds more voters than the fifty smallest counties together, so
    two-thirds of counties reporting is not two-thirds of the vote counted, and
    a percentage here would be read as exactly that. Returns None when the
    source carries no county section at all (the XLSX export does not), so a
    stale figure is never left standing beside fresh numbers.
    """
    locals_ = (payload or {}).get('localResults')
    if not isinstance(locals_, list) or not locals_:
        return None
    reporting = 0
    for county in locals_:
        statuses = county.get('reportingStatuses') or []
        if any((rs.get('status') or 'Not Reported') != 'Not Reported' for rs in statuses):
            reporting += 1
            continue
        if any((opt.get('voteCount') or 0) > 0
               for item in (county.get('ballotItems') or [])
               for opt in (item.get('ballotOptions') or [])):
            reporting += 1
    return {'reporting': reporting, 'total': len(locals_)}


def contests_from_json(path):
    """The feed's ballotItems, in the shape parse_csv produces."""
    with open(path, encoding='utf-8') as fh:
        payload = json.load(fh)
    results = payload.get('results') or {}
    items = results.get('ballotItems') or []
    if not items:
        raise ValueError('the JSON export carries no results.ballotItems')
    contests = OrderedDict()
    for item in items:
        contest_id = str(item.get('id') or '').strip()
        office_name = (item.get('name') or '').strip()
        if not contest_id or not office_name:
            continue
        options = item.get('ballotOptions') or []
        candidates = []
        for opt in options:
            name, incumbent = parse_candidate_name((opt.get('name') or '').strip())
            if not name:
                continue
            candidates.append({
                'name': name,
                'votes': int(opt.get('voteCount') or 0),
                'incumbent': incumbent,
                'party': party_from_csv(opt.get('politicalParty')),
            })
        if not candidates:
            continue
        contests[contest_id] = {
            'office_name': office_name,
            'party': candidates[0]['party'],
            'candidates': candidates,
            'totalVotes': 0,  # summed by backfill_total_votes
        }
    for c in contests.values():
        normalize_mixed_party(c)
        backfill_total_votes(c)
        for cand in c['candidates']:
            cand.pop('party', None)
        c['candidates'].sort(key=lambda x: x['votes'], reverse=True)
    return contests, payload.get('createdAt'), county_reporting(payload)


def parse_csv(path):
    """Parse the export — CSV, TSV or the Secretary of State's XLSX workbook."""
    contests = OrderedDict()
    rows = read_rows(path)
    for _ in rows:  # header
        break
    for row in rows:
        if len(row) < 6:
            continue
        office_name, contest_id, ballot_name = row[0].strip(), row[1].strip(), row[2].strip()
        party_str, total_str = row[4].strip(), row[5].strip()
        if not office_name:
            continue
        try:
            total = int(float(total_str)) if total_str else 0
        except ValueError:
            total = 0

        if ballot_name.lower() == 'total votes':
            if contest_id in contests:
                contests[contest_id]['totalVotes'] = total
            continue

        if contest_id not in contests:
            contests[contest_id] = {
                'office_name': office_name, 'party': party_from_csv(party_str),
                'candidates': [], 'totalVotes': 0,
            }
        name, incumbent = parse_candidate_name(ballot_name)
        contests[contest_id]['candidates'].append(
            {'name': name, 'votes': total, 'incumbent': incumbent,
             'party': party_from_csv(party_str)})

    for c in contests.values():
        normalize_mixed_party(c)
        backfill_total_votes(c)
        for cand in c['candidates']:
            cand.pop('party', None)
        c['candidates'].sort(key=lambda x: x['votes'], reverse=True)
    return contests



def parse_export(path):
    """Parse whichever form the Secretary of State published.

    Returns (contests, source_time, counties): the feed's own `createdAt` and
    its county reporting counts where it has them, else None for each.
    """
    if is_json_export(path):
        print('  Reading the JSON results feed')
        return contests_from_json(path)
    return parse_csv(path), None, None


def _contests_for_office(contest_list):
    order = {'rep': 0, 'dem': 1, 'np': 2}
    contest_list = sorted(contest_list, key=lambda c: order.get(c['party'], 3))
    out = []
    for c in contest_list:
        entry = {'party': c['party'], 'totalVotes': c['totalVotes'],
                 'candidates': c['candidates']}
        if c.get('multiParty'):
            entry['multiParty'] = True
            entry['parties'] = c.get('parties') or []
        out.append(entry)
    return out


OFFICE_QUALIFIER_RE = re.compile(r'\s*\([^)]*\)\s*$')


# A trailing parenthetical that is an ELECTION TYPE, not a seat. Judicial offices
# identify the seat the same way — "Supreme Court of Georgia (Bethel)", and ninety
# Superior Court seats named for their incumbent — so only this vocabulary is ever
# dropped. Measured: with any parenthetical fair game, rebuilding the published May
# primary changed 174 contests, merging three Supreme Court seats into one card;
# restricted to these words, it changes nothing.
OFFICE_QUALIFIER_WORDS = {'special', 'primary', 'runoff', 'general', 'election'}


def office_qualifier_map(displays):
    """Decide, for one section's office names, which trailing parenthetical to drop.

    WHY DROP ANY. The general export names one contest "District Attorney -
    Atlantic Judicial Circuit (Special Primary)" where every other source for it
    — the generated placeholder, and the `race_notes` key in
    ga-general-2026-results.html carrying the explanation of why a general ballot
    has a party primary on it — calls it "District Attorney - Atlantic Judicial
    Circuit". Left alone, that contest arrives under a name nothing else matches:
    a SECOND card for the same race (the placeholder's, stuck on "Awaiting
    Results") and the note silently absent from the card that most needs it.

    TWO GUARDS, because the parenthetical is usually load-bearing:

      1. It must be an election type (OFFICE_QUALIFIER_WORDS) — never a name. A
         judge's seat and an unexpired-term note are information; "(Special
         Primary)" beside "District Attorney - Atlantic Judicial Circuit" is not.
      2. Exactly one office name in the section may map to the stripped form. Two
         or more means the qualifier is the only thing telling those races apart —
         a special election for a seat that is also on the regular ballot — and
         merging them would add unrelated candidates into one total.

    Returns {display: canonical}.
    """
    def bare_of(display):
        m = OFFICE_QUALIFIER_RE.search(display)
        if not m:
            return display
        inside = m.group(0).strip().strip('()')
        words = {w for w in re.split(r'[^a-z]+', inside.lower()) if w}
        if not words or not words <= OFFICE_QUALIFIER_WORDS:
            return display  # a seat, a person, a term — not ours to drop
        return OFFICE_QUALIFIER_RE.sub('', display).strip() or display

    stripped = {d: bare_of(d) for d in displays}
    counts = Counter(stripped.values())
    return {d: (bare if counts[bare] == 1 else d) for d, bare in stripped.items()}


def build_sections(contests):
    buckets = {k: OrderedDict() for k in
               ('statewide', 'us-house', 'state-senate', 'state-house', 'courts', 'measures')}
    # Two passes: a name is only safe to tidy once every name the export uses
    # for that section is known (see strip_office_qualifier).
    staged = []
    for contest in contests.values():
        section = classify(contest['office_name'])
        if section is None:
            continue
        on = contest['office_name']
        if section == 'statewide':
            display = statewide_display(on)
        elif section == 'courts':
            display = courts_display(on)
        elif section == 'measures':
            display = base_display_name(on)
        else:
            base = base_display_name(on)
            if 'special' in on.lower():
                display = base  # keep "Special ..." prefix
            else:
                m = re.search(r'District\s+(\d+)', base, re.IGNORECASE)
                display = f"District {m.group(1)}" if m else base
        staged.append((section, display, contest))

    seen = {}
    for section, display, _ in staged:
        seen.setdefault(section, set()).add(display)
    canon = {sec: office_qualifier_map(names) for sec, names in seen.items()}
    announced = set()
    for section, display, contest in staged:
        canonical = canon[section][display]
        if canonical != display and (section, display) not in announced:
            announced.add((section, display))
            print(f"  Office name tidied: {display!r} -> {canonical!r}")
        buckets[section].setdefault(canonical, []).append(contest)

    def races_from(bucket, keys):
        return [{'office': name, 'contests': _contests_for_office(bucket[name])} for name in keys]

    # Statewide: canonical order, then any stragglers
    statewide_keys = [n for n in STATEWIDE_ORDER if n in buckets['statewide']]
    statewide_keys += [n for n in buckets['statewide'] if n not in STATEWIDE_ORDER]

    # Legislative: by district number; specials sorted to the end
    def split_specials(bucket):
        regular = sorted((k for k in bucket if 'special' not in k.lower()), key=district_number)
        specials = [k for k in bucket if 'special' in k.lower()]
        return regular + specials

    return [
        {'id': 'statewide',    'label': 'Executive / Statewide', 'races': races_from(buckets['statewide'], statewide_keys)},
        {'id': 'us-house',     'label': 'U.S. House',            'races': races_from(buckets['us-house'], sorted(buckets['us-house'], key=district_number))},
        {'id': 'state-senate', 'label': 'GA State Senate',       'races': races_from(buckets['state-senate'], split_specials(buckets['state-senate']))},
        {'id': 'state-house',  'label': 'GA State House',        'races': races_from(buckets['state-house'], sorted(buckets['state-house'], key=district_number))},
        {'id': 'courts',       'label': 'Courts',                'races': races_from(buckets['courts'], list(buckets['courts']))},
        {'id': 'measures',     'label': 'Ballot Questions',      'races': races_from(buckets['measures'], list(buckets['measures']))},
    ]


def _office_key(name):
    return re.sub(r'[^a-z0-9]', '', (name or '').lower())


def fill_missing_races(sections, baseline):
    """Carry forward races the new export does not mention, so the ballot never shrinks.

    `_data/election_results/<key>.json` is rebuilt WHOLESALE from one CSV, and
    the page renders exactly what that file holds. Before any vote is counted
    the file is the generated placeholder listing all 274 races on the November
    ballot, every one reading "Awaiting Results" — which is the promise the
    results page makes: a race missing from the page is a gap on our side, not
    a race with no returns.

    An export that carries only the contests that have reported would therefore
    DELETE the rest of the ballot from the page: at 8:15pm, with a dozen
    counties in, a reader looking for their State House district would find no
    card at all, and nothing anywhere to say the race exists. The certified
    exports we have all carry every contest, so this has never happened — but
    it is the unofficial feed's shape that decides it, and the failure is
    silent and total for whichever races are absent.

    So the baseline (whatever is committed now, placeholder or an earlier
    count) is the SPINE: its race order is kept, each race replaced by the new
    export's version where the export has one, and any race the export adds is
    appended. Votes therefore only ever come from the CSV — a carried-forward
    race keeps its zeros and keeps reading "Awaiting Results" — while the list
    of races is the union, in canonical order.

    Off by default: a certified rebuild should be exactly what the Secretary of
    State certified, nothing carried over. The election-night publish path
    (.github/workflows/publish-results.yml) turns it on.
    """
    by_id = {s['id']: s for s in baseline if isinstance(s, dict) and 'id' in s}
    carried = 0
    for section in sections:
        base = by_id.get(section['id'], {}).get('races') or []
        if not base:
            continue
        fresh = {_office_key(r['office']): r for r in section['races']}
        # TWO NAMING AUTHORITIES, NOT A PARTIAL REPORT. The ballot questions are
        # the case: the placeholder titles them from our own ga-ballot-measures
        # data ("Constitutional Amendment — Authorize Creation of Next
        # Generation 9-1-1 Fund Amendment") while the Secretary of State titles
        # them by ballot position ("Proposed Constitutional Amendment 1"), and
        # nothing in our data records which amendment got which number. Matched
        # by name they are six different races, so carrying forward would have
        # doubled the section: three cards with counts and three stuck on
        # "Awaiting Results" beside them.
        #
        # The signature is specific — NO baseline race matched, and the export
        # is not short of races — which a partial report cannot produce: an
        # export with 2 of 180 State House races still matches both of them.
        # The export wins, and says so loudly.
        if fresh and not (set(fresh) & {_office_key(r['office']) for r in base}) \
                and len(section['races']) >= len(base):
            print(f"  NOTE: '{section['id']}' renamed wholesale by the export "
                  f"({len(base)} baseline race(s) dropped, {len(section['races'])} kept) "
                  "— the export's names win; nothing carried forward")
            continue
        merged, used = [], set()
        for race in base:
            key = _office_key(race['office'])
            used.add(key)
            if key in fresh:
                merged.append(fresh[key])
            else:
                merged.append(race)
                carried += 1
        merged.extend(r for r in section['races'] if _office_key(r['office']) not in used)
        section['races'] = merged
    return carried


def record_build_time(data_key, now=None, stamp_path=None, counties=None):
    """Record when this data file was built, for the page's "Last updated" line.

    The results data is a bare list of sections with nowhere to carry metadata,
    and a page's `updated:` front matter is a hand-set DATE — so the stamp read
    "November 3, 2026" from poll close to midnight however many times the
    numbers were rebuilt, and a reader could not tell an 8:15pm count from an
    11:40pm one. The page cannot be made genuinely live (the counts are
    rendered into the HTML at build time, and GitHub Pages serves it with
    max-age=600 from its own CDN, which a Cloudflare purge does not reach), so
    saying plainly how old the numbers are is the honest alternative.

    Written HERE, by the thing that changes the numbers, rather than into front
    matter: an election-night step nobody has to remember cannot be forgotten
    at 9pm. This is the one presentation value this script emits, and it is a
    fact about the build rather than a choice about display — the layout still
    decides whether to show it, and prefers a certified page's hand-set date.

    Stored as EPOCH SECONDS, with the ISO string alongside only so the file can
    be read by eye. Liquid's `date` filter converts an integer through the site
    `timezone` (America/New_York) but renders an ISO string in whatever offset
    the string itself carries — so a UTC string published "November 4, 2026 at
    2:40 AM ET" for a 9:40pm Election Night build, naming TOMORROW. Verified by
    building both forms, 2026-10-30.
    """
    stamp_path = stamp_path or STAMP_PATH
    moment = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    stamp = OrderedDict([('epoch', int(moment.timestamp())),
                         ('iso', moment.isoformat())])
    # Set or CLEARED every build, never left behind: a rebuild from the XLSX
    # export carries no county section, and a figure from an hour ago standing
    # beside numbers from a minute ago is worse than no figure.
    if counties:
        stamp['counties'] = OrderedDict([('reporting', counties['reporting']),
                                         ('total', counties['total'])])
    stamps = {}
    if os.path.exists(stamp_path):
        try:
            with open(stamp_path, encoding='utf-8') as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                stamps = loaded
        except (OSError, ValueError) as exc:
            # An unreadable sidecar must not cost us the results, which are
            # already on disk by the time this runs. Re-stamping from scratch
            # loses other pages' times; they are rewritten on their next build.
            print(f"  WARNING: ignoring unreadable {stamp_path}: {exc}")
    stamps[data_key] = stamp
    write_json_atomic(stamp_path, OrderedDict(sorted(stamps.items())), indent=2)
    return stamp


if __name__ == '__main__':
    USAGE = ("Usage: python scripts/build_results_json.py <csv_path> <data_key> "
             "[--fill-missing-from <json_path>]")
    args = sys.argv[1:]
    fill_from = None
    if '--fill-missing-from' in args:
        i = args.index('--fill-missing-from')
        if i + 1 >= len(args):
            sys.exit(USAGE)
        fill_from = args[i + 1]
        del args[i:i + 2]
    if len(args) != 2:
        sys.exit(USAGE)
    csv_path, data_key = args
    print(f"Parsing export: {csv_path}")
    contests, source_time, counties = parse_export(csv_path)
    print(f"  {len(contests)} contest(s) parsed")
    sections = build_sections(contests)
    if fill_from:
        with open(fill_from, encoding='utf-8') as fh:
            baseline = json.load(fh)
        carried = fill_missing_races(sections, baseline)
        print(f"  Carried forward {carried} race(s) the export did not mention, from {fill_from}")
    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, f"{data_key}.json")
    write_json_atomic(out_path, sections, separators=(',', ':'))
    counts = {s['id']: len(s['races']) for s in sections}
    print(f"  Races per section: {counts}")
    print(f"Wrote: {out_path}")
    # Prefer the SECRETARY OF STATE'S timestamp over ours. The stamp answers
    # "how old are these numbers", and the honest answer is when the data was
    # built, not when we fetched it — a feed that stops updating would
    # otherwise keep looking fresh every time the page was rebuilt.
    moment = None
    if source_time:
        try:
            moment = datetime.fromisoformat(str(source_time).replace('Z', '+00:00'))
        except ValueError:
            print(f"  WARNING: unreadable createdAt {source_time!r}; stamping the build time")
    stamp = record_build_time(data_key, now=moment, counties=counties)
    print(f"Data built at: {stamp['iso']}" + (' (from the feed)' if moment else ' (local build time)'))
    if counties:
        print(f"  Counties reporting: {counties['reporting']} of {counties['total']}")
