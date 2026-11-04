#!/usr/bin/env python3
"""Refuse a results export that is not a results export, before it overwrites a page.

The election-night publish path (.github/workflows/publish-results.yml) downloads
a file from a URL and rebuilds the results data from it. Everything downstream
treats that file as authoritative, so this is the only place a wrong file can be
caught while the page still holds the right numbers.

What a RIGHT file looks like, by content rather than by name:

  * The Secretary of State's XLSX WORKBOOK as published — three sheets, of which
    "Total Votes" has the six columns build_results_json.py parses. This is what
    the SoS actually publishes; the CSVs under _sources/election_results/ are
    that sheet saved out by hand, which is why four elections shipped before
    anyone needed to know the difference.
  * Or the JSON feed at the Secretary of State's stable URL
    (https://results.sos.ga.gov/cdn/results/Georgia/export-<date><name>.json),
    which is the form the publish workflow can fetch on its own — the workbook's
    download name carries a fresh GUID every time and cannot be fetched twice.
  * Or a CSV/TSV whose header carries an "Office Name" column.

What a WRONG file looks like, and why each is worth a gate rather than a parse
error three steps later: an HTML login wall or CDN interstitial served with HTTP
200 (curl --fail cannot see it); a truncated download; a zip that is not a
workbook; the right workbook with the wrong columns. Each one, parsed, yields a
file with every section present and no votes in it — which on the page is
indistinguishable from "polls just closed".

Usage:
  python scripts/check_export_shape.py <path>

Exits 0 when the file is a plausible export, 1 when it is not, printing a
GitHub Actions ::error:: line either way.
"""

import sys
import zipfile


def fail(message):
    print(f'::error::{message}')
    return 1


def check(path):
    try:
        with open(path, 'rb') as fh:
            head = fh.read(4096)
    except OSError as exc:
        return fail(f'cannot read the download: {exc}')

    if not head:
        return fail('the download is empty.')

    if head[:4] == b'PK\x03\x04':
        if not zipfile.is_zipfile(path):
            return fail('the download starts like a zip but is not one — likely truncated.')
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
        if 'xl/workbook.xml' not in names:
            return fail('the download is a zip but not an XLSX workbook '
                        '(no xl/workbook.xml).')
        print('Export is an XLSX workbook.')
        return 0

    stripped = head.lstrip()
    if stripped[:1] == b'{':
        # Only the opening of the file is read: the feed is ~46MB, and parsing it
        # to validate it is the builder's job a step later.
        if b'"results"' not in head and b'"electionDate"' not in head:
            return fail('the download is JSON but does not look like the results feed '
                        '(no electionDate or results key in its first 4KB).')
        print('Export is the JSON results feed.')
        return 0

    lowered = head.lower()
    if b'<!doctype' in lowered or b'<html' in lowered:
        return fail('the download is HTML, not an export — check the URL points at '
                    'the file itself, not a page about it.')

    first = head.decode('utf-8-sig', 'replace').splitlines()[0] if b'\n' in head or head else ''
    if 'office name' not in first.lower():
        return fail('not a Secretary of State results header (no "Office Name" column): '
                    f'{first[:200]!r}')
    print('Export is a text table.')
    return 0


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit('Usage: python scripts/check_export_shape.py <path>')
    sys.exit(check(sys.argv[1]))
