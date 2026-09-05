#!/usr/bin/env python3
"""Aggregate Georgia political news headlines into assets/data/ga-news.json.

Data flow (matches the site's build-time pattern):
    curated RSS feeds -> this script -> assets/data/ga-news.json -> ga-news.html

What this stores and why it is copyright-safe: only a headline, a <=200-char
excerpt from the feed's own summary, the publisher name, and a link out. VoteGA
does not host article text; every card drives traffic to the source.

Sources come from _data/news_sources.yml (the audit surface). Google News RSS is
deliberately excluded -- its licence is "personal, non-commercial use" only.

Entity tagging (the hard part) is deliberately conservative, mirroring the
finance matcher's "show nothing rather than mis-attribute" rule
(scripts/lib/ga_match.py). An item is tagged to a person only when the match is
unambiguous:

  * full name present -> a given-name token (>=2 chars) sits within NAME_WINDOW
                         tokens BEFORE the surname (a real "First [Middle] Last"
                         mention), not merely co-occurring somewhere in the text;
  * bare surname      -> allowed ONLY for federal members and statewide
                         executives (the nationally-covered names where "Warnock"
                         / "Ossoff" / "Kemp" alone is unambiguous), when that
                         surname is theirs alone, is not a common English word,
                         and is >= 4 chars. The 249 state legislators are excluded
                         -- a bare "Mitchell" / "Martin" too often means someone
                         else -- so they require a given name.

The crosswalk mixes name formats ("Brian Kemp" vs "Warnock, Raphael G."); this
reads name.first / name.last when present and only parses `full` as a fallback,
so a federal member's surname is not mistaken for their initial.

Official press-release feeds (a feed with an `entity` key in news_sources.yml)
are the one exception to name-only tagging: every item from an official's own
feed is force-tagged to that person by their crosswalk id, because a release
("Statement on the farm bill") often never names its author. The `entity` value
may be a vgId, a federal member's bioguideId, or a state person's ocdPersonId;
name-matching still runs on top to catch anyone else the item mentions.

Usage:
    python scripts/generate_ga_news.py [output.json] [overrides.json]
"""

import html
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit, urlunsplit
import xml.etree.ElementTree as ET

import yaml

from lib.http import fetch_bytes
from lib.ga_match import toks

HERE           = os.path.dirname(os.path.abspath(__file__))
REPO           = os.path.dirname(HERE)
SOURCES_FILE   = os.path.join(REPO, "_data", "news_sources.yml")
CROSSWALK_FILE = os.path.join(REPO, "assets", "data", "id-crosswalk.json")
ENTITY_URLS_FILE = os.path.join(REPO, "_data", "entity_urls.json")
OUTPUT_FILE    = sys.argv[1] if len(sys.argv) > 1 else os.path.join(REPO, "assets", "data", "ga-news.json")
OVERRIDES_FILE = sys.argv[2] if len(sys.argv) > 2 else os.path.join(REPO, "assets", "data", "ga-news-overrides.json")

WINDOW_DAYS  = 45
SNIPPET_MAX  = 200
PER_FEED_MAX = 120   # guard against a runaway feed

DISCLAIMER = (
    "Headlines and short excerpts are aggregated for civic information and link to "
    "the original publisher. VoteGA does not host article text. Source selection is "
    "a curated, published list (_data/news_sources.yml)."
)

#: Surnames that are also everyday English words. A bare occurrence of one of
#: these never tags on the surname alone -- it must appear right after a given
#: name. Prevents "still blocking", "the Price of...", "White House",
#: "on the other hand" from tagging an officeholder with that surname.
COMMON_WORD_SURNAMES = {
    "white", "brown", "black", "green", "gray", "grey", "young", "long", "short",
    "house", "price", "rice", "cook", "park", "day", "new", "may", "march", "will",
    "best", "moore", "law", "case", "post", "power", "powers", "bush", "stone",
    "hall", "field", "fields", "bell", "rich", "gay", "hope", "love", "king",
    "west", "east", "north", "south", "swift", "camp", "flowers", "wood", "woods",
    "banks", "waters", "still", "hand", "bishop", "box", "sharp", "dean", "burns",
    "mills", "gunn", "means", "starr", "bloom", "batts", "newton", "cameron",
}

