#!/usr/bin/env python3
"""Enrich GA executive-order records with integrity, archival, and full text.

Runs after fetch_ga_executive_orders.py in the daily and backfill workflows.
Two layers, both best-effort and non-fatal:

Layer 1 — per-order JSON fields, written back into
          assets/data/ga-executive-orders-{year}.json:
    sha256      hex SHA-256 of the downloaded PDF
    bytes       size of the PDF in bytes
    fetchedAt   ISO-8601 (UTC) timestamp of the download
    archiveUrl  Wayback Machine snapshot URL (may be null if archiving failed)

Layer 2 — full text, written to assets/data/eo-text/{year}/{number}.txt:
    poppler's `pdftotext` first; if that yields too little text (a scanned or
    image-only PDF) the page images are rasterised with `pdftoppm` and run
    through Tesseract OCR.

Idempotent: an order that already carries a sha256 and has a committed text
file is skipped, so re-runs only touch what is missing. A single order that
cannot be downloaded, archived, or OCR'd is logged and skipped — it never
aborts the run.

Run as `python scripts/enrich_ga_executive_orders.py [years...]`, using the
same year syntax as fetch_ga_executive_orders.py (no args = current year).
Text extraction is a no-op where poppler / Tesseract are not installed (e.g. a
dev laptop); CI installs poppler-utils and tesseract-ocr.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from urllib.parse import quote

from lib.http import fetch_bytes, fetch_json
from fetch_ga_executive_orders import OUTPUT_DIR, parse_years

TEXT_DIR = os.path.join(OUTPUT_DIR, "eo-text")

# Below this many characters, assume pdftotext found no real text layer and
# fall back to OCR.
_MIN_TEXT_CHARS = 200

# Wayback archival is the slowest step (a save-now per order, rate-limited by
# archive.org). EO_ENRICH_ARCHIVE controls it:
#     '0'      skip archival entirely — e.g. during a large multi-year backfill,
#              then fill archives in later with an archive-on run.
#     '1'      (default, the daily job) archive orders that have never been
#              attempted; leave a recorded null alone so daily runs don't
#              re-hammer archive.org for orders it could not capture.
#     'retry'  (the manual archive sweep) also re-attempt orders whose recorded
#              archiveUrl is null. This is the pass that actually backfills the
#              nulls the daily job leaves behind.
_ARCHIVE_MODE = os.environ.get('EO_ENRICH_ARCHIVE', '1')
_ARCHIVE_ENABLED = _ARCHIVE_MODE != '0'
_ARCHIVE_RETRY_NULLS = _ARCHIVE_MODE == 'retry'

_PDF_HEADERS = {
    'User-Agent': 'votega.org/1.0 (executive-orders-enricher)',
    'Accept':     'application/pdf',
}


# ── Downloads ─────────────────────────────────────────────────────────────────

def download_pdf(url):
    """Fetch a PDF as bytes via the shared HTTP policy. None on failure."""
    return fetch_bytes(url, headers=_PDF_HEADERS, retries=3, backoff=5, label=url)


# ── Wayback archival (best-effort) ────────────────────────────────────────────

def _wayback_snapshot(url):
    """Return an existing Wayback snapshot URL for `url`, or None."""
    api = "https://archive.org/wayback/available?url=" + quote(url, safe='')
    data = fetch_json(api, retries=2, backoff=3, label="wayback-available", verbose=False)
    snap = ((data or {}).get('archived_snapshots') or {}).get('closest') or {}
    if snap.get('available') and snap.get('url'):
        return snap['url'].replace('http://', 'https://')
    return None


def _snapshot_from_save(url):
    """Trigger a Wayback save-now and return the snapshot URL it reports, or None.

    The save endpoint identifies the fresh capture in its response headers —
    `Content-Location` (a /web/<timestamp>/<url> path) and/or a `Link` header
    carrying rel="memento" — long before the availability API (queried by
    _wayback_snapshot) indexes it. Reading the URL straight from the save
    response is what lets a first attempt succeed instead of recording null.
    """
    req = urllib.request.Request("https://web.archive.org/save/" + url,
                                 headers=_PDF_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            loc = resp.headers.get('Content-Location')
            if loc:
                return "https://web.archive.org" + loc if loc.startswith('/') else loc
            link = resp.headers.get('Link') or ''
            m = re.search(r'<([^>]+)>;\s*rel="memento"', link)
            if m:
                return m.group(1).replace('http://', 'https://')
    except Exception as exc:  # noqa: BLE001 - archival must never abort enrichment
        print(f"    wayback save failed: {exc}")
    return None


def wayback_archive(url):
    """Existing snapshot if any; otherwise ask Wayback to save one, then re-check.

    Returns a snapshot URL or None. Fully best-effort — any failure yields None.
    """
    try:
        existing = _wayback_snapshot(url)
        if existing:
            return existing
        # Trigger a capture and take the snapshot URL from the save response.
        saved = _snapshot_from_save(url)
        if saved:
            return saved
        # The save may have started without reporting a URL; the availability
        # API lags the capture, so poll it a few times before giving up rather
        # than recording a null the same second the save was requested.
        for delay in (5, 15, 30):
            time.sleep(delay)
            snap = _wayback_snapshot(url)
            if snap:
                return snap
        return None
    except Exception as exc:  # noqa: BLE001 - archival must never abort enrichment
        print(f"    wayback failed: {exc}")
        return None


# ── Text extraction (Layer 2) ─────────────────────────────────────────────────

def _run(cmd, timeout):
    return subprocess.run(cmd, capture_output=True, timeout=timeout)


def pdftotext(pdf_path):
    """Extract an embedded text layer with poppler. '' if unavailable/empty."""
    if not shutil.which('pdftotext'):
        return ''
    try:
        proc = _run(['pdftotext', '-layout', '-nopgbrk', pdf_path, '-'], timeout=120)
        if proc.returncode == 0:
            return proc.stdout.decode('utf-8', errors='replace').strip()
        print(f"    pdftotext exit {proc.returncode}")
    except Exception as exc:  # noqa: BLE001
        print(f"    pdftotext failed: {exc}")
    return ''


def ocr_pdf(pdf_path, workdir):
    """Rasterise with pdftoppm and OCR each page with Tesseract. '' if unavailable."""
    if not (shutil.which('pdftoppm') and shutil.which('tesseract')):
        return ''
    try:
        prefix = os.path.join(workdir, 'page')
        proc = _run(['pdftoppm', '-r', '300', '-png', pdf_path, prefix], timeout=300)
        if proc.returncode != 0:
            print(f"    pdftoppm exit {proc.returncode}")
            return ''
        pages = sorted(f for f in os.listdir(workdir)
                       if f.startswith('page') and f.endswith('.png'))
        chunks = []
        for pg in pages:
            r = _run(['tesseract', os.path.join(workdir, pg), 'stdout'], timeout=180)
            if r.returncode == 0:
                chunks.append(r.stdout.decode('utf-8', errors='replace'))
        return '\n'.join(chunks).strip()
    except Exception as exc:  # noqa: BLE001
        print(f"    OCR failed: {exc}")
    return ''


def extract_text(pdf_bytes):
    """Best text available: pdftotext, then OCR fallback. Returns (text, method)."""
    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = os.path.join(tmp, 'order.pdf')
        with open(pdf_path, 'wb') as f:
            f.write(pdf_bytes)
        text = pdftotext(pdf_path)
        if len(text) >= _MIN_TEXT_CHARS:
            return text, 'pdftotext'
        ocr = ocr_pdf(pdf_path, tmp)
        if len(ocr) > len(text):
            return ocr, 'ocr'
        return text, ('pdftotext' if text else 'none')


def text_path(year, number):
    return os.path.join(TEXT_DIR, str(year), f"{number}.txt")


# ── Per-order enrichment ──────────────────────────────────────────────────────

def enrich_order(order, year):
    """Enrich one order in place. Returns True if the JSON entry was modified.

    Text files are written as a side effect and tracked separately from the
    JSON, so this can return False (JSON unchanged) while still having created
    a new text file.
    """
    number = order.get('number')
    url = order.get('url')
    if not url or not number:
        return False

    tpath = text_path(year, number)
    needs_hash = 'sha256' not in order
    needs_text = not os.path.exists(tpath)
    # Archival is gated on its own key, independent of the hash. In the default
    # mode a recorded attempt (key present, url-or-null) is left alone so daily
    # runs don't re-hammer archive.org; the 'retry' sweep re-attempts orders
    # whose recorded archiveUrl is still null.
    if not _ARCHIVE_ENABLED:
        needs_arch = False
    elif _ARCHIVE_RETRY_NULLS:
        needs_arch = order.get('archiveUrl') is None
    else:
        needs_arch = 'archiveUrl' not in order
    if not (needs_hash or needs_text or needs_arch):
        return False  # already enriched — idempotent skip

    changed = False

    # Only the hash and text steps need the PDF bytes; archival needs just the URL.
    if needs_hash or needs_text:
        pdf = download_pdf(url)
        if pdf is None:
            print(f"    {number}: PDF download failed — skipping")
        else:
            if needs_hash:
                order['sha256'] = hashlib.sha256(pdf).hexdigest()
                order['bytes'] = len(pdf)
                order['fetchedAt'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
                changed = True
            if needs_text:
                _write_text(pdf, tpath, number)

    if needs_arch:
        # May be null when no snapshot exists and save-now fails; recording the
        # key stops daily runs from retrying. The 'retry' archive sweep
        # (EO_ENRICH_ARCHIVE=retry) re-attempts these nulls later.
        order['archiveUrl'] = wayback_archive(url)
        changed = True

    return changed


def _write_text(pdf, tpath, number):
    """Extract full text and write it to tpath. Side-effect only."""
    text, method = extract_text(pdf)
    if text:
        os.makedirs(os.path.dirname(tpath), exist_ok=True)
        with open(tpath, 'w', encoding='utf-8') as f:
            f.write(text + '\n')
        print(f"    {number}: text via {method} ({len(text)} chars)")
    else:
        print(f"    {number}: no text extracted "
              "(poppler/tesseract missing or image-only PDF)")


# ── Per-year driver ───────────────────────────────────────────────────────────

def enrich_year(year):
    """Enrich every order for one year. Returns True if the JSON file changed."""
    path = os.path.join(OUTPUT_DIR, f"ga-executive-orders-{year}.json")
    if not os.path.exists(path):
        print(f"  {year}: no data file — skipping")
        return False

    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    orders = data.get('orders', [])
    print(f"Enriching {len(orders)} order(s) for {year}...")

    changed = 0
    for order in orders:
        try:
            if enrich_order(order, year):
                changed += 1
        except Exception as exc:  # noqa: BLE001 - one bad order must not abort the year
            print(f"    {order.get('number')}: enrichment error (non-fatal): {exc}")

    if changed:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"  Wrote {changed} enriched order(s) -> {path}")
    else:
        print(f"  No JSON changes for {year}")
    return changed > 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    years = parse_years(argv)
    any_change = False
    for year in years:
        if enrich_year(year):
            any_change = True
    print("Enrichment complete." + ("" if any_change else " No JSON changes."))


if __name__ == '__main__':
    main()
