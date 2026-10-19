#!/usr/bin/env python3
"""Score a topic's keyword lexicon against the offline meeting-text corpus.

A DIAGNOSTIC, not part of the build. Nothing is written; no network is used.

WHY. lib/meeting_topics.py classifies by keyword, so every term added to widen
recall is a chance to badge an unrelated agenda, and every term already there may
be earning nothing. Until now neither could be checked: the enrichers discard the
text they classify, so the only measurable corpus was three hand-picked PDFs behind
a live fetch (scripts/probe_alpr_keywords.py). lib/text_cache.py keeps that text on
disk outside git, and this script turns it into the measurement:

    1. populate once   python scripts/enrich_ocr_meetings.py --reclassify \
                              --text-cache .cache/meeting-text
    2. score freely    python scripts/score_topic_lexicon.py --topic alpr

THE IMPORTANT OUTPUT IS THE DIFF. Each corpus row is classified with the lexicon as
it stands NOW and compared against the tags the committed sidecar recorded when the
document was last enriched. So after editing lib/meeting_topics.py you see exactly
which documents change verdict, with the evidence that moved them:

    WOULD NEWLY MATCH   a lexicon change flags these — read the quotes, this is
                        where false positives show up before they reach the site
    WOULD STOP MATCHING a removed/narrowed term drops these — read them, this is
                        where recall is silently lost

With an unedited lexicon both lists are empty and the run is a pure health report:
per-term hit counts (a term with 0 hits is carrying no weight), vendor spread, and
corpus coverage.

THIS SCRIPT OWNS NO KEYWORDS. It imports classify()/matched_terms() from
lib/meeting_topics.py and nothing else — the one taxonomy. A private candidate list
here would be the exact duplication that made the old probe report numbers for a
matcher that did not ship.

USAGE
    python scripts/score_topic_lexicon.py                       # alpr, default cache
    python scripts/score_topic_lexicon.py --topic data-center
    python scripts/score_topic_lexicon.py --cache DIR --slug cobb
    python scripts/score_topic_lexicon.py --show 40             # more quotes
    python scripts/score_topic_lexicon.py --terms-only          # just the hit table
"""

import argparse
import glob
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.meeting_topics import (  # noqa: E402
    ALPR_TERMS, ALPR_VENDOR_LABELS, TOPIC_RULES, TOPIC_WORD_RULES,
    agenda_head, alpr_vendors, classify, matched_terms, topic_excerpts,
)
from lib.text_cache import open_cache  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, 'assets', 'data')
DEFAULT_CACHE = os.path.join(ROOT, '.cache', 'meeting-text')


def topic_terms(topic):
    """Every keyword that counts as evidence for `topic` — substring + whole-word."""
    return set(TOPIC_RULES.get(topic, [])) | set(TOPIC_WORD_RULES.get(topic, []))


