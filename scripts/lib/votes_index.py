"""Which places have a recorded-votes file, derived from the files themselves.

`generate_meeting_votes.py` writes assets/data/local-<slug>-votes.json for a
CivicClerk or Legistar place whose portal publishes votes, and writes NO file
for one that does not. This module turns that into `_data/local_votes.json`,
read by Jekyll (the /local/ badge) and by the sibling-repo registry publisher:

    {"metadata": {"source": ..., "note": ...},
     "places": {<slug>: {"platform", "status", "meetings", "meetingsWithVotes",
                         "firstMeeting", "lastMeeting"}}}

status is "available" (a votes file exists) or "not-published" (the platform
has a vote reader, but the portal records none). A place on any other platform
is absent: there is no reader for it, which is not the same claim as "its
portal records none", and the registry publisher words them differently.

The index is built from what is on disk, never from what a run intended to
write, so it cannot disagree with the files, and it carries no timestamp, so a
quiet run rewrites nothing.
"""

import json
import os

READER_PLATFORMS = ('civicclerk', 'legistar')


def votes_path(data_dir, slug):
    return os.path.join(data_dir, 'local-%s-votes.json' % slug)


def build_index(places, data_dir):
    """`places` is the parsed places.yml list; returns the index payload."""
    out = {}
    for p in places:
        cfg = (p.get('domains') or {}).get('meetings') or {}
        platform = cfg.get('platform')
        if platform not in READER_PLATFORMS:
            continue
        slug = p['slug']
        entry = {'platform': platform, 'status': 'not-published'}
        path = votes_path(data_dir, slug)
        if os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                meetings = json.load(f).get('meetings') or []
            dates = sorted(m['date'][:10] for m in meetings if m.get('date'))
            entry.update({
                'status': 'available',
                'meetings': len(meetings),
                'meetingsWithVotes': sum(1 for m in meetings if m.get('items')),
                'firstMeeting': dates[0] if dates else None,
                'lastMeeting': dates[-1] if dates else None,
            })
        out[slug] = entry
    return {
        'metadata': {
            'source': 'Derived from assets/data/local-<slug>-votes.json by scripts/generate_meeting_votes.py',
            'note': 'Only places on a platform with a vote reader (CivicClerk, Legistar) appear. '
                    '"not-published" means the reader exists but the place\'s portal records no votes.',
        },
        'places': dict(sorted(out.items())),
    }
