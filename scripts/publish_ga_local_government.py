#!/usr/bin/env python3
"""Publish the Georgia local-government topic dataset to Votega/ga-local-government.

What VoteGA turns the raw scrape into and publishes here: a cross-jurisdiction,
sourced, keyword-classified feed of what Georgia county and city governments are
discussing on their published agendas and minutes — ALPR/surveillance, data
centers, and land use — plus the jurisdiction registry and per-place coverage.

Inputs (already committed by the update-local-government workflow):
  _data/places.yml                      the jurisdiction registry
  assets/data/local-topics-<topic>.json the per-topic mention feeds
                                         (built by generate_topic_mentions.py)

Artifacts published:
  latest.json                    index + coverage + last scan (start here)
  data/places.json               jurisdiction registry (public fields only)
  data/mentions.json             every topic mention, one array
  data/mentions.csv              flat, spreadsheet-friendly
  data/mentions.schema.json      JSON Schema for a mention object
  data/mentions-<topic>.json     per-topic mentions
  data/coverage.json             per-place: topic counts + last activity
  SUMMARY.md                     human overview + the standing caveats

EXCERPT POLICY (deliberate): a per-mention quoted excerpt is published ONLY when the
mention's `context` is "agenda-action" — i.e. the topic surfaced as government
business (an item, motion, resolution, or a formal public hearing), from ANY source.
Excerpts whose context is "public-comment" or "unknown" are WITHHELD: public-comment
hits are frequently sign-up rosters that name residents, and bulk-redistributing
resident names + their stated positions is a bigger step than an on-site citation.
Withheld mentions still ship with tags, matched terms, vendors, confidence, context,
and source URL — everything but the quote. (Context is classified by
meeting_topics.classify_context from the agenda's own section headers.)

Dry run (no GA_LOCAL_GOVERNMENT_TOKEN): writes artifacts to $OUT_DIR (default
./out) instead of pushing. See lib/sibling_publish.
"""
import csv
import io
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

import yaml

sys.path.insert(0, os.path.dirname(__file__))
from lib.sibling_publish import build_json, publish_or_dry_run  # noqa: E402

REPO = "Votega/ga-local-government"
TOKEN_ENV = "GA_LOCAL_GOVERNMENT_TOKEN"
SCHEMA_VERSION = "1.0.0"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLACES_YML = os.path.join(ROOT, "_data", "places.yml")
DATA_DIR = os.path.join(ROOT, "assets", "data")

TOPICS = ["alpr", "data-center", "land-use"]
TOPIC_LABEL = {"alpr": "ALPR / surveillance", "data-center": "Data centers",
               "land-use": "Land use"}

# Excerpts are published only for this context (see module docstring).
EXCERPT_CONTEXT = "agenda-action"

# places.yml fields that are safe + useful to republish as a directory. Internal
# scraper scoping (body_map, subdomain, client, agenda_module_id, …) is dropped.
LINK_FIELDS = ["base_url", "agendas_url", "minutes_url", "video_url"]


def load_places():
    with open(PLACES_YML, encoding="utf-8") as fh:
        return (yaml.safe_load(fh) or {}).get("places", [])


def registry(places):
    """Public directory of the jurisdictions we cover, from places.yml."""
    out = []
    for p in places:
        if p.get("hidden"):
            continue
        meetings = (p.get("domains") or {}).get("meetings") or {}
        if not meetings and not p.get("domains"):
            continue
        entry = {
            "placeId": p["slug"],
            "name": p.get("name", p["slug"]),
            "type": p.get("type", "county"),
            "county": p.get("parentCounty") or (p["slug"] if p.get("type") == "county" else None),
            "fips": str(p.get("fips") or "") or None,
            "region": p.get("region") or None,
            "platform": meetings.get("platform"),
            "links": {k: meetings[k] for k in LINK_FIELDS if meetings.get(k)},
            "schedule": [
                {"body": s.get("body"), "when": s.get("when") or None,
                 "location": s.get("location") or None}
                for s in (meetings.get("schedule") or []) if s.get("body")
            ],
        }
        out.append(entry)
    out.sort(key=lambda e: e["name"])
    return out


def load_feed(topic):
    path = os.path.join(DATA_DIR, "local-topics-%s.json" % topic)
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def publishable_mention(topic, m):
    """One mention row in the published shape, applying the excerpt policy."""
    quote = m.get("context") == EXCERPT_CONTEXT
    return {
        "topic": topic,
        "placeId": m["placeId"],
        "placeName": m["placeName"],
        "placeType": m["placeType"],
        "fips": m.get("fips") or None,
        "region": m.get("region") or None,
        "date": m.get("date"),
        "body": m.get("body"),
        "confidence": m.get("confidence"),
        "context": m.get("context"),
        "sourceType": m.get("sourceType"),
        "vendors": m.get("vendors") or [],
        "matchedTerms": m.get("terms") or [],
        "tags": m.get("tags") or [],
        "excerpt": m.get("excerpt") if quote else None,
        "excerptTerm": m.get("excerptTerm") if quote else None,
        "sourceUrl": m.get("sourceUrl"),
    }