#: A given name must sit within this many tokens BEFORE the surname to count as a
#: full-name mention. Covers middle names/initials ("Keisha R. Lance Bottoms")
#: while rejecting a given name and surname that merely co-occur far apart
#: ("...Anthony Fauci..." near an unrelated "Anthony").
NAME_WINDOW = 3

STRIP_TAGS = re.compile(r"<[^>]+>")


# --------------------------------------------------------------------------- #
# Sources
# --------------------------------------------------------------------------- #
def load_sources():
    with open(SOURCES_FILE, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    feeds = cfg.get("feeds") or []
    ga_terms = [t.lower() for t in (cfg.get("ga_terms") or [])]
    topics = {k: re.compile(v, re.IGNORECASE) for k, v in (cfg.get("topics") or {}).items()}
    if not feeds:
        print("Error: no feeds configured in _data/news_sources.yml")
        sys.exit(1)
    return feeds, ga_terms, topics


# --------------------------------------------------------------------------- #
# Entity index (from id-crosswalk.json)
# --------------------------------------------------------------------------- #
def name_parts(person):
    """(surname_key, {given tokens}) for a crosswalk person, or (None, set()).

    Prefers structured name.last / name.first; parses name.full only as a
    fallback, handling the "Last, First" federal convention.
    """
    nm = person.get("name") or {}
    last = (nm.get("last") or "").strip()
    first = (nm.get("first") or "").strip()
    full = (nm.get("full") or "").strip()

    if last:
        sur = toks(last)
        giv = toks(first) if first else [t for t in toks(full) if t not in set(toks(last))]
    elif "," in full:
        l, f = full.split(",", 1)
        sur, giv = toks(l), toks(f)
    else:
        t = toks(full)
        sur, giv = t[-1:], t[:-1]

    if not sur:
        return None, set()
    surname_key = sur[-1]
    if len(surname_key) < 3:
        return None, set()
    givens = {g for g in giv if len(g) >= 2}
    return surname_key, givens


def build_entity_index(people):
    """surname_key -> [ {vgId, name, givens, officeholder} ] for linkable people.

    Only people with a role (current officeholder) or a vgId (a real,
    filing-backed candidate) are indexed; candidate-only rows with vgId null are
    skipped so bare-surname eligibility reflects people the site can link to.
    `sole_bare` marks surnames owned by exactly one indexed person who is a
    federal member or statewide executive -- the only ones eligible for
    bare-surname matching.
    """
    by_surname = {}
    indexed = 0
    for p in people:
        if not (p.get("role") or p.get("vgId")):
            continue
        surname_key, givens = name_parts(p)
        if not surname_key:
            continue
        role = p.get("role") or {}
        # Bare-surname eligibility is limited to nationally-covered figures --
        # federal members and statewide executives -- where a surname alone
        # ("Warnock", "Ossoff", "Kemp") is unambiguous in GA political news. The
        # 249 state legislators are excluded: their surnames (Mitchell, Martin,
        # Harper) are common enough that a bare occurrence often means someone
        # else ("Pat Mitchell", a DNC "Martin"), so they require a given name.
        bare_class = bool(role) and (role.get("level") == "federal"
                                     or role.get("office") == "statewide-executive")
        by_surname.setdefault(surname_key, []).append({
            "vgId": p.get("vgId"),
            "name": (p.get("name") or {}).get("full"),
            "givens": givens,
            "bare_class": bare_class,
        })
        indexed += 1

    sole_bare = set()
    for sk, persons in by_surname.items():
        holders = [p for p in persons if p["bare_class"]]
        if len(holders) == 1 and len(persons) == 1:
            sole_bare.add(sk)
    return by_surname, sole_bare, indexed


def build_id_index(people):
    """Map any stable person id -> vgId, for resolving a feed's `entity` binding.

    Accepts the id forms news_sources.yml is allowed to reference: the vgId
    itself, a federal member's bioguideId, or a state person's ocdPersonId. A
    feed keyed on any of these force-tags every item it yields to that person
    (see resolve_feed_entity), which is how an official's own press releases get
    attributed even when the headline never names them.
    """
    index = {}
    for p in people:
        vg = p.get("vgId")
        if not vg:
            continue
        index[vg] = vg
        ids = p.get("ids") or {}
        for key in ("bioguideId", "ocdPersonId"):
            val = ids.get(key)
            if val:
                index[val] = vg
    return index


def resolve_feed_entity(feed, id_index):
    """The vgId a feed is bound to via its optional `entity` key, or None.

    Prints a warning and returns None on an unknown reference so a stale binding
    degrades to plain name-matching rather than silently tagging nothing.
    """
    ref = feed.get("entity")
    if not ref:
        return None
    vg = id_index.get(ref)
    if not vg:
        print(f"  WARNING: feed '{feed.get('name')}' binds to unknown entity "
              f"'{ref}' -- ignoring (check assets/data/id-crosswalk.json)")
    return vg


def match_entities(text_tokens, by_surname, sole_bare):
    """Return [ {vgId, name} ] unambiguously named in the text.

    A person matches when EITHER
      * one of their given names appears within NAME_WINDOW tokens before their
        surname (a real "First [Middle] Last" mention), OR
      * their surname belongs to a lone federal member / statewide executive, is
        not a common English word, and is >= 4 chars (a bare "Warnock" / "Ossoff"
        / "Raffensperger" surname mention in a headline).
    """
    positions = {}
    for i, t in enumerate(text_tokens):
        positions.setdefault(t, []).append(i)

    hits = {}
    for surname_key, persons in by_surname.items():
        sk_pos = positions.get(surname_key)
        if not sk_pos:
            continue
        bare_ok_surname = (surname_key in sole_bare
                           and surname_key not in COMMON_WORD_SURNAMES
                           and len(surname_key) >= 4)
        for p in persons:
            matched = False
            for g in p["givens"]:
                for gi in positions.get(g, ()):
                    if any(0 < (sj - gi) <= NAME_WINDOW for sj in sk_pos):
                        matched = True
                        break
                if matched:
                    break
            if not matched and bare_ok_surname and p["bare_class"]:
                matched = True
            if matched:
                hits[p["name"]] = p

    return list(hits.values())


# --------------------------------------------------------------------------- #
# Relevance + topics
# --------------------------------------------------------------------------- #
def load_entity_urls():
    """The canonical id -> clean-URL map (_data/entity_urls.json) the site's
    entity pages already use. Returns {} if absent so linking degrades to plain
    text rather than failing the build."""
    if not os.path.exists(ENTITY_URLS_FILE):
        return {}
    with open(ENTITY_URLS_FILE, encoding="utf-8") as f:
        return json.load(f)


def display_name(full):
    """Human-friendly display name. The crosswalk stores federal members as
    "Last, First M." -- flip those to "First M. Last" for the news cards."""
    if full and "," in full:
        last, first = (part.strip() for part in full.split(",", 1))
        if first:
            return f"{first} {last}"
    return full


def resolve_entity_url(person, entity_urls):
    """Clean profile URL for a crosswalk person, or None if we can't link them.

    Tries the same id keys the site keys its entity pages on: bioguideId
    (us-congress), ocdPersonId (ga-legislator), then any votegaCandidateId or a
    bioguideId in the candidate map (covers a sitting member whose only clean URL
    is their candidate page, e.g. Ossoff). Statewide executives have no group in
    entity_urls yet, so they resolve to None and render as plain text.
    """
    ids = person.get("ids") or {}
    bioguide = ids.get("bioguideId")
    ocd = ids.get("ocdPersonId")
    cand_ids = ids.get("votegaCandidateIds") or []

    us = entity_urls.get("us-congress", {})
    leg = entity_urls.get("ga-legislator", {})
    cand = entity_urls.get("candidate", {})

    if bioguide and bioguide in us:
        return us[bioguide]
    if ocd and ocd in leg:
        return leg[ocd]
    for cid in cand_ids:
        if cid in cand:
            return cand[cid]
    if bioguide and bioguide in cand:
        return cand[bioguide]
    return None


def is_ga_relevant(text_lower, has_entity, ga_terms):
    if has_entity:
        return True
    return any(term in text_lower for term in ga_terms)


def bucket_topics(text, topics):
    return [slug for slug, rx in topics.items() if rx.search(text)]


# --------------------------------------------------------------------------- #
# Feed fetch + parse
# --------------------------------------------------------------------------- #
def clean_text(s):
    return html.unescape(STRIP_TAGS.sub("", s or "")).strip()


def canonical_url(url):
    """Drop tracking query/fragment so the same story dedupes across feeds."""
    parts = urlsplit(url.strip())
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def parse_date(raw):
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw).astimezone(timezone.utc)
    except Exception:
        try:  # ISO 8601 (Atom <updated>)
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            return None


