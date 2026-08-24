#!/usr/bin/env python3
"""Enrich presidential-laws.json with GovInfo (GPO) provenance.

For each enacted law we can map to a GovInfo PLAW package, add authoritative,
user-facing provenance fields alongside the Congress.gov data:

    govinfoPackageId   e.g. "PLAW-119publ102"
    officialTextUrl    GovInfo details page for the enrolled law (public, no key)
    officialPdfUrl     the enrolled-law PDF on govinfo.gov (public, no key)
    sha256Pdf          SHA-256 of that PDF, as published by GPO (from PREMIS)
    gpoAuthenticated   True — GovInfo/GPO publishes this as an authenticated,
                       digitally-signed document
    lawDateIssued      GovInfo dateIssued (the enrolled-law date)

The package id is derived from the Congress.gov actionText — "Became Public Law
No: 119-102" -> PLAW-119publ102, "Became Private Law No: 119-2" -> PLAW-119pvtl2.
A law whose actionText isn't an enactment (or that GovInfo hasn't published yet —
GovInfo lags Congress.gov by days) is left unenriched and picked up on a later
run. Every step is best-effort and non-fatal.

Public links point at www.govinfo.gov content URLs, which need no API key, so the
key is never exposed to the browser. The API key is used only server-side here to
confirm the package exists and to read the PREMIS hash.

Auth: GOVINFO_API_KEY (a free api.data.gov key, held as a repo secret in CI).
Falls back to DEMO_KEY for local spot-checks (30 req/hr — not a full build).

Run: python scripts/enrich_laws_with_govinfo.py [path-to-presidential-laws.json]
"""

import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from lib.http import fetch_bytes, fetch_json

API_BASE     = "https://api.govinfo.gov"
CONTENT_BASE = "https://www.govinfo.gov"
API_KEY      = os.environ.get('GOVINFO_API_KEY') or 'DEMO_KEY'

DEFAULT_FILE = "assets/data/presidential-laws.json"

# "Became Public Law No: 119-102." / "Became Private Law No: 119-2."
_LAW_RE = re.compile(r'Became\s+(Public|Private)\s+Law\s+No[:.]?\s*(\d+)-(\d+)', re.I)


def _local(tag):
    """Local name of a possibly-namespaced XML tag ('{ns}object' -> 'object')."""
    return tag.rsplit('}', 1)[-1]


def package_id(law):
    """GovInfo PLAW package id for a law, or None if it can't be derived."""
    m = _LAW_RE.search(law.get('actionText') or '')
    if m:
        kind, congress, num = m.group(1).lower(), m.group(2), m.group(3)
        seg = 'publ' if kind == 'public' else 'pvtl'
        return f"PLAW-{congress}{seg}{num}"
    # Fallback: an explicit publicLawNumber like "119-102" (public laws only).
    pln = law.get('publicLawNumber')
    if pln and re.fullmatch(r'\d+-\d+', pln):
        congress, num = pln.split('-')
        return f"PLAW-{congress}publ{num}"
    return None


def _keyed(url):
    return f"{url}?api_key={API_KEY}"


def govinfo_summary(pkg):
    """Package summary dict, or None (404 = not yet published, or fetch failed)."""
    return fetch_json(_keyed(f"{API_BASE}/packages/{pkg}/summary"),
                      retries=3, backoff=5, redact=API_KEY, label=pkg,
                      quiet_statuses=(404,))


def pdf_sha256(pkg):
    """SHA-256 of the package's PDF from its PREMIS fixity, or None. Best-effort."""
    raw = fetch_bytes(_keyed(f"{API_BASE}/packages/{pkg}/premis"),
                      retries=2, backoff=5, redact=API_KEY,
                      label=f"{pkg} premis", quiet_statuses=(404,))
    if not raw:
        return None
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return None
    # Each <object> carries an <originalName> and a fixity <messageDigest>;
    # return the digest of the object whose name is the PDF rendition.
    for obj in root.iter():
        if _local(obj.tag) != 'object':
            continue
        name = digest = None
        for el in obj.iter():
            lt = _local(el.tag)
            if lt == 'originalName':
                name = (el.text or '').strip()
            elif lt == 'messageDigest':
                digest = (el.text or '').strip()
        if name and name.lower().endswith('.pdf') and digest:
            return digest
    return None


def public_urls(pkg):
    """(details page, enrolled PDF) — both public, no API key required."""
    return (f"{CONTENT_BASE}/app/details/{pkg}",
            f"{CONTENT_BASE}/content/pkg/{pkg}/pdf/{pkg}.pdf")


def enrich(law):
    """Add GovInfo provenance fields to one law in place. True if it changed."""
    if law.get('govinfoPackageId'):
        return False  # already enriched (idempotent)
    pkg = package_id(law)
    if not pkg:
        return False  # not an enactment we can map

    summary = govinfo_summary(pkg)
    if summary is None:
        return False  # not yet in GovInfo (lag) or fetch failed — try again later

    details, pdf = public_urls(pkg)
    law['govinfoPackageId'] = pkg
    law['officialTextUrl']  = details
    law['officialPdfUrl']   = pdf
    law['gpoAuthenticated'] = True
    law['lawDateIssued']    = summary.get('dateIssued')
    law['sha256Pdf']        = pdf_sha256(pkg)  # best-effort; may be None
    return True


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    path = argv[0] if argv else DEFAULT_FILE

    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    laws = data.get('laws', [])
    key_note = 'DEMO_KEY (rate-limited)' if API_KEY == 'DEMO_KEY' else 'GOVINFO_API_KEY'
    print(f"Enriching {len(laws)} law(s) via GovInfo [{key_note}]...")

    changed = 0
    for law in laws:
        try:
            if enrich(law):
                changed += 1
                sha = 'sha256' if law.get('sha256Pdf') else 'no-sha'
                print(f"  {law.get('billLabel')} -> {law['govinfoPackageId']} [{sha}]")
        except Exception as exc:  # noqa: BLE001 - one bad law must not abort the run
            print(f"  {law.get('billLabel')}: enrichment error (non-fatal): {exc}")

    if changed:
        data.setdefault('metadata', {})['govinfoEnrichedAt'] = \
            datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"Enriched {changed} law(s); wrote {path}")
    else:
        print("No laws enriched (already done, unmapped, or not yet published in GovInfo).")


if __name__ == '__main__':
    main()
