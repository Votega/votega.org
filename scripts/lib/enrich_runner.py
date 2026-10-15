#!/usr/bin/env python3
"""Per-place error containment for the local-government meeting enrichers.

The three enrichers (enrich_granicus_meetings.py, enrich_ocr_meetings.py,
enrich_legistar_meetings.py) all had the same shape, and the same two structural
weaknesses, in their place loop:

  1. No error boundary per place. Any exception out of one meeting's document —
     and these read whatever a county's server happens to serve — aborted the
     whole multi-place run.
  2. local-flags.json was written ONCE, after the loop. So when the loop raised,
     every place that had already succeeded lost its flag update: its own
     local-<slug>-meetings-enriched.json sidecar had been written inside the
     loop and survived, but the hub flags file was never written, leaving the
     sidecars and the flags file inconsistent.

That is not hypothetical. On 2026-10-14 a relative redirect `Location` in
Catoosa raised ValueError out of a document fetch and the Granicus run died
after Barrow, Cherokee and Spalding had been enriched, so none of their flag
updates landed. The specific ValueError was fixed; this module fixes the shape,
so the next unexpected exception — a malformed PDF, a surprise from classify(),
a decode error — costs one place instead of the run.

Two rules, applied by run_places() so no enricher (or a future fourth one) can
forget them:

  * A place's failure is annotated and skipped; the remaining places still run.
    A failed place writes nothing at all, so its existing sidecar and its
    existing flag entry are left intact — the same "never overwrite good data
    with nothing" discipline as the enrichers' own `if not enriched: continue`
    guard, which is why the per-place callable signals a skip by returning None
    rather than by raising.
  * local-flags.json is written as each place completes, not once at the end, so
    neither a later exception nor a hard kill (a workflow timeout) can discard a
    place that already succeeded. write_flags_file merges into whatever is on
    disk, so writing one slug at a time still leaves alone the ~36 places the
    other enrichers own.

The run still exits non-zero when any place failed, so notify-workflow-failure
opens an issue — but only after every place that COULD succeed has. That means
the workflow steps must be `continue-on-error: true` with the failure surfaced
at the end of the job (the pattern update-local-government.yml already uses for
validate_place_meetings.py), or a contained failure would still skip the commit
step and discard the healthy places' work one layer up.
"""

import os
import sys
import traceback

from lib.meeting_topics import write_flags_file


def run_places(places, out_dir, enrich_place):
    """Run `enrich_place` over `places`, containing a failure to its own place.

    `places` is the (place, arg) sequence the enrichers' own *_places() helpers
    already return — arg is the meetings config for the Granicus/OCR enrichers
    and the Legistar client id for the Legistar one.

    `enrich_place(place, arg)` does one place's work, including writing that
    place's enriched sidecar, and returns the place's flag_entry() for
    local-flags.json — or None to skip it (no meetings file, nothing classified),
    which leaves that place's committed data untouched.

    Returns (done, failed): the slugs that produced a flag entry and the slugs
    that raised. The caller decides the exit status; see the module docstring for
    why that has to be non-zero without aborting the remaining places.
    """
    done, failed = [], []
    for place, arg in places:
        slug = place['slug']
        try:
            flags = enrich_place(place, arg)
        except Exception as e:
            # Deliberately broad: the point is that an UNANTICIPATED exception
            # from one county's document costs that county only. The traceback
            # goes to stderr so the run still shows what actually broke.
            failed.append(slug)
            print('::error::enriching %s failed (%s: %s) - left its existing '
                  'data intact and carried on with the other places'
                  % (slug, type(e).__name__, e))
            print('  ERROR: %s raised %s - skipping this place'
                  % (slug, type(e).__name__), file=sys.stderr)
            traceback.print_exc()
            continue
        if flags is None:
            continue
        # Written per place, not once at the end: see the module docstring.
        write_flags_file(out_dir, {slug: flags})
        done.append(slug)
    return done, failed


def report(done, failed, out_dir):
    """Print the run summary and return the process exit status.

    Exits non-zero when any place failed, so the scheduled workflow's
    failure-notifier still opens an issue — after every other place is done.
    """
    if done:
        print('Wrote %s (%d place(s): %s)'
              % (os.path.join(out_dir, 'local-flags.json'), len(done), ', '.join(done)))
    if not failed:
        return 0
    msg = ('%d place(s) failed and were left unchanged: %s'
           % (len(failed), ', '.join(failed)))
    print('::error::%s' % msg)
    print('FAILED: %s' % msg, file=sys.stderr)
    return 1
