#!/usr/bin/env python3
"""Gate a freshly built election-results file before it is committed and deployed.

This exists for the election-night publish path
(.github/workflows/publish-results.yml), where nobody is reading the build log
at 9:40pm. The data file is rebuilt WHOLESALE from one CSV and the page renders
exactly what the file holds, so a bad export does not degrade the page — it
replaces it. The failures worth refusing are the quiet ones:

  * AN EMPTY OR UNPARSEABLE EXPORT. A truncated download, an HTML error page
    saved as .csv, or a column reshuffle yields a file with every section
    present and no votes anywhere. The page would read "Awaiting Results" on
    every race, which is indistinguishable from "polls just closed".

  * A SHRINKING BALLOT. Races in the committed file but not in the new one have
    been deleted from the page, not zeroed. `--fill-missing-from` on the
    builder is the fix; this is the alarm that says it was needed.

  * COUNTS GOING BACKWARDS. Votes accumulate through the night, so a drop in
    the statewide total is the signature of a partial or stale export
    overwriting a fuller one. Not impossible legitimately — a county correcting
    an error can revise a total down — so it is refusable with
    --allow-decrease, which the operator passes deliberately.

  * STRUCTURAL DAMAGE. Missing or renamed section ids, a race with no
    contests, a contest whose candidate votes exceed its own total.

Checks that cannot be decided from the file alone (did the Secretary of State
publish this, is it tonight's export) are out of scope: this reads what was
built and what is committed, nothing else.

Usage:
  python scripts/validate_results_build.py <data_key> [--baseline-ref HEAD]
                                           [--allow-decrease] [--allow-zero]
                                           [--summary-out PATH]

Exits 0 when the build is safe to publish, 1 when it is not.
"""

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SECTION_IDS = ['statewide', 'us-house', 'state-senate', 'state-house', 'courts', 'measures']


def load_built(data_key):
    path = os.path.join(REPO, '_data', 'election_results', f'{data_key}.json')
    with open(path, encoding='utf-8') as fh:
        return json.load(fh), path


def load_baseline(data_key, ref):
    """The committed version, read from git so an uncommitted build is compared against it."""
    rel = f'_data/election_results/{data_key}.json'
    try:
        raw = subprocess.check_output(['git', 'show', f'{ref}:{rel}'], cwd=REPO,
                                      stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        return None  # first build of a new election: nothing to compare
    try:
        return json.loads(raw)
    except ValueError:
        return None


def tally(sections):
    races = votes = contests = 0
    offices = set()
    for s in sections:
        for r in s.get('races', []):
            races += 1
            offices.add((s.get('id'), r.get('office')))
            for c in r.get('contests', []):
                contests += 1
                votes += sum(x.get('votes') or 0 for x in c.get('candidates', []))
    return {'races': races, 'contests': contests, 'votes': votes, 'offices': offices}


def main(argv):
    if not argv or argv[0].startswith('-'):
        sys.exit(__doc__.split('Usage:')[1].strip())
    data_key = argv[0]
    flags = argv[1:]
    ref = 'HEAD'
    if '--baseline-ref' in flags:
        ref = flags[flags.index('--baseline-ref') + 1]
    allow_decrease = '--allow-decrease' in flags
    allow_zero = '--allow-zero' in flags
    summary_out = None
    if '--summary-out' in flags:
        summary_out = flags[flags.index('--summary-out') + 1]

    errors, warnings, lines = [], [], []

    try:
        built, path = load_built(data_key)
    except (OSError, ValueError) as exc:
        print(f'FATAL: cannot read the built file for {data_key}: {exc}')
        return 1

    # --- structure -----------------------------------------------------------
    if not isinstance(built, list):
        errors.append('the data file is not a list of sections')
        built = []
    ids = [s.get('id') for s in built if isinstance(s, dict)]
    missing = [i for i in SECTION_IDS if i not in ids]
    if missing:
        errors.append(f'missing section id(s): {", ".join(missing)}')

    for s in built:
        for r in s.get('races', []):
            if not r.get('contests'):
                errors.append(f'race with no contests: {s.get("id")} / {r.get("office")}')
            for c in r.get('contests', []):
                cand_total = sum(x.get('votes') or 0 for x in c.get('candidates', []))
                total = c.get('totalVotes') or 0
                if total and cand_total > total:
                    errors.append(
                        f'candidate votes exceed the contest total: {r.get("office")} '
                        f'({cand_total} > {total})')

    now = tally(built)
    lines.append(f'Built `{data_key}`: **{now["races"]} races**, '
                 f'{now["contests"]} contests, **{now["votes"]:,} votes**.')

    # --- did anything report? ------------------------------------------------
    if now['votes'] == 0 and not allow_zero:
        errors.append('no votes anywhere in the file — a truncated or wrong export would '
                      'look exactly like this (pass --allow-zero to publish a zeroed page '
                      'on purpose)')

    # --- against what is committed -------------------------------------------
    base = load_baseline(data_key, ref)
    if base is None:
        warnings.append(f'no committed baseline at {ref} to compare against — '
                        'skipping the shrink and decrease checks')
    else:
        was = tally(base)
        lines.append(f'Committed now: {was["races"]} races, {was["votes"]:,} votes '
                     f'(delta **{now["votes"] - was["votes"]:+,} votes**, '
                     f'{now["races"] - was["races"]:+d} races).')
        dropped = was['offices'] - now['offices']
        if dropped:
            sample = ', '.join(f'{sec}/{off}' for sec, off in sorted(dropped)[:5])
            errors.append(
                f'{len(dropped)} race(s) in the committed file are absent from this build, '
                f'so they would vanish from the page (e.g. {sample}). Rebuild with '
                '--fill-missing-from to carry them forward as "Awaiting Results"')
        if now['votes'] < was['votes']:
            msg = (f'the vote total went DOWN by {was["votes"] - now["votes"]:,} '
                   '— the signature of a partial or stale export')
            (warnings if allow_decrease else errors).append(
                msg + (' (allowed by --allow-decrease)' if allow_decrease else
                       ' (pass --allow-decrease if this is a genuine revision)'))

    for w in warnings:
        print(f'WARNING: {w}')
    for e in errors:
        print(f'ERROR: {e}')
    for line in lines:
        print(line.replace('**', '').replace('`', ''))

    if summary_out:
        with open(summary_out, 'w', encoding='utf-8') as fh:
            fh.write('### Election results build\n\n')
            fh.write('\n'.join(f'- {line}' for line in lines) + '\n')
            for w in warnings:
                fh.write(f'- :warning: {w}\n')
            for e in errors:
                fh.write(f'- :x: **{e}**\n')
            if not errors:
                fh.write('\n- :white_check_mark: Safe to publish.\n')

    if errors:
        print(f'\nREFUSED: {len(errors)} problem(s); {path} must not be published as is.')
        return 1
    print('\nOK: safe to publish.')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
