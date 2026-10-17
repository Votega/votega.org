#!/usr/bin/env python3
"""Paged reads of the Federal Register documents API, shared by the build-time
generators (presidential executive orders, Cabinet-department rules).

No key, no quota. The one trap is that a short list is indistinguishable from a
real one once written, so `fetch_all` returns None if ANY page failed rather
than the pages it did get.
"""

from lib.http import fetch_json

DOCUMENTS_URL = "https://www.federalregister.gov/api/v1/documents.json"
AGENCIES_URL = "https://www.federalregister.gov/api/v1/agencies.json"


def fetch_all(conditions, fields, fetcher=fetch_json, per_page=100, label="Federal Register"):
    """Every document matching `conditions` (an already-encoded query fragment such
    as 'conditions%5Btype%5D%5B%5D=RULE'), restricted to `fields`, newest first.
    Returns a list of {field: value} dicts, or None if any page failed.

    The API reports at most 10,000 in `count` for a result set that large, so
    callers must filter (by date) to stay far below it."""
    field_qs = "".join(f"&fields[]={f}" for f in fields)
    out, page, total_pages = [], 1, 1
    while page <= total_pages:
        url = (f"{DOCUMENTS_URL}?{conditions}&per_page={per_page}&page={page}"
               f"&order=newest{field_qs}")
        data = fetcher(url, label=f"{label} page {page}")
        if not isinstance(data, dict) or "results" not in data:
            return None
        total_pages = data.get("total_pages") or 1
        out.extend({f: r.get(f) for f in fields} for r in data["results"])
        page += 1
    return out
