#!/usr/bin/env python3
"""Content-addressed cache of extracted meeting text — the offline corpus.

WHY THIS EXISTS. The enrichers classify each agenda/minutes document at fetch time
and commit only DERIVED data (tags, matched terms, the PDF's sha256); the raw text
is discarded on purpose, because agenda packets are large and churn, and a
committed copy would bloat git and risk republishing OCR garble (see the git-bloat
note in enrich_ocr_meetings.py). That discipline is right for the REPO and wrong
for ITERATION: it means a keyword added to lib/meeting_topics.py cannot be measured
against the documents we have already read. The only way to score a candidate
lexicon was to re-download every PDF, which costs ~800 fetches and still gives no
before/after comparison.

This module keeps that text OUT of git but ON disk, so the loop becomes:

    populate once (one networked CI pass)  ->  score/re-tag any number of times, free

Two capabilities follow from it, and the second is the expensive one:

  1. SCORING. scripts/score_topic_lexicon.py runs the shipped lexicon over the whole
     corpus and reports which terms earn their place, what a change would newly
     match, and what it would stop matching — measurement instead of judgment.
  2. RE-TAGGING WITHOUT NETWORK. `--reclassify` exists so a taxonomy change re-tags
     already-cached meetings, and its docstring notes the cost: "the text is not
     stored, so re-classifying requires re-downloading the PDF". With a populated
     cache, `--reclassify --from-text-cache` re-tags the full history from local
     text and fetches nothing.

NEVER COMMITTED. The cache root is gitignored. Nothing here is a source of truth:
it is a derived, reproducible artifact of documents that remain public at their
source URL, and it can be deleted and rebuilt at any time.

LAYOUT

    <root>/manifest.json              (slug, meeting id) -> entry, see `record()`
    <root>/text/<ab>/<sha256>.txt.gz  gzipped UTF-8 extracted text

Text is keyed by the sha256 OF THE TEXT, not of the PDF. That is uniform across all
three enrichers — the Legistar enricher assembles its blob from API fields and has
no PDF at all — it is self-verifying (the key can always be recomputed from the
contents), and it de-duplicates automatically, which matters more than it sounds:
agenda packets are re-published across meetings and the same document is often
reachable from several places. The upstream `pdfSha256` is still recorded in the
manifest entry, so a caller can tell that the SOURCE pdf changed since caching even
when the extracted text is byte-identical.

Gzip members are written with mtime=0 so the same text always produces the same
bytes — a rebuilt cache compares equal instead of churning.
"""

import gzip
import hashlib
import json
import os

from lib.atomic_io import atomic_write, write_json_atomic

MANIFEST = 'manifest.json'
_TEXT_DIR = 'text'


def text_sha(text):
    """The cache key for `text`: sha256 of its UTF-8 encoding."""
    return hashlib.sha256((text or '').encode('utf-8')).hexdigest()


