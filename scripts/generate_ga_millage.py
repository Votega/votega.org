#!/usr/bin/env python3
"""Build the Georgia millage dataset from DOR's Tax Digest Consolidated Summaries.

    # normal run: discover, download and build every published year
    python scripts/generate_ga_millage.py --out assets/data

    # offline, from workbooks already on disk (what CI and development use)
    python scripts/generate_ga_millage.py --from-dir /path/to/xlsx --out assets/data

    # see what would be fetched, without fetching
    python scripts/generate_ga_millage.py --list

WHAT IT PRODUCES
----------------
`ga-millage.json`  metadata + a compact columnar table (field names once, rows as
                   arrays) and `ga-millage.csv`, the same rows for anyone who
                   would rather open a spreadsheet. One row per
                   county x tax district x year, carrying identity, the derived
                   district type, M&O and bond millage, total tax and total
                   assessed value. This is "table A" of
                   docs/LOCAL-EXPANSION-SCOPE.md; the ~400 exemption columns are
                   left for the separate HB 581 table.

LINKS ARE DISCOVERED, NOT CONSTRUCTED
-------------------------------------
The per-year download URLs on DOR's page are not patterned — 2024 is a bare
/media/30916/download while 2020 is /document/document-document/2020/download —
so the index page is scraped for anchors and the year is read from the link text.
Constructing a URL from a year would silently miss or mis-fetch a file. A year
DOR has not published yet simply does not appear.

NO THIRD-PARTY IMPORTS. lib/xlsx.py reads the workbooks with zipfile and
ElementTree so that scripts/test_dor_digest.py can run in CI, which installs no
pip packages (see run-script-tests.yml).
"""

import argparse
import csv
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import dor_digest as D  # noqa: E402
from lib import dor_millage_pdf as PDF  # noqa: E402
from lib.xlsx import XlsxError  # noqa: E402

INDEX = ('https://dor.georgia.gov/local-government-services/'
         'digest-compliance/digest-consolidated-summaries')

# The machine-readable workbooks start at 2020. ONE earlier year is obtainable:
# the 2019 millage-rate PDF, which lives on a DIFFERENT index page and has a
# clean text layer. 2021 and 2024 are scanned and 2025 is Type 3 mojibake, so
# this is deliberately 2019 and nothing else — see lib/dor_millage_pdf.py.
PDF_INDEX = ('https://dor.georgia.gov/local-government-services/'
             'digest-compliance/property-tax-millage-rates')
PDF_YEARS = (2019,)
SOURCE_NAME = 'Georgia Department of Revenue — Tax Digest Consolidated Summaries'
UA = 'VoteGA/1.0 (+https://www.votega.org; nonpartisan civic data)'

FIELDS = ['taxYear', 'countyCode', 'countyName', 'countyNameAsFiled',
          'districtCode', 'districtName', 'districtType', 'occurrence',
          'millageMO', 'millageBond', 'totalTaxMO', 'totalTaxBond',
          'assessedValueMO', 'assessedValueBond', 'dataSource']

# Which source a row came from. 2019 carries MILLAGE ONLY — no tax levied, no
# assessed value — and a null in this dataset otherwise means "the jurisdiction
# reported none". Without this field that null would read as a reported zero,
# so anything summing tax or value by year must filter on it.
SOURCE_XLSX = 'digest-xlsx'

# A link on the index page whose text names a tax year. The "(Current Year)"
# heading sits beside the newest link rather than in it, so the year in the link
# text is what identifies the file.
_YEAR_RE = re.compile(r'\b(19|20)\d{2}\b')
_ANCHOR_RE = re.compile(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.I | re.S)
_TAG_RE = re.compile(r'<[^>]+>')


def fetch(url, timeout=120):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def discover(html=None):
    """{year: absolute url} for every workbook linked on the index page.

    Refuses if the page yields nothing, which is how a redesign surfaces instead
    of quietly producing an empty dataset.
    """
    html = html if html is not None else fetch(INDEX).decode('utf-8', 'replace')
    found = {}
    for href, inner in _ANCHOR_RE.findall(html):
        text = _TAG_RE.sub(' ', inner)
        if 'download' not in href.lower():
            continue
        m = _YEAR_RE.search(text)
        if not m:
            continue
        year = int(m.group(0))
        if not 1990 <= year <= datetime.now(timezone.utc).year + 1:
            continue
        url = href if href.startswith('http') else 'https://dor.georgia.gov' + href
        found.setdefault(year, url)
    if not found:
        raise SystemExit('ERROR: no workbook links found on %s — the page layout '
                         'has probably changed. Nothing was written.' % INDEX)
    return dict(sorted(found.items()))


