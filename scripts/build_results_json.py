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
from lib.atomic_io import write_json_atomic
import os
import re
import sys
from collections import OrderedDict
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


def detect_delimiter(path):
    """Sniff delimiter — handles both tab-separated exports and comma CSV."""
    with open(path, newline='', encoding='utf-8-sig') as f:
        sample = f.read(4096)
    return '\t' if sample.count('\t') > sample.count(',') else ','


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


def parse_csv(path):
    contests = OrderedDict()
    delimiter = detect_delimiter(path)
    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.reader(f, delimiter=delimiter)
        next(reader)  # header
        for row in reader:
            if len(row) < 6:
                continue
            office_name, contest_id, ballot_name = row[0].strip(), row[1].strip(), row[2].strip()
            party_str, total_str = row[4].strip(), row[5].strip()
            total = int(total_str) if total_str else 0

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


def _contests_for_office(contest_list):
    order = {'rep': 0, 'dem': 1, 'np': 2}
    contest_list = sorted(contest_list, key=lambda c: order.get(c['party'], 3))
    return [{'party': c['party'], 'totalVotes': c['totalVotes'], 'candidates': c['candidates']}
            for c in contest_list]


def build_sections(contests):
    buckets = {k: OrderedDict() for k in
               ('statewide', 'us-house', 'state-senate', 'state-house', 'courts', 'measures')}
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
        buckets[section].setdefault(display, []).append(contest)

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


def record_build_time(data_key, now=None, stamp_path=None):
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
    stamp = OrderedDict([('epoch', int(moment.timestamp())),
                         ('iso', moment.isoformat())])
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
    print(f"Parsing CSV: {csv_path}")
    contests = parse_csv(csv_path)
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
    print(f"Built at: {record_build_time(data_key)['iso']}")