def _tag(el):
    """Local tag name without the Atom/RSS namespace."""
    return el.tag.rsplit("}", 1)[-1]


def parse_feed(raw_bytes, source):
    """Parse RSS <item> or Atom <entry> into normalized dicts."""
    try:
        root = ET.fromstring(raw_bytes)
    except ET.ParseError as exc:
        print(f"  Malformed feed XML from {source}: {exc}")
        return []

    items = []
    for node in root.iter():
        if _tag(node) not in ("item", "entry"):
            continue
        title = link = summary = date_raw = ""
        for child in node:
            name = _tag(child)
            if name == "title":
                title = child.text or ""
            elif name == "link":
                # RSS puts the URL in text; Atom in href=
                link = (child.text or child.get("href") or "").strip()
            elif name in ("description", "summary", "encoded"):
                if not summary:
                    summary = child.text or ""
            elif name in ("pubDate", "published", "updated", "date"):
                if not date_raw:
                    date_raw = child.text or ""

        title = clean_text(title)
        link = link.strip()
        if not title or not link:
            continue
        cu = canonical_url(link)
        items.append({
            "id": hashlib.sha1(cu.encode("utf-8")).hexdigest()[:12],
            "title": title,
            "url": link,
            "source": source,
            "publishedAt": (parse_date(date_raw).isoformat() if parse_date(date_raw) else None),
            "snippet": clean_text(summary)[:SNIPPET_MAX],
        })
        if len(items) >= PER_FEED_MAX:
            break
    return items


