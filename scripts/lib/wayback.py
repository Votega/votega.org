"""Minimal Wayback Machine client: find an existing snapshot, or ask for one.

Small and stateless on purpose. enrich_ga_executive_orders.py carries a heavier
copy (rate-limit pacing, circuit breakers) tuned to a ~hundreds-of-orders sweep;
a caller archiving a handful of files per run does not need that machinery, only
the guarantee that a failure returns None rather than raising or hanging.

    snapshot_for(url)  -> https snapshot URL of the closest capture, or None
    save_now(url)      -> snapshot URL named by a fresh capture, or None
    archive(url)       -> snapshot_for, else save_now; None on any failure

None always means "not archived (yet)". It never means the file is gone.
"""

import json
import re
import urllib.request
from urllib.parse import quote

UA = 'votega.org/1.0 (public-records archiver; https://www.votega.org)'


def snapshot_for(url, timeout=20):
    api = 'https://archive.org/wayback/available?url=' + quote(url, safe='')
    req = urllib.request.Request(api, headers={'User-Agent': UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode('utf-8', 'replace'))
    except Exception:  # noqa: BLE001 - unreachable, throttled or malformed: not archived
        return None
    snap = ((data or {}).get('archived_snapshots') or {}).get('closest') or {}
    if snap.get('available') and snap.get('url') and str(snap.get('status', '200')) == '200':
        return snap['url'].replace('http://', 'https://')
    return None


def save_now(url, timeout=60):
    req = urllib.request.Request('https://web.archive.org/save/' + url, headers={'User-Agent': UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            loc = r.headers.get('Content-Location')
            if loc:
                return 'https://web.archive.org' + loc if loc.startswith('/') else loc
            m = re.search(r'<([^>]+)>;\s*rel="memento"', r.headers.get('Link') or '')
            if m:
                return m.group(1).replace('http://', 'https://')
    except Exception:  # noqa: BLE001 - 429, 5xx, timeout: leave for a later run
        return None
    return None


def archive(url):
    return snapshot_for(url) or save_now(url)
