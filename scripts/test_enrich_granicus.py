#!/usr/bin/env python3
"""Invariants of the Granicus agenda-document fetch (enrich_granicus_meetings.py).

fetch_agenda_html follows Granicus's one 302 by hand, so it owns the parts of
redirect handling that urllib would normally do for it. These tests pin the two
that bit us, with no network (module-level _get is swapped for a routing table).

⚠ A Location header may be RELATIVE. RFC 7231 §7.1.2 allows it, and Catoosa's
instance uses it for 11 of the first 35 documents we touch:

    Location: /DocumentViewer.php?file=catoosaga_<hash>.pdf&view=1

The old code passed that string straight back to urllib, which rejects a
non-absolute URL with `ValueError: unknown url type`. Barrow, Cherokee and
Spalding only ever send absolute S3 URLs, so the whole class of bug was
invisible until a fourth portal was onboarded — and because the Request was
built OUTSIDE _get's try block, the ValueError escaped the per-document error
handling and aborted the entire multi-county run, after three counties' work.

Run: python scripts/test_enrich_granicus.py      (no network, no repo writes)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import enrich_granicus_meetings as E

failures = []


def check(label, got, want):
    if got == want:
        print("  ok   %s" % label)
    else:
        print("  FAIL %s: got %r, want %r" % (label, got, want))
        failures.append(label)


class FakeNet(object):
    """Routing table standing in for enrich_granicus_meetings._get.

    Maps an exact URL -> (code, location, body). Any URL not in the table is a
    404, and the URLs actually requested are recorded so a test can assert that
    the resolved absolute URL — not the raw header — is what got fetched.
    """

    def __init__(self, routes):
        self.routes = routes
        self.requested = []

    def __call__(self, url, timeout=30):
        self.requested.append(url)
        return self.routes.get(url, (404, None, None))


def with_net(routes):
    net = FakeNet(routes)
    E._get = net
    return net


real_get = E._get
VIEWER = 'https://catoosaga.granicus.com/AgendaViewer.php?view_id=1&clip_id=258'

# ---------------------------------------------------------------------------
print("A relative Location is resolved against the viewer URL")

RELATIVE_LOC = '/DocumentViewer.php?file=catoosaga_72fb5834.pdf&view=1'
RESOLVED = 'https://catoosaga.granicus.com/DocumentViewer.php?file=catoosaga_72fb5834.pdf&view=1'
# DocumentViewer.php serves the PDF itself, which enrich_meeting routes to
# lib.pdf_text on the %PDF- magic bytes.
PDF = b'%PDF-1.7\r\nbody of the agenda'

net = with_net({VIEWER: (302, RELATIVE_LOC, None), RESOLVED: (200, None, PDF)})
check('the document bytes come back', E.fetch_agenda_html(VIEWER, retries=1), PDF)
check('the RESOLVED absolute url is what was fetched', net.requested, [VIEWER, RESOLVED])

# A relative Location without a leading slash resolves against the directory.
net = with_net({VIEWER: (302, 'DocumentViewer.php?file=x.pdf', None),
                'https://catoosaga.granicus.com/DocumentViewer.php?file=x.pdf': (200, None, PDF)})
check('a path-relative Location also resolves', E.fetch_agenda_html(VIEWER, retries=1), PDF)

# ---------------------------------------------------------------------------
print("\nAbsolute Locations behave exactly as before")

S3_VHOST = ('https://granicus_production_attachments.s3.amazonaws.com'
            '/catoosaga/2a78d1dc.pdf')
S3_PATH = ('https://s3.amazonaws.com/granicus_production_attachments'
           '/catoosaga/2a78d1dc.pdf')
net = with_net({VIEWER: (302, S3_VHOST, None), S3_PATH: (200, None, PDF)})
check('an S3 virtual-host target is still rewritten to path-style',
      E.fetch_agenda_html(VIEWER, retries=1), PDF)
check('the path-style url is the one fetched', net.requested[1], S3_PATH)

HTML = b'<html><body>Board of Commissioners agenda</body></html>'
net = with_net({VIEWER: (200, None, HTML)})
check('a direct 2xx is taken as-is', E.fetch_agenda_html(VIEWER, retries=1), HTML)

net = with_net({VIEWER: (302, 'https://catoosaga.granicus.com/core/error/404', None)})
check('an error-page redirect is an unpublished document, not a fetch',
      E.fetch_agenda_html(VIEWER, retries=1), None)
check('and the error page itself is never fetched', len(net.requested), 1)

net = with_net({VIEWER: (404, None, None)})
check('a 4xx on the viewer is non-retryable', E.fetch_agenda_html(VIEWER, retries=1), None)

# ---------------------------------------------------------------------------
print("\nA malformed URL is a handled failure, never a crash")

# Defense in depth: even if some future portal sends a Location that cannot be
# resolved into something urllib accepts, one unreadable document must not take
# the whole multi-county run down with it. This exercises the REAL _get.
E._get = real_get
for bad in ('/DocumentViewer.php?file=x.pdf', 'not a url at all', 'httpx://nope/x'):
    try:
        got = E._get(bad, timeout=5)
        ok = got == (None, None, None)
    except Exception as exc:
        ok = 'raised %s' % type(exc).__name__
    check('_get(%r) returns a failure tuple' % bad, ok, True)

print("")
if failures:
    print("FAILED: %s" % ", ".join(failures))
    sys.exit(1)
print("All Granicus agenda-fetch invariants hold.")
