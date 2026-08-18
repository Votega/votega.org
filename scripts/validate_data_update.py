#!/usr/bin/env python3
"""Generic pre-commit validator for generated data files.

Guards the case CLAUDE.md warns about — *"never commit based on JSON validity
alone"*. A truncated or empty file produced by a partial API failure is still
valid JSON, so parsing it proves nothing. This compares the freshly generated
file against the version already committed at HEAD and refuses to let it
through if a metric collapsed.

Addresses CODEBASE-REVIEW-2026-08-18.md findings 2.3 and 5.1.

Why a delta check rather than per-dataset floors: an absolute floor has to be
re-tuned every time the underlying corpus changes size, and when it isn't, it
either goes slack (never fires) or turns into a permanent failure. The
`>= 5000` assert in update-ga-bills.yml is the latter — it is pinned to the
2025-26 session and will fail every run for the first year of the next
biennium. A relative floor tracks the data automatically; `--min` remains
available as a coarse absolute sanity bound for genuinely new datasets.

Usage:
    python scripts/validate_data_update.py assets/data/scotus-decisions.json \
        --metric decisions=metadata.count \
        --min decisions=100

    python scripts/validate_data_update.py assets/data/federal-member-votes.json \
        --metric rollcalls=len:votes \
        --metric members=len:memberVotes \
        --min members=15

Metric expressions:
    metadata.count      dotted path to a number
    len:votes           length of the dict/list at that path
    len:metadata.gaMembers

Exit codes:
    0  all checks passed (or baseline unavailable and only floors were checked)
    1  a check failed — the caller should not commit
"""

import argparse
import json
import subprocess
import sys

DEFAULT_MAX_SHRINK = 0.20


def resolve(data, expr):
    """Resolve a metric expression against a loaded JSON document."""
    want_len = False
    if expr.startswith('len:'):
        want_len = True
        expr = expr[4:]

    node = data
    for part in expr.split('.'):
        if not isinstance(node, (dict, list)):
            raise KeyError(f'{expr!r}: cannot descend into {type(node).__name__} at {part!r}')
        if isinstance(node, list):
            raise KeyError(f'{expr!r}: cannot index list with {part!r}')
        if part not in node:
            raise KeyError(f'{expr!r}: no key {part!r}')
        node = node[part]

    if want_len:
        if not isinstance(node, (dict, list, str)):
            raise KeyError(f'len:{expr}: {type(node).__name__} has no length')
        return len(node)

    if isinstance(node, bool) or not isinstance(node, (int, float)):
        raise KeyError(f'{expr}: expected a number, got {type(node).__name__}')
    return node


def committed_version(path):
    """Return the JSON committed at HEAD for `path`, or None if not tracked."""
    try:
        blob = subprocess.run(
            ['git', 'show', f'HEAD:{path}'],
            capture_output=True, check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        return None


def parse_pairs(values, flag):
    out = {}
    for raw in values or []:
        if '=' not in raw:
            sys.exit(f'Error: {flag} expects LABEL=VALUE, got {raw!r}')
        label, _, val = raw.partition('=')
        out[label.strip()] = val.strip()
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('path', help='path to the freshly generated JSON file')
    ap.add_argument('--metric', action='append', metavar='LABEL=EXPR',
                    help='metric to check (repeatable)')
    ap.add_argument('--min', action='append', metavar='LABEL=N', default=[],
                    help='absolute floor for a metric (repeatable)')
    ap.add_argument('--max-shrink', type=float, default=DEFAULT_MAX_SHRINK,
                    metavar='FRACTION',
                    help=f'fail if a metric drops by more than this fraction '
                         f'versus HEAD (default {DEFAULT_MAX_SHRINK})')
    ap.add_argument('--scope-key', metavar='PATH',
                    help='dotted path to the value identifying the dataset\'s scope '
                         '(e.g. metadata.congress, metadata.session). When it changes, '
                         'the corpus legitimately resets, so delta checks are skipped '
                         'for that run and only --min floors apply. Keeps a session or '
                         'Congress rollover from turning into a standing failure.')
    ap.add_argument('--allow-missing-baseline', action='store_true',
                    help='treat an untracked/unparseable HEAD version as OK (default)')
    args = ap.parse_args()

    if not args.metric:
        sys.exit('Error: at least one --metric is required')

    metrics = parse_pairs(args.metric, '--metric')
    floors = {k: float(v) for k, v in parse_pairs(args.min, '--min').items()}

    unknown = set(floors) - set(metrics)
    if unknown:
        sys.exit(f'Error: --min given for undeclared metric(s): {sorted(unknown)}')

    try:
        with open(args.path, encoding='utf-8') as fh:
            new = json.load(fh)
    except FileNotFoundError:
        sys.exit(f'FAIL: {args.path} was not generated')
    except json.JSONDecodeError as exc:
        sys.exit(f'FAIL: {args.path} is not valid JSON: {exc}')

    base = committed_version(args.path)
    if base is None:
        print(f'note: no committed baseline for {args.path} '
              f'(new file, or not tracked) - delta checks skipped')

    if base is not None and args.scope_key:
        def scope_of(doc):
            node = doc
            for part in args.scope_key.split('.'):
                if not isinstance(node, dict) or part not in node:
                    return None
                node = node[part]
            return node

        new_scope, old_scope = scope_of(new), scope_of(base)
        if new_scope != old_scope:
            print(f'note: {args.scope_key} changed {old_scope!r} -> {new_scope!r} '
                  f'- the corpus reset, so delta checks are skipped this run '
                  f'(--min floors still apply)')
            base = None

    failures = []
    print(f'Validating {args.path}')

    for label, expr in metrics.items():
        try:
            value = resolve(new, expr)
        except KeyError as exc:
            failures.append(f'{label}: {exc}')
            print(f'  {label:<14} ERROR  {exc}')
            continue

        notes = []

        floor = floors.get(label)
        if floor is not None and value < floor:
            failures.append(f'{label}: {value} is below the absolute floor of {floor:g}')
            notes.append(f'below floor {floor:g}')

        if base is not None:
            try:
                prior = resolve(base, expr)
            except KeyError:
                notes.append('no baseline for this metric')
            else:
                if prior > 0:
                    change = (value - prior) / prior
                    limit = -abs(args.max_shrink)
                    notes.append(f'was {prior} ({change:+.1%})')
                    if change < limit:
                        failures.append(
                            f'{label}: dropped {abs(change):.1%} versus HEAD '
                            f'({prior} -> {value}), exceeding the '
                            f'{abs(args.max_shrink):.0%} limit'
                        )
                elif value == 0:
                    notes.append('was 0')

        suffix = f'   [{"; ".join(notes)}]' if notes else ''
        print(f'  {label:<14} {value}{suffix}')

    if failures:
        print()
        print('VALIDATION FAILED - refusing to commit:')
        for f in failures:
            print(f'  - {f}')
        print()
        print('If this drop is legitimate (a new session, a source that genuinely '
              'shrank), re-run with a higher --max-shrink or adjust --min.')
        return 1

    print('All integrity checks passed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
