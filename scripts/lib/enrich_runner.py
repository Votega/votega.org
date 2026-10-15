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

The INNER boundary, run_meetings(), is the same argument one level down. A place
loop reads ~25 documents from a county's own server, and the per-place boundary
above still charged a county's entire window to one malformed PDF: the place
raised, wrote nothing, and its committed sidecar stayed as it was — so the 24
readable meetings were thrown away too, and the newly-scraped ones never got
tagged at all. run_meetings() wraps each meeting instead, with three rules:

  * A meeting that raises falls back to its CACHED record when the sidecar has
    one, exactly as the drivers' own `raw is None` path does. The sidecar IS the
    incremental cache, so a meeting already classified on an earlier run keeps
    its tags through a transient failure instead of silently vanishing from the
    place page.
  * A meeting that raises with no cached record is LOST — there is nothing
    truthful to publish for it. Losing a few is acceptable (the next run
    retries, and the window is republished whole each time), but losing a large
    share means the place's documents are broadly unreadable, and a sidecar
    written from the remainder would publish "nothing on recent agendas" for
    meetings we simply could not read. too_lossy() is that cut-off: past it the
    place is skipped entirely, which leaves its committed sidecar intact.
  * Lost meetings make the PLACE count as failed for exit-status purposes, so
    report() still exits non-zero and the failure-notifier opens an issue — the
    sidecar it wrote is short, and that is exactly what someone must look at. A
    place whose failing meetings ALL fell back to cache is NOT marked failed:
    nothing published is wrong, nothing shrank, and the next run re-fetches
    them anyway, so an issue there would be noise. Both cases are logged.

A place therefore reports two things, not one, and does it by returning a
PlaceOutcome(flags, lost) — flags None to skip the write, `lost` non-empty to
fail the run. A bare flag entry (or None) still works unchanged, so a driver
with no per-meeting failures to report needs no ceremony.
"""

import collections
import os
import sys
import traceback

from lib.meeting_topics import write_flags_file

# A place that could not read more than this share of its window is skipped
# rather than published short — see the module docstring. Deliberately generous:
# the common case is one bad document in 25 (4%), and the point of the inner
# boundary is that that case publishes the other 24.
MAX_LOST_SHARE = 0.25

# What a place reports back: its flag entry (None to skip the write, leaving its
# committed data intact) and the ids of meetings that failed with no cached
# record to fall back on. Returning a bare flag entry, or None, is still valid.
PlaceOutcome = collections.namedtuple('PlaceOutcome', 'flags lost')


def run_places(places, out_dir, enrich_place):
    """Run `enrich_place` over `places`, containing a failure to its own place.

    `places` is the (place, arg) sequence the enrichers' own *_places() helpers
    already return — arg is the meetings config for the Granicus/OCR enrichers
    and the Legistar client id for the Legistar one.

    `enrich_place(place, arg)` does one place's work, including writing that
    place's enriched sidecar, and returns the place's flag_entry() for
    local-flags.json — or None to skip it (no meetings file, nothing classified),
    which leaves that place's committed data untouched. It may instead return a
    PlaceOutcome(flags, lost) to report meetings it lost inside its own window
    (see run_meetings): `flags` is used exactly as above, and a non-empty `lost`
    marks the place failed even when its sidecar was written, because a short
    sidecar is precisely what wants a human's eye.

    Returns (done, failed): the slugs that produced a flag entry and the slugs
    that raised or lost meetings. A degraded place appears in BOTH — its flags
    landed and the run still fails. The caller decides the exit status; see the
    module docstring for why that has to be non-zero without aborting the
    remaining places.
    """
    done, failed = [], []
    for place, arg in places:
        slug = place['slug']
        try:
            outcome = enrich_place(place, arg)
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
        flags, lost = (outcome if isinstance(outcome, PlaceOutcome)
                       else (outcome, ()))
        if lost:
            # The place survived, but some of its meetings have no record at all
            # — published or skipped, that is a failure someone should see.
            failed.append(slug)
            print('::error::%s lost %d meeting(s) to unreadable documents (%s)'
                  % (slug, len(lost), ', '.join(str(m) for m in lost)))
        if flags is None:
            continue
        # Written per place, not once at the end: see the module docstring.
        write_flags_file(out_dir, {slug: flags})
        done.append(slug)
    return done, failed


def run_meetings(slug, window, enrich_one, meeting_id=None, cache=None):
    """Run `enrich_one` over one place's meetings, containing a failure to one.

    The inner half of the containment, and the reason it exists is in the module
    docstring: without it, one malformed document in a county's window costs the
    county's whole window.

    `enrich_one(meeting)` returns that meeting's enriched record, or None to drop
    it (nothing to read — a video-only row). `meeting_id` extracts the id used
    for logging and for the cache lookup (default: `meeting['id']`, which is what
    the Granicus and OCR sidecars key on). `cache` is the prior sidecar indexed
    by id — the drivers' incremental cache — or None for a driver that keeps
    none (Legistar reads the structured API every run).

    Returns (records, lost): the records to write, and the ids of meetings that
    raised with no cached record to stand in for them. A meeting that raised and
    HAS a cached record is in `records`, not `lost`: it keeps the tags an earlier
    run gave it, so a transient failure cannot silently un-flag a meeting.
    """
    get_id = meeting_id or (lambda m: m.get('id'))
    cache = cache or {}
    records, lost = [], []
    for meeting in window:
        mid = get_id(meeting)
        try:
            rec = enrich_one(meeting)
        except Exception as e:
            # Deliberately broad, for the same reason run_places' is: these read
            # whatever a county's server serves, and one unreadable document
            # must cost one meeting. The traceback goes to stderr so the run
            # still shows what actually broke.
            cached = cache.get(mid)
            print('    %s: enrichment raised %s (%s) — %s'
                  % (mid, type(e).__name__, e,
                     'kept its cached record' if cached else 'NO cached record, lost'))
            traceback.print_exc()
            if cached:
                records.append(cached)
            else:
                lost.append(mid)
            continue
        if rec:
            records.append(rec)
    if lost:
        print('  WARNING: %s could not read %d of %d meeting(s) in its window: %s'
              % (slug, len(lost), len(window), ', '.join(str(m) for m in lost)),
              file=sys.stderr)
    return records, lost


def too_lossy(slug, lost, window_size, max_share=MAX_LOST_SHARE):
    """True when a place lost too much of its window to publish the remainder.

    A sidecar is republished whole, so a place that read only a fraction of its
    meetings would publish "nothing on recent agendas" for the ones it could not
    read — worse than publishing nothing and leaving last run's sidecar in place.
    A couple of bad documents are below the cut-off and publish normally; the
    next run retries them either way.
    """
    if not lost or not window_size:
        return False
    if len(lost) <= max_share * window_size:
        return False
    print('  WARNING: %s lost %d of %d meeting(s) (over the %d%% cut-off) — '
          'leaving its existing data intact rather than publishing a short window'
          % (slug, len(lost), window_size, round(max_share * 100)))
    return True


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
    # "or lost meetings": a place in `failed` either raised (and was left
    # unchanged) or published a window short of meetings it could not read.
    msg = ('%d place(s) failed or lost meetings: %s'
           % (len(failed), ', '.join(failed)))
    print('::error::%s' % msg)
    print('FAILED: %s' % msg, file=sys.stderr)
    return 1
