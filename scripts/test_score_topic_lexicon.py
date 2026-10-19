#!/usr/bin/env python3
"""Invariant checks for score_topic_lexicon.py — the offline lexicon scorer.

The scorer's job is to make a lib/meeting_topics.py edit measurable: it classifies
the cached corpus with the lexicon as it stands and diffs that against the tags the
committed sidecars recorded. Decisions get made from those two lists, so the logic
behind them is pinned here:

  * production is REPRODUCED, not approximated — a document the enrichers classify
    on its agenda head only (a combined agenda packet) is scored the same way, or
    the scorer would report matches the site never made;
  * the diff buckets are right — newly-matching vs stopped-matching vs not-in-any-
    sidecar, because confusing the third with either of the first two would invent
    a precision or recall change that did not happen;
  * a dead keyword (one no document contains) is counted as such.

Run: python scripts/test_score_topic_lexicon.py     (no network, no repo writes)
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import score_topic_lexicon as scorer  # noqa: E402
from lib.text_cache import open_cache  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print("  ok   %s" % label)
    else:
        print("  FAIL %s: got %r, want %r" % (label, got, want))
        failures.append(label)


tmp = tempfile.mkdtemp(prefix='votega-scorer-test-')
try:
    root = os.path.join(tmp, 'corpus')
    w = open_cache(root, writable=True)

    # Baseline says alpr, but the text's only surveillance phrase is "gunfire
    # detection" — real language from a Columbus SoundThinking contract that the
    # lexicon does NOT carry. This is the recall-loss bucket.
    w.record('bibb', '1', 'To authorize a gunfire detection and alert program.')
    # Baseline says nothing; the text names Flock. This is the new-match bucket.
    w.record('bibb', '2', 'Approve agreement with Flock Safety for cameras.')
    # Clean both ways.
    w.record('bibb', '3', 'Rezoning application for a residential subdivision.')
    # Agenda packet: the alpr term sits AFTER the first ADJOURN, so production's
    # agenda_head trim must drop it and the scorer must drop it too.
    w.record('carrollton', '4',
             'AGENDA. Call to order. ADJOURN. PRIOR MINUTES: Flock Safety contract.',
             trimmed=True)
    # Same text, NOT marked trimmed — the term is in scope, so it must match. Proves
    # the trim is driven by the manifest flag, not by the text.
    w.record('cobb', '5',
             'AGENDA. Call to order. ADJOURN. PRIOR MINUTES: Flock Safety contract.',
             trimmed=False)
    # Cached but absent from every sidecar: neither a new match nor a lost one.
    w.record('nowhere', '6', 'ALPR camera purchase for the sheriff.')
    w.flush()

    # Stand in for the committed sidecars so the test does not depend on live data.
    scorer.sidecar_tags = lambda: {
        'bibb/1': ['alpr'],
        'bibb/2': ['contract'],
        'bibb/3': ['rezoning'],
        'carrollton/4': ['appointment'],
        'cobb/5': ['appointment'],
    }

    # The scorer reports to stdout; capture it and assert on the summary lines.
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    argv = sys.argv
    sys.argv = ['score_topic_lexicon.py', '--cache', root, '--show', '50']
    try:
        with redirect_stdout(buf):
            rc = scorer.main()
    finally:
        sys.argv = argv
    out = buf.getvalue()

    def summary(field):
        for line in out.splitlines():
            if line.strip().startswith(field):
                return line.split()[-1] if field == 'corpus' else line.split()[len(field.split())]
        return None

    check('exit code is 0 on a populated corpus', rc, 0)
    check('every document is readable', '6 documents (6 readable, 0 missing)' in out, True)

    # bibb/2 (Flock) and cobb/5 (untrimmed Flock) and nowhere/6 (ALPR) match.
    # bibb/1 (gunfire detection), bibb/3 (rezoning) and carrollton/4 (trimmed) do not.
    check('three documents match', 'matches         3' in out, True)
    check('the trimmed packet does not match', 'carrollton/4' not in out, True)
    check('the untrimmed twin does match', 'newly matching  2' in out, True)

    # bibb/1 is the only row the sidecar flags that the lexicon now misses.
    check('one document would stop matching', 'stopped         1' in out, True)
    check('the stopped row is named', 'bibb/1' in out.split('WOULD STOP MATCHING')[1],
          True)
    check('the gunfire-detection gap is visible as lost recall',
          'A narrowed or removed' in out, True)

    # nowhere/6 has no sidecar row, so it is neither newly-matching nor stopped.
    check('a row with no sidecar is reported undiffed',
          'have no committed sidecar row' in out, True)
    check('the undiffed row is not counted as a new match',
          'nowhere/6' not in out.split('WOULD NEWLY MATCH')[1].split('WOULD STOP')[0],
          True)

    # Dead keywords: most of the lexicon finds nothing in six short strings.
    check('dead keywords are counted', 'dead keywords' in out, True)
    check('a fired keyword is not called dead',
          'flock' not in out.split('dead keywords')[1], True)

    # An empty corpus must say how to populate itself and exit non-zero, not crash.
    buf2 = io.StringIO()
    sys.argv = ['score_topic_lexicon.py', '--cache', os.path.join(tmp, 'absent')]
    try:
        with redirect_stdout(buf2):
            rc2 = scorer.main()
    finally:
        sys.argv = argv
    check('empty corpus exits non-zero', rc2, 1)
    check('empty corpus explains how to populate',
          '--text-cache' in buf2.getvalue(), True)

    # The scorer must own no keywords — the duplication that made the old probe
    # measure a matcher that did not ship.
    import ast
    src = ast.parse(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      'score_topic_lexicon.py'),
                         encoding='utf-8').read())
    imported = {a.name for n in ast.walk(src) if isinstance(n, ast.ImportFrom)
                and n.module == 'lib.meeting_topics' for a in n.names}
    check('scorer sources its matcher from lib.meeting_topics',
          {'classify', 'matched_terms'} <= imported, True)
    defined = {t.id for n in ast.walk(src) if isinstance(n, ast.Assign)
               for t in n.targets if isinstance(t, ast.Name)}
    check('scorer defines no keyword collection of its own',
          sorted(defined & {'ALPR_KEYWORDS', 'TOPIC_RULES', 'TOPIC_WORD_RULES',
                            'CANDIDATES', '_MATCHERS'}), [])
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if failures:
    sys.exit('FAILED: %s' % ', '.join(failures))
print('All lexicon-scorer checks passed.')