def sidecar_tags():
    """{'<slug>/<meeting id>': [tags]} from every committed enriched sidecar.

    The baseline the corpus is diffed against: what the site currently says about
    each document. Keys mirror TextCache.key() — the OCR/Granicus enrichers record a
    meeting under 'id', the Legistar one under 'eventId'.
    """
    out = {}
    for path in sorted(glob.glob(os.path.join(DATA_DIR,
                                              'local-*-meetings-enriched.json'))):
        base = os.path.basename(path)
        slug = base[len('local-'):-len('-meetings-enriched.json')]
        try:
            with open(path, encoding='utf-8') as fh:
                doc = json.load(fh)
        except (OSError, ValueError):
            continue
        for m in doc.get('meetings') or []:
            mid = m.get('id', m.get('eventId'))
            if mid is None:
                continue
            out['%s/%s' % (slug, mid)] = m.get('tags') or sorted(m.get('topics') or {})
    return out


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--topic', default='alpr',
                    help='taxonomy tag to score (default: alpr)')
    ap.add_argument('--cache', default=DEFAULT_CACHE,
                    help='text-cache root (default: .cache/meeting-text)')
    ap.add_argument('--slug', help='score one place only')
    ap.add_argument('--show', type=int, default=15,
                    help='quotes to print per verdict-change list (default 15)')
    ap.add_argument('--terms-only', action='store_true',
                    help='print only the per-term hit table')
    args = ap.parse_args()

    if args.topic not in TOPIC_RULES and args.topic not in TOPIC_WORD_RULES:
        ap.error('unknown topic %r — known: %s'
                 % (args.topic, ', '.join(sorted(set(TOPIC_RULES) | set(TOPIC_WORD_RULES)))))

    cache = open_cache(args.cache)
    stats = cache.stats(args.slug)
    if not stats['entries']:
        print('No corpus at %s.\n' % args.cache)
        print('Populate it with one networked pass, then re-run this offline:\n'
              '  python scripts/enrich_ocr_meetings.py --reclassify --text-cache %s\n'
              '  python scripts/enrich_granicus_meetings.py --reclassify --text-cache %s\n'
              '  python scripts/enrich_legistar_meetings.py --text-cache %s'
              % (args.cache, args.cache, args.cache))
        return 1

    terms = topic_terms(args.topic)
    baseline = sidecar_tags()

    term_hits = Counter()      # keyword -> docs containing it
    vendor_hits = Counter()
    matched, newly, stopped, unknown = [], [], [], 0

    for key, ent, text in cache.documents(args.slug):
        # Reproduce production exactly: a combined agenda packet is classified on its
        # head only, and the manifest recorded whether this document is one.
        if ent.get('trimmed'):
            text = agenda_head(text)

        tags = classify(text)
        hit = args.topic in tags
        evidence = sorted(set(matched_terms(text)) & terms) if hit else []
        for t in evidence:
            term_hits[t] += 1
        if hit and args.topic == 'alpr':
            for v in alpr_vendors(evidence):
                vendor_hits[v] += 1

        was = baseline.get(key)
        if was is None:
            unknown += 1           # cached but not in any committed sidecar
        row = (key, ent, evidence, text)
        if hit:
            matched.append(row)
            if was is not None and args.topic not in was:
                newly.append(row)
        elif was is not None and args.topic in was:
            stopped.append(row)

    # ── report ────────────────────────────────────────────────────────────────
    print('=== CORPUS ===')
    print('  %d documents (%d readable, %d missing) across %d place(s)%s'
          % (stats['entries'], stats['readable'], stats['missing'], stats['places'],
             ' [slug=%s]' % args.slug if args.slug else ''))
    if unknown:
        print('  %d cached document(s) have no committed sidecar row — not diffed'
              % unknown)

    print('\n=== TERM HITS (topic %r: %d keywords) ===' % (args.topic, len(terms)))
    for t in sorted(terms):
        n = term_hits.get(t, 0)
        label = ALPR_VENDOR_LABELS.get(t) if args.topic == 'alpr' else None
        print('  %5d  %-34s%s' % (n, t, '  [%s]' % label if label else ''))
    dead = sorted(t for t in terms if not term_hits.get(t))
    print('  -- %d of %d keywords fired; %d carried no document'
          % (len(terms) - len(dead), len(terms), len(dead)))
    if args.terms_only:
        return 0

    if vendor_hits:
        print('\n=== VENDORS NAMED ===')
        for v, n in vendor_hits.most_common():
            print('  %5d  %s' % (n, v))

    print('\n=== MATCHES ===')
    print('  %d of %d readable document(s) match %r (%d place(s))'
          % (len(matched), stats['readable'], args.topic,
             len({k.split('/', 1)[0] for k, _, _, _ in matched})))

    def quote(row):
        key, ent, evidence, text = row
        ex = topic_excerpts(text, [args.topic]).get(args.topic) or {}
        print('  %-22s %-10s %s' % (key, ent.get('date') or '-',
                                    (ent.get('body') or ent.get('title') or '')[:46]))
        print('      terms: %s' % (', '.join(evidence) or '-'))
        if ex.get('excerpt'):
            print('      [%s] %s' % (ex.get('context') or '?', ex['excerpt'][:240]))
        print('      %s' % (ent.get('textSourceUrl') or '-'))

    # The two lists that matter after a lexicon edit.
    print('\n=== WOULD NEWLY MATCH (%d) ===' % len(newly))
    if newly:
        print('  Documents the current lexicon flags that the committed sidecar does '
              'not.\n  Read the quotes: a false positive shows up here first.')
        for row in newly[:args.show]:
            quote(row)
        if len(newly) > args.show:
            print('  … %d more (--show %d)' % (len(newly) - args.show, len(newly)))
    else:
        print('  none — the lexicon agrees with every committed sidecar row')

    print('\n=== WOULD STOP MATCHING (%d) ===' % len(stopped))
    if stopped:
        print('  The sidecar flags these; the current lexicon does not. A narrowed or '
              'removed\n  term silently loses recall here.')
        for row in stopped[:args.show]:
            quote(row)
        if len(stopped) > args.show:
            print('  … %d more (--show %d)' % (len(stopped) - args.show, len(stopped)))
    else:
        print('  none — the lexicon still catches every document the sidecar flags')

    print('\n=== SUMMARY ===')
    print('  topic           %s' % args.topic)
    print('  corpus          %d readable of %d' % (stats['readable'], stats['entries']))
    print('  matches         %d' % len(matched))
    print('  newly matching  %d   (inspect for false positives)' % len(newly))
    print('  stopped         %d   (inspect for lost recall)' % len(stopped))
    print('  dead keywords   %d   %s' % (len(dead), ', '.join(dead[:12])
                                         + (' …' if len(dead) > 12 else '')))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
