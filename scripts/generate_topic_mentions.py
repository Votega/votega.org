#!/usr/bin/env python3
"""
generate_topic_mentions.py — build the per-topic mention feeds that back the
/local/topics/<topic>/ index pages, from the committed local-government
enrichment sidecars.

This is the reconciled successor to the handoff `topic_scan.py`. Two things
changed in reconciliation, both to fit VoteGA's existing pipeline:

  1. ONE taxonomy. The handoff scanner carried its own TOPICS/VENDORS keyword
     dicts. Those are dropped — the keyword lexicon, the vendor lexicon and the
     land-use rollup all come from scripts/lib/meeting_topics.py, the single
     source both meeting enrichers already use. A new ALPR keyword added there
     flows to the badges, the place pages AND these topic feeds in one edit.

  2. Real input, not a synthetic JSONL. The handoff assumed a docs.jsonl of
     extracted page text. VoteGA has no such feed; the enrichers classify each
     meeting at fetch time and commit the result to
     assets/data/local-<slug>-meetings-enriched.json. We read those. The
     tradeoff is honest and documented: the sidecars retain each flagged
     meeting's date / body / source / matched terms, but NOT the raw page text,
     so the handoff's per-hit EXCERPT and #page=N deep link are not
     reconstructable here. Adding them later means persisting an excerpt in the
     enricher (which already holds the text), not re-fetching every PDF here.

Output: one file per topic, assets/data/local-topics-<slug>.json, shape

    {
      "metadata": { generatedAt, topic, label, emoji, placesScanned,
                    placesWithMentions, vendors[], universeCounties,
                    universeCities },
      "mentions": [ { placeId, placeName, placeType, fips, region, date, body,
                      docType, sourceUrl, confidence, vendors[], terms[],
                      tags[] }, ... ],           # newest first
      "coveredNoMention": [ { placeId, placeName, placeType, region }, ... ]
    }

`coveredNoMention` is what lets the page tell "we scanned here and found
nothing" from "we never looked" — a place is in exactly one of `mentions` /
`coveredNoMention` iff it has an enrichment sidecar (i.e. a scraper adapter).

Deterministic (sorted mentions, sort_keys) so reruns give clean git diffs.

USAGE:
    python scripts/generate_topic_mentions.py            # scan + write all topics
    python scripts/generate_topic_mentions.py --out assets/data --data assets/data
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime, timezone

# Import path so `scripts/lib/...` resolves whether run from repo root or scripts/.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.meeting_topics import (  # noqa: E402
    TOPIC_RULES,
    LAND_USE,
    ALPR_TERMS,
    ALPR_HIGH_TERMS,
    alpr_vendors,
)

try:
    import yaml
except ImportError:  # pragma: no cover
    print("PyYAML is required (pip install pyyaml)", file=sys.stderr)
    raise

# Georgia's full local-government universe, for the coverage footer's
# denominator (CLAUDE.md / handoff). Counties are fixed; the city count is the
# commonly cited "~537 active municipalities".
UNIVERSE_COUNTIES = 159
UNIVERSE_CITIES = 537

# Land-use subjects shown on the land-use page. Data centers are a land-use
# subject too, but they get their own page (mirrors build_summary's split), so
# the land-use page excludes them and the pages stay non-redundant.
LU_TAGS = LAND_USE - {"data-center"}

# The page topics and how each maps onto an enriched meeting's `topics`/`tags`.
# label/emoji here are the generator's fallback; _data/topics.yml is the display
# source of truth for the pages.
TOPICS = {
    "alpr":        {"label": "ALPR / surveillance",     "emoji": "📷"},
    "data-center": {"label": "Data centers",            "emoji": "🏭"},
    "land-use":    {"label": "Land use",                "emoji": "🏗️"},
}

ENRICHED_GLOB = "local-*-meetings-enriched.json"
ENRICHED_RE = re.compile(r"local-(.+)-meetings-enriched\.json$")


def load_places(places_path: str) -> dict:
    """slug -> {name, type, fips, region} from _data/places.yml."""
    with open(places_path, encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    out = {}
    for p in doc.get("places", []):
        out[p["slug"]] = {
            "name": p.get("name", p["slug"]),
            "type": p.get("type", "county"),
            "fips": str(p.get("fips") or ""),
            "region": p.get("region") or "",
        }
    return out


def topic_hit(topic: str, meeting: dict):
    """If `meeting` mentions `topic`, return a mention dict (minus place fields);
    else None. Reads only fields the enrichers already persist."""
    topics = meeting.get("topics") or {}
    matched = set(meeting.get("matchedTerms") or [])
    excerpts = meeting.get("topicExcerpts") or {}

    # excerpt/term for this page-topic, from the sidecar (text-layer meetings only).
    ex = None
    if topic == "alpr":
        if "alpr" not in topics:
            return None
        terms = sorted(matched & ALPR_TERMS)
        vendors = alpr_vendors(terms)
        confidence = "high" if (vendors or (matched & ALPR_HIGH_TERMS)) else "medium"
        tags = []
        # Phase A: quote ALPR only for high-confidence mentions (vendor-named /
        # spelled-out). A bare keyword-only hit shows terms + source, no quote.
        if confidence == "high":
            ex = excerpts.get("alpr")
    elif topic == "data-center":
        if "data-center" not in topics:
            return None
        terms = sorted(matched & set(TOPIC_RULES["data-center"]))
        vendors = []
        confidence = "high"
        tags = []
        ex = excerpts.get("data-center")
    elif topic == "land-use":
        present = sorted(set(topics) & LU_TAGS)
        if not present:
            return None
        lu_keywords = {k for t in present for k in TOPIC_RULES.get(t, [])}
        terms = sorted(matched & lu_keywords)
        vendors = []
        confidence = "high"
        tags = present
        ex = next((excerpts[t] for t in present if t in excerpts), None)
    else:
        return None

    # Source type, from how the meeting was enriched — Legistar records carry no
    # textMethod, Granicus is 'html', the OCR enricher is pdftotext/ocr/none. Lets
    # a consumer (e.g. the sibling-repo publisher) treat a structured agenda-item
    # excerpt differently from an OCR public-comment-roster one.
    tm = meeting.get("textMethod")
    if tm is None:
        source_type = "legistar"
    elif tm == "html":
        source_type = "granicus"
    else:
        source_type = "ocr"

    return {
        "excerpt": (ex or {}).get("excerpt"),
        "excerptTerm": (ex or {}).get("term"),
        "context": (ex or {}).get("context"),
        "date": meeting.get("date"),
        "body": meeting.get("body") or meeting.get("title") or "",
        "docType": meeting.get("textSource") or meeting.get("doc_type") or "agenda",
        "sourceType": source_type,
        "sourceUrl": meeting.get("sourceUrl") or meeting.get("textSourceUrl"),
        "confidence": confidence,
        "vendors": vendors,
        "terms": terms,
        "tags": tags,
    }


def build_topic(topic: str, enriched_files: list[str], places: dict) -> dict:
    mentions = []
    scanned = []            # (placeId, placeName, placeType, region)
    with_mentions = set()
    vendors_seen = set()

    for path in enriched_files:
        m = ENRICHED_RE.search(os.path.basename(path))
        if not m:
            continue
        slug = m.group(1)
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError):
            continue

        meta = places.get(slug, {})
        place_name = meta.get("name") or doc.get("metadata", {}).get("place") or slug
        place_type = meta.get("type", "county")
        fips = meta.get("fips", "")
        region = meta.get("region", "")
        scanned.append((slug, place_name, place_type, region))

        for meeting in doc.get("meetings") or []:
            hit = topic_hit(topic, meeting)
            if not hit:
                continue
            with_mentions.add(slug)
            vendors_seen.update(hit["vendors"])
            mentions.append({
                "placeId": slug,
                "placeName": place_name,
                "placeType": place_type,
                "fips": fips,
                "region": region,
                **hit,
            })

    # Newest first, stable tiebreak by place then body for clean diffs.
    mentions.sort(key=lambda r: (r["date"] or "", r["placeId"], r["body"]), reverse=True)

    covered_no_mention = sorted(
        ({"placeId": s, "placeName": n, "placeType": t, "region": r}
         for (s, n, t, r) in scanned if s not in with_mentions),
        key=lambda x: x["placeName"],
    )

    cfg = TOPICS[topic]
    return {
        "metadata": {
            "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "topic": topic,
            "label": cfg["label"],
            "emoji": cfg["emoji"],
            "placesScanned": len({s for (s, *_ ) in scanned}),
            "placesWithMentions": len(with_mentions),
            "vendors": sorted(vendors_seen),
            "universeCounties": UNIVERSE_COUNTIES,
            "universeCities": UNIVERSE_CITIES,
        },
        "mentions": mentions,
        "coveredNoMention": covered_no_mention,
    }


def write_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, sort_keys=True, ensure_ascii=False)
        fh.write("\n")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default="assets/data",
                    help="dir holding local-*-meetings-enriched.json (input)")
    ap.add_argument("--places", default="_data/places.yml")
    ap.add_argument("--out", default="assets/data",
                    help="dir for local-topics-<slug>.json (output)")
    args = ap.parse_args()

    places = load_places(args.places)
    enriched = sorted(glob.glob(os.path.join(args.data, ENRICHED_GLOB)))
    if not enriched:
        print(f"no enriched sidecars found in {args.data} — nothing to do",
              file=sys.stderr)
        return 1

    for topic in TOPICS:
        result = build_topic(topic, enriched, places)
        out_path = os.path.join(args.out, f"local-topics-{topic}.json")
        write_json(out_path, result)
        md = result["metadata"]
        print(f"{topic:12s} {len(result['mentions']):4d} mentions across "
              f"{md['placesWithMentions']}/{md['placesScanned']} scanned places"
              f"  vendors={len(md['vendors'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