# --------------------------------------------------------------------------- #
# Overrides
# --------------------------------------------------------------------------- #
def load_overrides():
    if not os.path.exists(OVERRIDES_FILE):
        return {"suppress": set(), "patches": {}}
    with open(OVERRIDES_FILE, encoding="utf-8") as f:
        data = json.load(f)
    suppress = set(data.get("_suppress") or [])       # match on item id OR url substring
    patches = {k: v for k, v in data.items() if not k.startswith("_")}  # keyed by item id
    return {"suppress": suppress, "patches": patches}


def is_suppressed(item, suppress):
    if item["id"] in suppress:
        return True
    return any(s in item["url"] for s in suppress if not s.isalnum() or len(s) > 12)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    feeds, ga_terms, topics = load_sources()

    if not os.path.exists(CROSSWALK_FILE):
        print(f"Error: {CROSSWALK_FILE} not found -- run build_id_crosswalk.py first")
        sys.exit(1)
    with open(CROSSWALK_FILE, encoding="utf-8") as f:
        people = json.load(f)["people"]
    by_surname, sole_bare, indexed = build_entity_index(people)
    print(f"Indexed {indexed} linkable people across {len(by_surname)} surnames "
          f"({len(sole_bare)} bare-surname-eligible)\n")

    person_by_vgid = {p.get("vgId"): p for p in people if p.get("vgId")}
    id_index = build_id_index(people)
    entity_urls = load_entity_urls()
    overrides = load_overrides()

    raw_items, seen_ids, seen_titles = [], set(), set()
    dropped_national = 0

    for feed in feeds:
        name, url = feed["name"], feed["url"]
        bound_vgid = resolve_feed_entity(feed, id_index)
        # An official's own feed is inherently GA-relevant, so a bound feed
        # bypasses the ga_terms gate the same way an explicitly ga_focused one
        # does -- a "Statement on the shutdown" release must not be dropped for
        # never saying "Georgia".
        ga_focused = bool(feed.get("ga_focused")) or bool(bound_vgid)
        raw = fetch_bytes(url, label=name)
        if raw is None:
            print(f"[{name}] fetch failed -- skipping")
            continue
        items = parse_feed(raw, name)
        kept_here = 0
        for it in items:
            if it["id"] in seen_ids:
                continue
            norm_title = re.sub(r"[^a-z0-9]", "", it["title"].lower())
            if norm_title in seen_titles:
                continue
            if is_suppressed(it, overrides["suppress"]):
                continue

            text = f"{it['title']} {it['snippet']}"
            ents = match_entities(toks(text), by_surname, sole_bare)

            if not ga_focused and not is_ga_relevant(text.lower(), bool(ents), ga_terms):
                dropped_national += 1
                continue

            it["entityIds"] = [e["vgId"] for e in ents if e["vgId"]]
            it["entityNames"] = [e["name"] for e in ents]
            # Force-tag the feed's bound official (their own press release),
            # first and deduped, on top of anyone name-matched in the text.
            if bound_vgid and bound_vgid not in it["entityIds"]:
                it["entityIds"].insert(0, bound_vgid)
                bp = person_by_vgid.get(bound_vgid)
                it["entityNames"].insert(0, (bp.get("name") or {}).get("full") if bp else bound_vgid)
            it["topics"] = bucket_topics(text, topics)

            # Apply per-item overrides (add/replace tags).
            patch = overrides["patches"].get(it["id"])
            if patch:
                it["entityIds"] = patch.get("entityIds", it["entityIds"])
                it["topics"] = patch.get("topics", it["topics"])

            seen_ids.add(it["id"])
            seen_titles.add(norm_title)
            raw_items.append(it)
            kept_here += 1
        print(f"[{name}] {len(items)} fetched -> {kept_here} kept")

    # 45-day window; undated items are kept but sort last.
    cutoff = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)
    def in_window(it):
        if not it["publishedAt"]:
            return True
        try:
            return datetime.fromisoformat(it["publishedAt"]) >= cutoff
        except ValueError:
            return True
    windowed = [it for it in raw_items if in_window(it)]

    windowed.sort(key=lambda it: it["publishedAt"] or "", reverse=True)

    # Drop the internal-only entityNames debugging field before writing.
    for it in windowed:
        it.pop("entityNames", None)

    if not windowed:
        print("Error: no items produced -- refusing to write an empty news file")
        sys.exit(1)

    tagged = sum(1 for it in windowed if it["entityIds"])
    topic_counts = {}
    for it in windowed:
        for t in it["topics"]:
            topic_counts[t] = topic_counts.get(t, 0) + 1

    # Compact entity lookup for the page: vgId -> {name, url}. Built only for the
    # people actually tagged, with clean URLs resolved at build time so the page
    # needs no second fetch. url is null when the person has no clean profile yet
    # (e.g. statewide executives) -> the page renders those as plain text.
    entities = {}
    linked = 0
    for it in windowed:
        for vg in it["entityIds"]:
            if vg in entities:
                continue
            p = person_by_vgid.get(vg)
            if not p:
                continue
            url = resolve_entity_url(p, entity_urls)
            entities[vg] = {"name": display_name((p.get("name") or {}).get("full")), "url": url}
            if url:
                linked += 1

    output = {
        "metadata": {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "source": "Curated Georgia RSS feeds (_data/news_sources.yml)",
            "sources": [f["name"] for f in feeds],
            "count": len(windowed),
            "windowDays": WINDOW_DAYS,
            "entityTagged": tagged,
            "topicCounts": topic_counts,
            "disclaimer": DISCLAIMER,
        },
        "entities": entities,
        "items": windowed,
    }

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nDone. {len(windowed)} items ({tagged} entity-tagged, "
          f"{dropped_national} dropped as non-GA) -> {OUTPUT_FILE}")
    print(f"Entities: {len(entities)} tagged ({linked} with a clean profile link)")
    print(f"Topics: {topic_counts}")


if __name__ == "__main__":
    main()
