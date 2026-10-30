#!/usr/bin/env python3
"""Assert the ballot preview leaves judicial races out but keeps the section.

Judicial races are nonpartisan and decided at the May general primary, so the
November ballot preview does not advertise them. They are excluded from the
PREVIEW only: on election night the page is rebuilt from the SoS CSV by
build_results_json.py, which buckets judicial contests into this same `courts`
section, so results appear without anything being flipped.

Two things have to stay true for that to work, and neither is obvious from
reading build_sections() alone:

  * the `courts` section is still EMITTED, empty. validate_general_placeholder
    expects five sections, and _layouts/election_results.html hides a tab whose
    panel has no race cards - which is what keeps the Courts tab out of sight
    without any judicial-specific code in the layout.
  * excluding judicial must not disturb any other section.

Usage:
  python scripts/test_general_placeholder_sections.py

Exits 0 on success, 1 on any failure.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_general_placeholder as B  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def race(**kw):
    """A race with a general phase, defaulting to this build's cycle."""
    cand = {'id': kw.pop('cid', 'c1'), 'name': kw.pop('cname', 'A Candidate')}
    nonpartisan = kw.pop('nonpartisan', False)
    general = ({'candidates': [cand]} if nonpartisan
               else {'ballots': {'Republican': [cand]}})
    base = {'cycle': B.CYCLE, 'phases': {'general': general}}
    base.update(kw)
    return base


JUDICIAL = [
    race(level='state-judicial', chamber='Supreme Court of Georgia',
         seat='Warren', nonpartisan=True),
    race(level='state-judicial', chamber='Georgia Court of Appeals',
         seat='Doyle', nonpartisan=True),
    race(level='state-judicial', chamber='Superior Court',
         circuit='Atlanta', seat='Eaton', nonpartisan=True),
]

OTHERS = [
    race(level='state', chamber='Georgia House of Representatives', district=70),
    race(level='state', chamber='Georgia State Senate', district=6),
    race(level='federal', chamber='U.S. House', district=4),
    race(level='federal', chamber='U.S. Senate'),
]


def sections_by_id(races):
    return {s['id']: s for s in B.build_sections(races, {}, {})}


def cases():
    # The policy constant itself, so a silent rename is caught here rather than
    # by a section mysteriously filling up again.
    check("courts is the excluded section",
          B.PREVIEW_EMPTY_SECTIONS, {'courts'})

    # classify() must still RECOGNISE judicial as courts - the exclusion is a
    # policy on top of classification, not a hole in it. If this regressed to
    # None the test below would pass for the wrong reason.
    check("a judicial race still classifies as courts",
          {B.classify(r) for r in JUDICIAL}, {'courts'})

    both = sections_by_id(JUDICIAL + OTHERS)
    check("all five sections are emitted",
          sorted(both), ['courts', 'state-house', 'state-senate',
                         'statewide', 'us-house'])
    check("courts is emitted empty", both['courts']['races'], [])
    check("courts keeps its label", bool(both['courts'].get('label')), True)

    # Judicial races present or absent must make no difference anywhere else.
    check("excluding judicial changes no other section",
          sections_by_id(OTHERS), {k: v for k, v in both.items()})

    check("the other sections still fill",
          {k: len(v['races']) for k, v in both.items() if k != 'courts'},
          {'statewide': 1, 'us-house': 1, 'state-senate': 1, 'state-house': 1})

    # A judicial-only build is the realistic pre-election case for that tab.
    only = sections_by_id(JUDICIAL)
    check("a judicial-only build yields no offices at all",
          sum(len(s['races']) for s in only.values()), 0)


if __name__ == "__main__":
    print("ballot preview section policy:")
    cases()
    if failures:
        print(f"\n{len(failures)} failure(s)")
        sys.exit(1)
    print("\nAll checks passed.")