def mentions_csv(rows):
    cols = ["topic", "placeId", "placeName", "placeType", "fips", "region",
            "date", "body", "confidence", "context", "sourceType", "vendors",
            "matchedTerms", "tags", "excerpt", "sourceUrl"]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for r in rows:
        row = dict(r)
        for list_col in ("vendors", "matchedTerms", "tags"):
            row[list_col] = "; ".join(row.get(list_col) or [])
        w.writerow(row)
    return buf.getvalue().encode()


def mention_schema():
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "$id": "https://github.com/Votega/ga-local-government/blob/main/data/mentions.schema.json",
        "title": "VoteGA local-government topic mention",
        "type": "object",
        "required": ["topic", "placeId", "date", "sourceUrl"],
        "properties": {
            "topic": {"enum": TOPICS},
            "placeId": {"type": "string", "description": "jurisdiction slug (joins data/places.json)"},
            "placeName": {"type": "string"},
            "placeType": {"enum": ["county", "city"]},
            "fips": {"type": ["string", "null"]},
            "region": {"type": ["string", "null"]},
            "date": {"type": ["string", "null"], "description": "meeting date, ISO 8601"},
            "body": {"type": ["string", "null"], "description": "governing body / meeting name"},
            "confidence": {"enum": ["high", "medium"],
                           "description": "high = named vendor or spelled-out capability; medium = keyword only"},
            "context": {"enum": ["agenda-action", "public-comment", "unknown", None],
                        "description": "how the topic surfaced; a quoted excerpt is present only for agenda-action"},
            "sourceType": {"enum": ["legistar", "granicus", "ocr"],
                           "description": "how the meeting text was obtained"},
            "vendors": {"type": "array", "items": {"type": "string"}},
            "matchedTerms": {"type": "array", "items": {"type": "string"}},
            "tags": {"type": "array", "items": {"type": "string"},
                     "description": "granular land-use subtags (rezoning, variance, …)"},
            "excerpt": {"type": ["string", "null"],
                        "description": "quoted context; only for structured (legistar/granicus) sources"},
            "excerptTerm": {"type": ["string", "null"]},
            "sourceUrl": {"type": ["string", "null"], "description": "the agenda/minutes document"},
        },
    }


def coverage(feeds, reg_by_id):
    """Per scanned place: mention count per topic + last activity."""
    scanned = set()
    per = defaultdict(lambda: {"topics": {}, "lastActivity": None})
    for topic in TOPICS:
        feed = feeds[topic]
        for m in feed["mentions"]:
            scanned.add(m["placeId"])
        for p in feed.get("coveredNoMention", []):
            scanned.add(p["placeId"])
        counts = Counter(m["placeId"] for m in feed["mentions"])
        latest = {}
        for m in feed["mentions"]:
            d = m.get("date") or ""
            if d > (latest.get(m["placeId"]) or ""):
                latest[m["placeId"]] = d
        for pid, n in counts.items():
            per[pid]["topics"][topic] = n
            if (latest.get(pid) or "") > (per[pid]["lastActivity"] or ""):
                per[pid]["lastActivity"] = latest[pid]
    rows = []
    for pid in sorted(scanned):
        meta = reg_by_id.get(pid, {})
        rows.append({
            "placeId": pid,
            "name": meta.get("name", pid),
            "type": meta.get("type"),
            "region": meta.get("region"),
            "topics": per[pid]["topics"],
            "lastActivity": per[pid]["lastActivity"],
        })
    return rows, len(scanned)


