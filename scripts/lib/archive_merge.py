"""Combine a place's primary meetings feed with an older ARCHIVE feed.

A place can change systems (Floyd County: a Granicus archive to Sept 2022 - Jan
2026, then CivicClerk from Feb 2026). `domains.meetings` carries one primary
platform; an optional `archive:` sub-block carries a second platform config of the
same shape (its own platform, URLs, body_map/include/exclude/body_label). The run
fetches both, scopes each by its own body rules, and merges here.

Rules (pure, no network):
  * Overlap key is (date, body). The PRIMARY wins: an archive row whose key the
    primary also holds is dropped, never blended - two systems rarely agree on
    titles or file URLs, and mixing fields produces a record neither published.
  * Archive rows with no primary counterpart are kept as-is.
  * Result is newest-first, like every adapter's output.
  * If the archive could not be fetched, rows from the previous published file
    that the primary does not cover and that are OLDER than the primary's earliest
    meeting are carried forward - a transient archive outage must not delete
    history (CLAUDE.md: never overwrite good data with worse data).
"""


def _key(m):
    return (m.get('date'), ' '.join((m.get('body') or '').lower().split()))


def merge_archive(primary, archive):
    """primary, archive: lists of meeting dicts. Returns the merged list."""
    seen = {_key(m) for m in primary}
    extra = [m for m in (archive or []) if _key(m) not in seen]
    merged = list(primary) + extra
    merged.sort(key=lambda m: m.get('date') or '', reverse=True)
    return merged


def carry_forward_history(primary, previous):
    """Archive-outage fallback: previous rows older than every primary meeting."""
    dates = [m.get('date') for m in primary if m.get('date')]
    if not dates:
        return []
    start = min(dates)
    return [m for m in (previous or [])
            if m.get('date') and m['date'] < start]