def workbooks_from_dir(path):
    """{year: filepath} for digest workbooks already on disk."""
    out = {}
    for name in sorted(os.listdir(path)):
        if not name.lower().endswith(('.xls', '.xlsx')):
            continue
        m = _YEAR_RE.search(name)
        if m:
            out.setdefault(int(m.group(0)), os.path.join(path, name))
    if not out:
        raise SystemExit('ERROR: no .xls/.xlsx workbooks with a year in the name '
                         'under %s' % path)
    return dict(sorted(out.items()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='assets/data', help='directory for the outputs')
    ap.add_argument('--from-dir', help='read workbooks from here instead of downloading')
    ap.add_argument('--cache', default=None, help='where downloads are kept')
    ap.add_argument('--list', action='store_true', help='print the discovered links and exit')
    ap.add_argument('--year', type=int, action='append', help='limit to this year (repeatable)')
    ap.add_argument('--no-pdf', action='store_true',
                    help='skip the 2019 millage PDF (workbook years only)')
    args = ap.parse_args()

    pdf_paths = {}
    if args.from_dir:
        books = workbooks_from_dir(args.from_dir)
        urls = {}
        for y in PDF_YEARS:
            cand = os.path.join(args.from_dir, '%d.pdf' % y)
            if os.path.exists(cand):
                pdf_paths[y] = cand
    else:
        urls = discover()
        if args.list:
            for y, u in urls.items():
                print('%d  %s' % (y, u))
            return 0
        cache = args.cache or os.path.join('.cache', 'dor-digest')
        os.makedirs(cache, exist_ok=True)
        books = {}
        for y, u in urls.items():
            dest = os.path.join(cache, 'digest-%d.xlsx' % y)
            if not os.path.exists(dest):
                print('fetching %d ...' % y, flush=True)
                blob = fetch(u)
                with open(dest, 'wb') as fh:
                    fh.write(blob)
            books[y] = dest
        if not args.no_pdf:
            for y, u in sorted(discover(fetch(PDF_INDEX).decode('utf-8', 'replace')).items()):
                if y not in PDF_YEARS:
                    continue
                dest = os.path.join(cache, 'millage-%d.pdf' % y)
                if not os.path.exists(dest):
                    print('fetching the %d millage PDF ...' % y, flush=True)
                    with open(dest, 'wb') as fh:
                        fh.write(fetch(u))
                pdf_paths[y] = dest

    if args.year:
        books = {y: p for y, p in books.items() if y in set(args.year)}
        if not books:
            raise SystemExit('ERROR: none of the requested years are available')

    rows, per_year, types = [], {}, {}
    for year, path in books.items():
        try:
            recs = D.parse(path)
        except (D.DigestError, XlsxError) as exc:
            # Loud and total: a layout change in ONE year must not publish a
            # dataset that silently drops it.
            raise SystemExit('ERROR: %s\nNothing was written.' % exc)
        # The workbook states its own tax year per row; trust that over the
        # filename, and say so when they disagree.
        stated = {r['taxYear'] for r in recs if r['taxYear']}
        if stated and stated != {year}:
            print('  note: %s names tax year(s) %s, filename said %d — using the file'
                  % (os.path.basename(path), sorted(stated), year))
        for r in recs:
            types[r['districtType']] = types.get(r['districtType'], 0) + 1
        per_year[year] = len(recs)
        rows.extend(recs)

    # Every workbook row is tagged before the PDF year joins them.
    for r in rows:
        r['dataSource'] = SOURCE_XLSX

    # 2019, from the millage PDF, keyed with district codes borrowed from the
    # nearest workbook year. Skipped silently when that reference year is not in
    # this run (--year 2023, say), because the codes cannot be resolved without
    # it — and skipped, never guessed.
    if pdf_paths and not args.no_pdf:
        reference = [r for r in rows if r['taxYear'] == PDF.REFERENCE_YEAR]
        if not reference:
            print('note: %d is not in this run, so the %s PDF year(s) cannot be '
                  'keyed and were skipped' % (PDF.REFERENCE_YEAR,
                                              ', '.join(str(y) for y in sorted(pdf_paths))))
        else:
            for year, path in sorted(pdf_paths.items()):
                if year in per_year:
                    continue  # a workbook for that year wins over the PDF
                try:
                    recs, unresolved = PDF.parse(path, reference, year=year)
                except PDF.MillagePdfError as exc:
                    raise SystemExit('ERROR: %s\nNothing was written.' % exc)
                for r in recs:
                    types[r['districtType']] = types.get(r['districtType'], 0) + 1
                per_year[year] = len(recs)
                rows.extend(recs)
                print('%d: %d rows from the millage PDF (millage only; no tax or '
                      'assessed value in that source)' % (year, len(recs)))
                if unresolved:
                    print('  %d row(s) dropped — their district name does not '
                          'resolve to a %d district code, so they cannot be keyed:'
                          % (len(unresolved), PDF.REFERENCE_YEAR))
                    for county, dist in unresolved[:20]:
                        print('    %-16s %s' % (county, dist))

    # DOR's county names are dirty (see dor_digest.canonical_county_names): 191
    # distinct names for 159 codes. Publish one canonical name per code and keep
    # what the workbook actually said beside it, so nothing is silently rewritten.
    canon = D.canonical_county_names(rows)
    renamed = 0
    for r in rows:
        filed = r['countyName']
        r['countyNameAsFiled'] = filed
        r['countyName'] = canon.get(r['countyCode'], filed)
        if r['countyName'] != filed:
            renamed += 1
    if renamed:
        odd = sorted({(r['countyCode'], r['countyNameAsFiled'], r['countyName'])
                      for r in rows if r['countyName'] != r['countyNameAsFiled']})
        print('\nNOTE: %d row(s) carried an abbreviated or suffixed county name; '
              'countyName is canonicalised and countyNameAsFiled keeps the original.'
              % renamed)
        print('      %d code(s) affected, e.g. %s'
              % (len({o[0] for o in odd}),
                 ', '.join('%s->%s' % (o[1], o[2]) for o in odd[:6])))

    rows.sort(key=lambda r: (r['taxYear'] or 0, r['countyName'],
                             int(r['districtCode'] or 0), r['occurrence']))

    # The published key carries an occurrence ordinal, so it must be unique. If
    # it is not, the numbering itself is broken and nothing should be written.
    dupes = len(rows) - len({D.key(r) for r in rows})
    if dupes:
        raise SystemExit('ERROR: %d rows share a full key including occurrence — '
                         'the ordinal is broken, refusing to publish.' % dupes)

    # A repeated (county, district, year) is a defect in DOR's workbook, not in
    # this script. Report every one; do not merge them.
    groups = D.duplicate_groups(rows)
    if groups:
        print('\nNOTE: %d (county, district, year) listed more than once by DOR — '
              'every row is published, none merged:' % len(groups))
        for county, dc, yr, members in groups:
            print('  %s %s, district %s, %d rows:' % (county, yr, dc, len(members)))
            for m in members:
                print('    occurrence %d: %r  %s mills  tax %s  assessed %s'
                      % (m['occurrence'], m['districtName'], m['millageMO'],
                         m['totalTaxMO'], m['assessedValueMO']))

    os.makedirs(args.out, exist_ok=True)
    payload = {
        'metadata': {
            'generatedAt': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'source': SOURCE_NAME,
            'sourceIndex': INDEX,
            'sourceUrls': {str(y): urls[y] for y in sorted(urls)} if urls else None,
            'license': 'Source data is a public record of the State of Georgia.',
            'years': sorted(per_year),
            'rowsPerYear': {str(y): per_year[y] for y in sorted(per_year)},
            'count': len(rows),
            'fields': FIELDS,
            'keyFields': ['countyCode', 'districtCode', 'taxYear'],
            'notes': [
                'One row per county x tax district x tax year.',
                'Key on (countyCode, districtCode, taxYear). District names drift '
                'between years for ~15% of districts and must not be used to join.',
                'A null millage means the jurisdiction reported none; 0 means it '
                'levied zero. They are different facts.',
                'countyName is canonical per countyCode; countyNameAsFiled is '
                "what that year's workbook said. DOR abbreviates some county "
                "names per row ('ATKINS', 'BENHIL', 'CHARLT TB'), giving 191 "
                'distinct names for 159 codes, so never join on a county name.',
                'districtType is derived: codes 0-3 are statewide-stable '
                '(countywide/state/school/county_incorporated), everything above '
                'is classified from the district name.',
                'A city school system is listed under EACH county it serves, so '
                'the same system can appear more than once in a year.',
                'occurrence is 1 for every row except where DOR lists the same '
                'county/district/year twice (Cherokee 2022 district 18). Those '
                'rows are published unmerged; sum them only deliberately.',
                "DOR's 2020 workbook is published as "
                '"2020-digest-excluding-charlton", so treat 2020 Charlton '
                'figures with suspicion.',
            ],
        },
        'rows': [[r[f] for f in FIELDS] for r in rows],
    }
    jpath = os.path.join(args.out, 'ga-millage.json')
    with open(jpath, 'w', encoding='utf-8') as fh:
        json.dump(payload, fh, indent=1, ensure_ascii=False)
        fh.write('\n')
    cpath = os.path.join(args.out, 'ga-millage.csv')
    with open(cpath, 'w', encoding='utf-8', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(FIELDS)
        for r in rows:
            w.writerow(['' if r[f] is None else r[f] for f in FIELDS])

    print('\n%d rows across %d year(s): %s'
          % (len(rows), len(per_year), ', '.join(str(y) for y in sorted(per_year))))
    for y in sorted(per_year):
        print('  %d: %d rows' % (y, per_year[y]))
    print('district types:')
    for t, n in sorted(types.items(), key=lambda kv: -kv[1]):
        print('  %6d  %s' % (n, t))
    if types.get('unclassified'):
        print('  WARNING: %d unclassified district(s) — add a rule to '
              'lib/dor_digest.py NAME_TYPES' % types['unclassified'])
    counties = len({r['countyCode'] for r in rows})
    print('counties: %d (expect 159)' % counties)
    print('wrote %s (%.1f KB)' % (jpath, os.path.getsize(jpath) / 1024.0))
    print('wrote %s (%.1f KB)' % (cpath, os.path.getsize(cpath) / 1024.0))
    return 0


if __name__ == '__main__':
    sys.exit(main())