def summary_md(reg, all_mentions, cov_rows, scanned_n, universe, last_scan):
    by_topic = Counter(m["topic"] for m in all_mentions)
    places_by_topic = {t: len({m["placeId"] for m in all_mentions if m["topic"] == t})
                       for t in TOPICS}
    vendors = Counter(v for m in all_mentions if m["topic"] == "alpr"
                      for v in (m.get("vendors") or []))
    lines = [
        "# Georgia local-government topic dataset",
        "",
        "What Georgia county and city governments are discussing on their published "
        "agendas and minutes — surveillance cameras (ALPR), data centers, and land "
        "use — classified by keyword, with the source document for every mention.",
        "",
        "Published by [VoteGA.org](https://votega.org). Start with `latest.json`.",
        "",
        "## Coverage",
        "",
        "- **%d** jurisdictions scanned, of Georgia's %d counties and ~%d cities."
        % (scanned_n, universe[0], universe[1]),
        "- Last scan: **%s**" % (last_scan or "n/a"),
        "- Only governments with an automated agenda feed are scanned; a place that "
        "is absent is **not covered yet**, which is different from *no mentions found*.",
        "",
        "## Mentions by topic",
        "",
        "| Topic | Mentions | Jurisdictions |",
        "| --- | --- | --- |",
    ]
    for t in TOPICS:
        lines.append("| %s | %d | %d |" % (TOPIC_LABEL[t], by_topic.get(t, 0),
                                           places_by_topic.get(t, 0)))
    if vendors:
        lines += ["", "## ALPR vendors named", "",
                  "| Vendor | Mentions |", "| --- | --- |"]
        for v, n in vendors.most_common():
            lines.append("| %s | %d |" % (v, n))
    lines += [
        "",
        "## Read this before you use it",
        "",
        "- **A mention marks discussion, not action.** A topic appearing on an agenda "
        "means it *came up* — not that the government approved, funded, or plans to "
        "pursue it. It may have been raised in public comment, mentioned in passing, "
        "tabled, or voted down. Follow the `sourceUrl` for context.",
        "- **A quoted excerpt is included only when `context` is `agenda-action`** — "
        "the topic surfaced as government business (an item, motion, resolution, or a "
        "formal public hearing). Excerpts for `public-comment` and `unknown` context "
        "are withheld: public-comment hits are often sign-up rosters that name "
        "residents. Those mentions still carry tags, matched terms, vendors, "
        "confidence, context, and the source URL — everything but the quote.",
        "- **Confidence.** `high` = a named vendor or a spelled-out capability; "
        "`medium` = a bare keyword. ALPR excerpts are published only for `high`.",
        "- **Accuracy.** Provided as is, no warranty. Spotted an error? Open an issue.",
    ]
    return ("\n".join(lines) + "\n").encode()


def main():
    places = load_places()
    reg = registry(places)
    reg_by_id = {e["placeId"]: e for e in reg}

    feeds = {t: load_feed(t) for t in TOPICS}
    universe = (feeds["alpr"]["metadata"].get("universeCounties", 159),
                feeds["alpr"]["metadata"].get("universeCities", 537))
    last_scan = max((feeds[t]["metadata"].get("generatedAt") or "" for t in TOPICS),
                    default="")[:10]

    per_topic = {t: [publishable_mention(t, m) for m in feeds[t]["mentions"]]
                 for t in TOPICS}
    all_mentions = [m for t in TOPICS for m in per_topic[t]]
    cov_rows, scanned_n = coverage(feeds, reg_by_id)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    latest = {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": now,
        "publisher": "VoteGA.org",
        "description": "Georgia local-government agenda topic mentions "
                       "(ALPR, data centers, land use), the jurisdiction registry, "
                       "and per-place coverage.",
        "lastScan": last_scan,
        "coverage": {"placesScanned": scanned_n,
                     "universeCounties": universe[0], "universeCities": universe[1]},
        "topics": [{"topic": t, "label": TOPIC_LABEL[t],
                    "mentions": len(per_topic[t]),
                    "file": "data/mentions-%s.json" % t} for t in TOPICS],
        "files": {
            "registry": "data/places.json",
            "mentions": "data/mentions.json",
            "mentionsCsv": "data/mentions.csv",
            "schema": "data/mentions.schema.json",
            "coverage": "data/coverage.json",
        },
    }

    meta = {"generatedAt": now, "publisher": "VoteGA.org", "schemaVersion": SCHEMA_VERSION}
    artifacts = {
        "latest.json": build_json(latest),
        "data/places.json": build_json({"metadata": {**meta, "count": len(reg)}, "places": reg}),
        "data/mentions.json": build_json({"metadata": {**meta, "count": len(all_mentions)},
                                          "mentions": all_mentions}),
        "data/mentions.csv": mentions_csv(all_mentions),
        "data/mentions.schema.json": build_json(mention_schema()),
        "data/coverage.json": build_json({"metadata": {**meta, "count": len(cov_rows)},
                                          "places": cov_rows}),
        "SUMMARY.md": summary_md(reg, all_mentions, cov_rows, scanned_n, universe, last_scan),
    }
    for t in TOPICS:
        artifacts["data/mentions-%s.json" % t] = build_json(
            {"metadata": {**meta, "topic": t, "count": len(per_topic[t])},
             "mentions": per_topic[t]})

    publish_or_dry_run(REPO, artifacts, TOKEN_ENV)


if __name__ == "__main__":
    main()
