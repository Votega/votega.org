#!/usr/bin/env python3
"""One place's failure must not discard another place's completed work.

The three local-government enrichers (Granicus, OCR, Legistar) share a place
loop, and it used to share two structural faults:

  * No error boundary per place, so any exception out of one county's document
    aborted the whole multi-county run.
  * local-flags.json written ONCE after the loop, so when the loop raised, every
    place that had already succeeded lost its flag update — its sidecar was
    written inside the loop and survived, leaving the sidecars and the hub flags
    file inconsistent.

That is the 2026-10-14 Granicus run: a relative redirect Location in Catoosa
raised ValueError and the run died after Barrow, Cherokee and Spalding had been
enriched, so none of their flags landed. These tests pin the fix in
lib/enrich_runner.py, with no network and no repo writes (everything runs
against a temp DATA_DIR, and the per-place callable is a fake).

Run: python scripts/test_enrich_containment.py
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.enrich_runner import run_places, report  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print("  ok   %s" % label)
    else:
        print("  FAIL %s: got %r, want %r" % (label, got, want))
        failures.append(label)


def place(slug):
    return {'slug': slug, 'name': slug.title()}


def flags(*names):
    """A flag entry shaped like lib.meeting_topics.flag_entry()'s output."""
    return {'flags': list(names), 'dataCenterItems': []}


def read_flags(out_dir):
    with open(os.path.join(out_dir, 'local-flags.json'), encoding='utf-8') as f:
        return json.load(f)


PLACES = [(place(s), {'platform': 'granicus'})
          for s in ('barrow', 'cherokee', 'spalding', 'catoosa')]


# ---------------------------------------------------------------------------
print("A failing place is skipped; every other place still completes")

out_dir = tempfile.mkdtemp()
try:
    seen = []

    def fake(p, cfg):
        seen.append(p['slug'])
        # Catoosa is the real case: a relative redirect Location that urllib
        # rejected with `ValueError: unknown url type`.
        if p['slug'] == 'catoosa':
            raise ValueError('unknown url type: /DocumentViewer.php?file=x.pdf')
        return flags('data-center') if p['slug'] == 'barrow' else flags()

    done, failed = run_places(PLACES, out_dir, fake)

    check('every place was attempted', seen,
          ['barrow', 'cherokee', 'spalding', 'catoosa'])
    check('the three healthy places completed', done,
          ['barrow', 'cherokee', 'spalding'])
    check('the failing place is reported', failed, ['catoosa'])

    doc = read_flags(out_dir)
    check('the flags file records every successful place',
          sorted(doc['places']), ['barrow', 'cherokee', 'spalding'])
    check('and not the failing one', 'catoosa' in doc['places'], False)
    check("the successful place's own flags are intact",
          doc['places']['barrow']['flags'], ['data-center'])
    check('the flags file carries a generatedAt',
          bool(doc.get('metadata', {}).get('generatedAt')), True)

    check('the run exits non-zero so the failure notifier still fires',
          report(done, failed, out_dir), 1)
