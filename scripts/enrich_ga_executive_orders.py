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
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from urllib.parse import quote

from lib.http import fetch_bytes, fetch_json
from fetch_ga_executive_orders import OUTPUT_DIR, parse_years

TEXT_DIR = os.path.join(OUTPUT_DIR, "eo-text")

# Below this many characters, assume pdftotext found no real text layer and
# fall back to OCR.
_MIN_TEXT_CHARS = 200

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


def wayback_archive(url):
    """Existing snapshot if any; otherwise ask Wayback to save one, then re-check.

    Returns a snapshot URL or None. Fully best-effort — any failure yields None.
    """
    try:
        existing = _wayback_snapshot(url)
        if existing:
            return existing
        # Trigger a capture (can be slow); the response is ignored.
        fetch_bytes("https://web.archive.org/save/" + url,
                    headers=_PDF_HEADERS, retries=1, backoff=2, timeout=90,
                    label="wayback-save", verbose=False)
        return _wayback_snapshot(url)
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
    if not needs_hash and not needs_text:
        return False  # already enriched — idempotent skip

    pdf = download_pdf(url)
    if pdf is None:
        print(f"    {number}: PDF download failed — skipping")
        return False

    changed = False
    if needs_hash:
        order['sha256'] = hashlib.sha256(pdf).hexdigest()
        order['bytes'] = len(pdf)
        order['fetchedAt'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        # Attempt archival once, during the first enrichment pass, so we don't
        # hammer Wayback on every subsequent daily run. May be null.
        order['archiveUrl'] = wayback_archive(url)
        changed = True

    if needs_text:
        text, method = extract_text(pdf)
        if text:
            os.makedirs(os.path.dirname(tpath), exist_ok=True)
            with open(tpath, 'w', encoding='utf-8') as f:
                f.write(text + '\n')
            print(f"    {number}: text via {method} ({len(text)} chars)")
        else:
            print(f"    {number}: no text extracted "
                  "(poppler/tesseract missing or image-only PDF)")

    return changed


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
