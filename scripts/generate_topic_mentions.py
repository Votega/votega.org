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
      "metadata": { generatedAt, topic, label, emoji, placesScanned, mentionsWithOutcomes,
                    countiesScanned, citiesScanned, consolidatedScanned,
                    placesWithMentions, vendors[], universeCounties,
                    universeCities, universeConsolidated },
      "mentions": [ { placeId, placeName, placeType, fips, region, date, body,
                      docType, sourceUrl, confidence, vendors[], terms[],
                      tags[], and where the minutes were read: meetingId,
                      followThrough, outcomes[], minutesUrl?, minutesDraft? },
                    ... ],                       # newest first
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
    classify,
    TOPIC_RULES,
    TOPIC_WORD_RULES,
    LAND_USE,
    ALPR_TERMS,
    ALPR_HIGH_TERMS,
    alpr_vendors,
)
from lib.atomic_io import atomic_write  # noqa: E402

# PyYAML is imported where the registry is read (load_places), not here, so the
# offline test job, which installs no packages, can import the pure helpers.

# Georgia's full local-government universe, for the coverage footer's
# denominator (CLAUDE.md / handoff). Counties are fixed; the city count is the
# commonly cited "~537 active municipalities".
#
# Consolidated city-county governments (Macon-Bibb, Columbus-Muscogee,
# Athens-Clarke, …) are their own category: they aren't a standalone county or
# city government, so a place typed "consolidated" is counted here, not under
# counties. The 159/537 figures are left as the recognized geographic and
# municipal universe sizes — the consolidated counties still sit within the 159
# as territory, but their *government* is scanned under the consolidated bucket.
UNIVERSE_COUNTIES = 159
UNIVERSE_CITIES = 537
UNIVERSE_CONSOLIDATED = 9  # Georgia city-county consolidated governments

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
    "local-taxes": {"label": "Local taxes & referenda", "emoji": "🗳️"},
}

ENRICHED_GLOB = "local-*-meetings-enriched.json"
ENRICHED_RE = re.compile(r"local-(.+)-meetings-enriched\.json$")