finally:
    shutil.rmtree(out_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
print("\nA place that fails FIRST does not block the places after it")

out_dir = tempfile.mkdtemp()
try:
    def fake_first_fails(p, cfg):
        if p['slug'] == 'barrow':
            raise RuntimeError('poppler segfaulted on a malformed PDF')
        return flags()

    done, failed = run_places(PLACES, out_dir, fake_first_fails)
    check('the later places all completed', done,
          ['cherokee', 'spalding', 'catoosa'])
    check('the first place is the only failure', failed, ['barrow'])
    check('their flags landed', sorted(read_flags(out_dir)['places']),
          ['catoosa', 'cherokee', 'spalding'])
finally:
    shutil.rmtree(out_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
print("\nFlags are written per place, so a hard kill keeps what finished")

# Not just "written in a finally": a run that is killed outright (a workflow
# timeout) never reaches a finally either, so the write has to happen as each
# place completes. Simulated by letting the fake raise something run_places does
# NOT catch — a BaseException, which is what a kill looks like.
out_dir = tempfile.mkdtemp()
try:
    def fake_killed(p, cfg):
        if p['slug'] == 'spalding':
            raise KeyboardInterrupt()
        return flags()

    try:
        run_places(PLACES, out_dir, fake_killed)
        check('the kill propagated', False, True)
    except KeyboardInterrupt:
        check('the kill propagated', True, True)

    check('the places that finished before the kill are already on disk',
          sorted(read_flags(out_dir)['places']), ['barrow', 'cherokee'])
finally:
    shutil.rmtree(out_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
print("\nwrite_flags_file's merge semantics survive the per-place writes")

# The enrichers own only their own slugs: a Granicus run must leave the ~36
# places the OCR and Legistar enrichers contribute exactly as they were.
out_dir = tempfile.mkdtemp()
try:
    with open(os.path.join(out_dir, 'local-flags.json'), 'w', encoding='utf-8') as f:
        json.dump({'metadata': {'generatedAt': '2026-01-01T00:00:00Z'},
                   'places': {'fulton': flags('rezoning'),
                              'newton': flags('data-center'),
                              'barrow': flags('stale-value')}}, f)

    done, failed = run_places(PLACES, out_dir, lambda p, cfg: flags('alpr'))
    doc = read_flags(out_dir)
    check('all four enriched places are present', failed, [])
    check("the other enrichers' places are untouched",
          [doc['places']['fulton'], doc['places']['newton']],
          [flags('rezoning'), flags('data-center')])
    check('this run overwrote its own place', doc['places']['barrow']['flags'],
          ['alpr'])
    check('nothing was dropped', sorted(doc['places']),
          ['barrow', 'catoosa', 'cherokee', 'fulton', 'newton', 'spalding'])
finally:
    shutil.rmtree(out_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
print("\nA skip is not a failure, and writes nothing")

# Returning None is how a place says "no meetings file yet" or "nothing
# classified" — the existing never-overwrite-good-data-with-nothing guard. It
# must leave that place's flag entry exactly as committed, and must not make the
# run fail.
out_dir = tempfile.mkdtemp()
try:
    with open(os.path.join(out_dir, 'local-flags.json'), 'w', encoding='utf-8') as f:
        json.dump({'metadata': {}, 'places': {'cherokee': flags('data-center')}}, f)

    done, failed = run_places(
        PLACES, out_dir,
        lambda p, cfg: None if p['slug'] in ('cherokee', 'catoosa') else flags())
    check('skipped places are not in done', done, ['barrow', 'spalding'])
    check('skipped places are not failures', failed, [])
    check('a skipped place keeps its committed flags',
          read_flags(out_dir)['places']['cherokee'], flags('data-center'))
    check('a skipped place with no prior entry stays absent',
          'catoosa' in read_flags(out_dir)['places'], False)
    check('an all-clean run exits zero', report(done, failed, out_dir), 0)
finally:
    shutil.rmtree(out_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
print("\nEvery enricher routes its place loop through run_places")

# The containment is only real if all three drivers use it — and a fourth
# enricher added later is the likeliest place to reintroduce the bug.
import re  # noqa: E402

for name in ('enrich_granicus_meetings', 'enrich_ocr_meetings',
             'enrich_legistar_meetings'):
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            name + '.py'), encoding='utf-8').read()
    check('%s calls run_places' % name, 'run_places(' in src, True)
    check('%s exits via report()' % name,
          bool(re.search(r'sys\.exit\(report\(', src)), True)
    # A direct write_flags_file call in a driver would be the once-after-the-loop
    # write coming back.
    check('%s does not write the flags file itself' % name,
          'write_flags_file(' in src, False)

print("")
if failures:
    print("FAILED: %s" % ", ".join(failures))
    sys.exit(1)
print("All enricher failure-containment invariants hold.")