class TextCache:
    """Read/write access to one cache root.

    `writable=False` (the default) is a pure reader: it never creates the root and
    never writes, so a scorer or a `--from-text-cache` run cannot accidentally
    half-populate a cache it was only meant to read. Call `flush()` after a writing
    run to persist the manifest — text blobs are written as they arrive, but the
    manifest is held in memory so one run costs one manifest write, not 800.
    """

    def __init__(self, root, writable=False):
        self.root = root
        self.writable = writable
        self._manifest = {}
        self._dirty = False
        path = os.path.join(root, MANIFEST)
        if os.path.exists(path):
            try:
                with open(path, encoding='utf-8') as fh:
                    doc = json.load(fh)
                self._manifest = doc.get('entries') or {}
            except (OSError, ValueError):
                # A truncated manifest must not take a run down: the text blobs are
                # still on disk and re-recording rebuilds the index.
                self._manifest = {}

    # ── keys ──────────────────────────────────────────────────────────────────
    @staticmethod
    def key(slug, meeting_id):
        """Manifest key for one meeting. str() because Legistar ids are ints and
        JSON round-trips every mapping key as a string — without this, a lookup
        after a save would miss every Legistar meeting."""
        return '%s/%s' % (slug, meeting_id)

    def _blob_path(self, sha):
        # Two-character fan-out: ~800 files today, but a flat directory of tens of
        # thousands is slow to list on some filesystems and awkward to inspect.
        return os.path.join(self.root, _TEXT_DIR, sha[:2], '%s.txt.gz' % sha)

    # ── read ──────────────────────────────────────────────────────────────────
    def get_text(self, sha):
        """The cached text for `sha`, or None if it is not on disk."""
        path = self._blob_path(sha)
        if not os.path.exists(path):
            return None
        try:
            with gzip.open(path, 'rt', encoding='utf-8') as fh:
                return fh.read()
        except (OSError, ValueError, EOFError):
            return None  # corrupt member — treat as a miss, re-fetch repopulates

    def entry(self, slug, meeting_id):
        """The manifest entry for one meeting, or None."""
        return self._manifest.get(self.key(slug, meeting_id))

    def text_for(self, slug, meeting_id):
        """Cached text for one meeting, or None on any miss (no entry, or the blob
        the entry points at is gone)."""
        ent = self.entry(slug, meeting_id)
        if not ent:
            return None
        return self.get_text(ent.get('textSha') or '')

    def entries(self, slug=None):
        """(key, entry) for every manifest row, optionally one place only. Sorted so
        a scorer's report and its exit status are reproducible."""
        for k in sorted(self._manifest):
            if slug and not k.startswith('%s/' % slug):
                continue
            yield k, self._manifest[k]

    def documents(self, slug=None):
        """(key, entry, text) for every row whose text is readable.

        Rows whose blob is missing or corrupt are SKIPPED, not yielded with empty
        text — a scorer must never score a document it could not read and count the
        silence as a clean negative. `stats()` reports the gap instead.
        """
        for key, ent in self.entries(slug):
            text = self.get_text(ent.get('textSha') or '')
            if text is None:
                continue
            yield key, ent, text

    def stats(self, slug=None):
        """Coverage counters, so a caller can say how complete the corpus is."""
        rows = list(self.entries(slug))
        readable = sum(1 for _, e in rows if self.get_text(e.get('textSha') or '')
                       is not None)
        return {
            'entries': len(rows),
            'readable': readable,
            'missing': len(rows) - readable,
            'places': len({k.split('/', 1)[0] for k, _ in rows}),
        }

    # ── write ─────────────────────────────────────────────────────────────────
    def record(self, slug, meeting_id, text, method=None, pdf_sha=None,
               source_url=None, date=None, body=None, title=None, trimmed=False):
        """Store `text` and index it under (slug, meeting_id). Returns its sha.

        No-op on a reader (`writable=False`) beyond returning the sha, so callers can
        stay branch-free. An identical blob already on disk is not rewritten — the
        key IS the content, so a second write would produce the same bytes.
        """
        sha = text_sha(text)
        if not self.writable:
            return sha
        path = self._blob_path(sha)
        if not os.path.exists(path):
            # atomic_write creates the parent directory itself, so the fan-out dir
            # needs no separate makedirs.
            # mtime=0 for byte-stable output; compresslevel 9 because this is written
            # once and read many times, and agenda text compresses ~10:1.
            with atomic_write(path, mode='wb') as fh:
                with gzip.GzipFile(fileobj=fh, mode='wb', compresslevel=9,
                                   mtime=0) as gz:
                    gz.write((text or '').encode('utf-8'))
        self._manifest[self.key(slug, meeting_id)] = {
            'textSha': sha,
            'chars': len(text or ''),
            'method': method,
            'pdfSha256': pdf_sha,
            'textSourceUrl': source_url,
            'date': date,
            'body': body,
            'title': title,
            # Does production classify only this document's agenda HEAD? Combined
            # agenda packets (meeting_topics.agenda_head) bundle prior meetings'
            # minutes after the agenda, and the enricher trims them off before
            # classifying. The cache stores the RAW extracted text — so the trim
            # policy itself stays revisable — and records here that production
            # trims it, so a scorer reproduces production exactly instead of
            # scoring a full packet the site never classified.
            'trimmed': bool(trimmed),
        }
        self._dirty = True
        return sha

    def flush(self):
        """Persist the manifest if anything changed. Safe to call unconditionally."""
        if not (self.writable and self._dirty):
            return False
        os.makedirs(self.root, exist_ok=True)
        write_json_atomic(os.path.join(self.root, MANIFEST),
                          {'entries': self._manifest}, indent=1)
        self._dirty = False
        return True


def open_cache(root, writable=False):
    """TextCache for `root`, or None when `root` is falsey — lets every caller write
    `cache = open_cache(args.text_cache)` and then guard on None, instead of
    threading an enabled/disabled flag alongside the object."""
    if not root:
        return None
    return TextCache(root, writable=writable)