def load_places(places_path: str) -> dict:
    """slug -> {name, type, fips, region} from _data/places.yml."""
    try:
        import yaml
    except ImportError:  # pragma: no cover
        print("PyYAML is required (pip install pyyaml)", file=sys.stderr)
        raise
    with open(places_path, encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    out = {}
    for p in doc.get("places", []):
        out[p["slug"]] = {
            "name": p.get("name", p["slug"]),
            "type": p.get("type", "county"),
            "fips": str(p["fips"]) if p.get("fips") else None,  # null, never "" (a city has no county FIPS)
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
    elif topic == "local-taxes":
        if "local-taxes" not in topics:
            return None
        tax_keywords = set(TOPIC_RULES["local-taxes"]) | set(TOPIC_WORD_RULES["local-taxes"])
        terms = sorted(matched & tax_keywords)
        vendors = []
        confidence = "high"
        tags = []
        ex = excerpts.get("local-taxes")
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


# ---- follow-through: what the minutes record for a tagged meeting ----------
#
# The follow-through convention in CLAUDE.md. A mention is a meeting whose AGENDA we tagged.
# Where the place has a recorded-votes file (local-<slug>-votes.json: CivicClerk,
# Legistar, IQM2), the same meeting's recorded items are classified with the SAME
# taxonomy, and the items that carry this page's topic are attached with their
# results. The join is exact twice over: the meeting id is the portal's own (the
# votes file and the meetings file are read from the same portal), and the item is
# the portal's own agenda item, so there is no title matching anywhere.
#
# `followThrough` says which case a mention is in, so the page never implies
# more than the record holds:
#   "recorded"        minutes read; items carrying this topic listed in `outcomes`
#   "not-in-minutes"  minutes read, but no recorded item names this topic (it may
#                     have been discussed, or it sits in a packet, not a caption)
#   "no-results"      minutes read, and they record no results at all
#   null              no votes file for this place, or this meeting not read yet
MAX_OUTCOME_NAME = 300


def topic_in_tags(topic: str, tags) -> bool:
    tags = set(tags)
    if topic == "land-use":
        return bool(tags & LU_TAGS)
    return topic in tags


def load_votes(data_dir: str, slug: str) -> dict:
    path = os.path.join(data_dir, "local-%s-votes.json" % slug)
    try:
        with open(path, encoding="utf-8") as fh:
            meetings = json.load(fh).get("meetings") or []
    except (OSError, ValueError):
        return {}
    return {str(m.get("id")): m for m in meetings if m.get("id") is not None}


def _motion_summary(mo: dict) -> dict:
    """The fields a topic row needs, set ones only: these feeds are fetched whole
    by the topic pages, so a null on every motion is paid for by every visitor."""
    out = {
        "resultText": mo.get("resultText") or (mo.get("result") or "").capitalize() or None,
        "result": mo.get("result"),
        "resultClass": mo.get("resultClass"),
        "motion": mo.get("motion"),
        "yes": len(mo.get("yes") or []),
        "no": len(mo.get("no") or []),
        "abstain": len(mo.get("abstain") or []),
        "absent": len(mo.get("absent") or []),
        "tally": mo.get("tally"),
        "next": mo.get("next"),
        "textDisagrees": mo.get("textDisagrees"),
    }
    return {k: v for k, v in out.items() if v}


def follow_through(topic: str, vote_meeting):
    """(status, outcomes, minutes fields) for one mention. See the block comment."""
    if not vote_meeting:
        return None, [], {}
    extra = {"minutesUrl": vote_meeting.get("minutesUrl"),
             "minutesDraft": vote_meeting.get("minutesDraft")}
    items = vote_meeting.get("items") or []
    if not items:
        return "no-results", [], extra
    outcomes = []
    for it in items:
        name = it.get("name") or ""
        if not topic_in_tags(topic, classify(name)):
            continue
        if len(name) > MAX_OUTCOME_NAME:
            name = name[:MAX_OUTCOME_NAME].rsplit(" ", 1)[0] + "…"
        outcomes.append({
            "reference": it.get("reference"),
            "outline": it.get("outline"),
            "name": name or None,
            "motions": [_motion_summary(mo) for mo in it.get("motions") or []],
        })
    return ("recorded" if outcomes else "not-in-minutes"), outcomes, extra


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
        fips = meta.get("fips")
        region = meta.get("region", "")
        scanned.append((slug, place_name, place_type, region))
        votes = load_votes(os.path.dirname(path), slug)

        for meeting in doc.get("meetings") or []:
            hit = topic_hit(topic, meeting)
            if not hit:
                continue
            with_mentions.add(slug)
            vendors_seen.update(hit["vendors"])
            mid = meeting.get("id")
            status, outcomes, minutes = follow_through(
                topic, votes.get(str(mid)) if mid is not None else None)
            mentions.append({
                "placeId": slug,
                "placeName": place_name,
                "placeType": place_type,
                "fips": fips,
                "region": region,
                **hit,
                # present only where the place has a votes record for this meeting
                **({"meetingId": str(mid),
                    "followThrough": status,
                    "outcomes": outcomes,
                    **({"minutesUrl": minutes["minutesUrl"]} if minutes.get("minutesUrl") else {}),
                    **({"minutesDraft": True} if minutes.get("minutesDraft") else {}),
                    } if status else {}),
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
            "countiesScanned": len({s for (s, _, t, _) in scanned if t == "county"}),
            "citiesScanned": len({s for (s, _, t, _) in scanned if t == "city"}),
            "consolidatedScanned":
                len({s for (s, _, t, _) in scanned if t == "consolidated"}),
            "placesWithMentions": len(with_mentions),
            "mentionsWithOutcomes": sum(1 for m in mentions if m.get("followThrough") == "recorded"),
            "vendors": sorted(vendors_seen),
            "universeCounties": UNIVERSE_COUNTIES,
            "universeCities": UNIVERSE_CITIES,
            "universeConsolidated": UNIVERSE_CONSOLIDATED,
        },
        "mentions": mentions,
        "coveredNoMention": covered_no_mention,
    }


def write_json(path: str, data) -> None:
    with atomic_write(path) as fh:
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
