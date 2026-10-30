#!/usr/bin/env python3
"""Assert the ballot preview drops judicial races and keeps District Attorney ones.

Both live in the `courts` section, so the two policies are easy to confuse and a
fix to one has already broken the other:

  * Judicial races are nonpartisan and decided at the May general primary, so the
    November preview does not advertise them. On election night the page is
    rebuilt from the SoS CSV by build_results_json.py, which buckets judicial
    contests into this same section, so results appear with nothing flipped.
  * District Attorney races ARE on the November ballot and partisan. An earlier
    version excluded the whole `courts` SECTION to hide the judicial races and
    took all ten DA races off the page with it.

So the exclusion is keyed on the race's `level`, and these checks pin that:
judicial out, DA in, every other section untouched, and classify() still
RECOGNISING judicial as courts - the exclusion is a policy on top of
classification, not a hole in it.

The DA office name is pinned to the SoS's own spelling, because the office name
is the key the page is rebuilt under: get it wrong and the ten races look like
ten new offices appearing and ten disappearing when the real results land.

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
    party = kw.pop('party', 'Republican')
    nonpartisan = kw.pop('nonpartisan', False)
    general = ({'candidates': [cand]} if nonpartisan
               else {'ballots': {party: [cand]}})
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

DA = [
    race(level='local', chamber='District Attorney',
         circuit='Atlantic Judicial Circuit', cname='Billy Joe Nelson Jr.'),
    race(level='local', chamber='District Attorney',
         circuit='Rockdale Judicial Circuit', party='Democrat',
         cname='Alisha Adams Johnson'),
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
    # by a section mysteriously filling up or emptying again.
    check("judicial is the excluded level",
          B.PREVIEW_EXCLUDED_LEVELS, {'state-judicial'})

    # If this regressed to None the judicial checks below would pass for the
    # wrong reason.
    check("a judicial race still classifies as courts",
          {B.classify(r) for r in JUDICIAL}, {'courts'})
    check("a DA race classifies as courts",
          {B.classify(r) for r in DA}, {'courts'})

    everything = sections_by_id(JUDICIAL + DA + OTHERS)
    check("all five sections are emitted",
          sorted(everything), ['courts', 'state-house', 'state-senate',
                               'statewide', 'us-house'])

    # courts holds the DA races and ONLY the DA races.
    check("courts holds just the DA races",
          [r['office'] for r in everything['courts']['races']],
          ['District Attorney - Atlantic Judicial Circuit',
           'District Attorney - Rockdale Judicial Circuit'])

    # The office name is the key the page is rebuilt under on election night, and
    # the SoS writes an ASCII hyphen where races.json's displayTitle has an em
    # dash. ga-primary-results.json carries all ten in this exact form.
    check("the DA office name matches the SoS spelling",
          B.office_name(DA[0], 'courts'),
          'District Attorney - Atlantic Judicial Circuit')

    # A DA race is partisan: its candidates come from `ballots`, not the flat
    # `candidates` list a judicial race uses. Reading the wrong shape yields an
    # empty contest list, which build_sections() then drops silently.
    contests = B.build_contests(DA[1], 'courts', {}, {})
    check("a DA contest carries its party and candidate",
          [(c['party'], [k['name'] for k in c['candidates']]) for c in contests],
          [('dem', ['Alisha Adams Johnson'])])

    # Judicial races present or absent must make no difference anywhere.
    check("excluding judicial changes nothing else",
          sections_by_id(DA + OTHERS), everything)

    check("the other sections still fill",
          {k: len(v['races']) for k, v in everything.items() if k != 'courts'},
          {'statewide': 1, 'us-house': 1, 'state-senate': 1, 'state-house': 1})

    # A judicial-only build is the case that used to be the whole courts section.
    only = sections_by_id(JUDICIAL)
    check("a judicial-only build yields no offices at all",
          sum(len(s['races']) for s in only.values()), 0)
    check("courts is still emitted when it is empty",
          [s['id'] for s in B.build_sections(JUDICIAL, {}, {})],
          ['statewide', 'us-house', 'state-senate', 'state-house', 'courts'])


if __name__ == "__main__":
    print("ballot preview section policy:")
    cases()
    if failures:
        print(f"\n{len(failures)} failure(s)")
        sys.exit(1)
    print("\nAll checks passed.")
