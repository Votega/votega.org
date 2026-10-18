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

Most sources publish RSS/Atom. A source that publishes none (usg.edu/news/ is
a TerminalFour site with no feed) gets a named HTML adapter in HTML_PARSERS,
selected by a `parser` key on that feed in news_sources.yml. An adapter scrapes
only what a feed would have given -- headline, link, date, the page's own
summary -- and is deliberately brittle: if the markup moves it yields nothing
and the feed simply contributes no items, which is how a 404 feed already fails.

Not every source is fetched. The Governor's executive orders come from the EO
pipeline's own committed artifacts (assets/data/ga-executive-orders-<year>.json +
assets/data/eo-text/), configured under `executive_orders:` in news_sources.yml
rather than as a feed -- see load_eo_items() and scripts/lib/ga_eo_news.py for
why, and for the category allowlist that keeps 81%-of-the-corpus board
appointments out of the hub. Local items go through ingest() exactly like fetched
ones, so there is one set of tagging and relevance rules.

Usage:
    python scripts/generate_ga_news.py [output.json] [overrides.json]
"""

import html
import hashlib
import json
from lib.atomic_io import write_json_atomic
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit, urlunsplit
import xml.etree.ElementTree as ET

import yaml

from lib.http import DEFAULT_USER_AGENT, fetch_bytes
from lib.ga_match import toks
from lib.ga_eo_news import (
    DEFAULT_CATEGORIES as EO_DEFAULT_CATEGORIES,
    build_news_items as build_eo_news_items,
    load_orders as load_eo_orders,
    make_text_reader as make_eo_text_reader,
)

HERE           = os.path.dirname(os.path.abspath(__file__))
REPO           = os.path.dirname(HERE)
SOURCES_FILE   = os.path.join(REPO, "_data", "news_sources.yml")
CROSSWALK_FILE = os.path.join(REPO, "assets", "data", "id-crosswalk.json")
ENTITY_URLS_FILE = os.path.join(REPO, "_data", "entity_urls.json")
DATA_DIR       = os.path.join(REPO, "assets", "data")
EO_TEXT_DIR    = os.path.join(DATA_DIR, "eo-text")
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
    eo = cfg.get("executive_orders") or None
    return feeds, ga_terms, topics, eo


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


def is_ga_relevant(text_lower, has_entity, ga_terms, excluded_terms=()):
    """Keep an item from a non-GA-focused feed only if it is actually about GA.

    `excluded_terms` drops specific `ga_terms` for one feed, for a source whose
    boilerplate names a Georgia place on every item regardless of subject --
    NetChoice datelines every release "ATLANTA--", so `atlanta` alone kept its
    releases about other states' laws. Such a feed must name a GA politician or
    a GA term other than its own boilerplate. The exclusion is per-feed on
    purpose: an Atlanta-datelined GPB or Georgia Recorder story is real GA news.
    """
    if has_entity:
        return True
    return any(term in text_lower for term in ga_terms if term not in excluded_terms)


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
# HTML adapters (sources with no RSS/Atom feed)
# --------------------------------------------------------------------------- #
#: usg.edu/news/ rows: a MM.DD.YYYY date in <span class="quiet">, then the
#: headline link. The "Latest News" row wraps the link in an <h3> and adds the
#: page's own one-paragraph summary; the "More News" rows are a bare <a> with no
#: summary at all -- so the link pattern must not require either, and is scoped
#: to /news/ hrefs instead to avoid matching some other anchor in the row.
USG_DATE = re.compile(r'\s*(\d{1,2})\.(\d{1,2})\.(\d{4})\s*</span>')
USG_LINK = re.compile(r"""<a\s+href=["']([^"']*/news/[^"']+)["'][^>]*>(.*?)</a>""", re.S)


def parse_usg_html(raw_bytes, source, feed_url):
    """Scrape the University System of Georgia newsroom listing."""
    page = raw_bytes.decode("utf-8", "replace")
    items = []
    for chunk in page.split('<span class="quiet">')[1:]:
        d = USG_DATE.match(chunk)
        a = USG_LINK.search(chunk)
        if not d or not a:
            continue
        month, day, year = (int(x) for x in d.groups())
        try:
            when = datetime(year, month, day, tzinfo=timezone.utc)
        except ValueError:
            continue
        title = clean_text(a.group(2))
        link = urljoin(feed_url, a.group(1).strip())
        if not title:
            continue
        # The row's summary, where there is one, is whatever follows the headline
        # inside the row div. A "More News" row has none -- hence None, not "".
        tail = chunk[a.end():]
        end = tail.find("</div>")
        snippet = clean_text(tail[:end] if end != -1 else tail)
        cu = canonical_url(link)
        items.append({
            "id": hashlib.sha1(cu.encode("utf-8")).hexdigest()[:12],
            "title": title,
            "url": link,
            "source": source,
            "publishedAt": when.isoformat(),
            "snippet": snippet[:SNIPPET_MAX] or None,
        })
        if len(items) >= PER_FEED_MAX:
            break
    return items


#: sos.ga.gov/news/division/<id> cards: one <article class="card card-list__item">
#: per release, carrying a "Month DD, YYYY" <span class="card__date">, the
#: headline as the only <a class="heading__link"> in the card, and a
#: <div class="card__summary">. The headline is scoped to that class because the
#: enclosing <h2> repeats the title verbatim in its own id= and name=
#: attributes, and the card also links the same article twice (headline plus a
#: "Read the full article" anchor) -- so a bare /news/ href pattern would match
#: the wrong thing.
SOS_CARD = '<article class="card card-list__item"'
SOS_DATE = re.compile(r'<span class="card__date">\s*([A-Z][a-z]+ \d{1,2}, \d{4})\s*</span>')
SOS_LINK = re.compile(
    r"""<a\s+href=["']([^"']+)["'][^>]*class=["'][^"']*heading__link[^"']*["'][^>]*>(.*?)</a>""",
    re.S)
SOS_SUMMARY = re.compile(r'<div class="card__summary">(.*?)</div>', re.S)


def parse_sos_html(raw_bytes, source, feed_url):
    """Scrape a Georgia Secretary of State news listing.

    The agency's rss.xml -- which this feed pointed at until now -- is not its
    newsroom. It is the site-wide alert/banner feed: "Student Ambassador
    Registration Banner - Cloned", professional-licensing-board go-live
    notices, items going back to 2025, and no press releases at all. The
    division listing is the actual release stream (the Elections Division is 31).
    """
    page = raw_bytes.decode("utf-8", "replace")
    items = []
    for chunk in page.split(SOS_CARD)[1:]:
        d = SOS_DATE.search(chunk)
        a = SOS_LINK.search(chunk)
        if not d or not a:
            continue
        try:
            when = datetime.strptime(d.group(1), "%B %d, %Y").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        title = clean_text(a.group(2))
        if not title:
            continue
        link = urljoin(feed_url, a.group(1).strip())
        sm = SOS_SUMMARY.search(chunk)
        snippet = clean_text(sm.group(1)) if sm else ""
        cu = canonical_url(link)
        items.append({
            "id": hashlib.sha1(cu.encode("utf-8")).hexdigest()[:12],
            "title": title,
            "url": link,
            "source": source,
            "publishedAt": when.isoformat(),
            "snippet": snippet[:SNIPPET_MAX] or None,
        })
        if len(items) >= PER_FEED_MAX:
            break
    return items


#: `parser` values news_sources.yml may name. Omitting the key means RSS/Atom.
HTML_PARSERS = {"usg": parse_usg_html, "sos": parse_sos_html}


#: Seconds between re-attempts for a feed with `blocked_retries` set.
BLOCKED_RETRY_WAIT = 10

#: `fetch_with` values news_sources.yml may name. Omitting the key uses urllib
#: via lib.http, which is what every feed but one wants.
FEED_TRANSPORTS = ("curl",)


def fetch_via_curl(url, label, timeout=30, verbose=True):
    """Fetch a URL with the curl binary instead of urllib.

    For one feed, lib.http cannot reach the host at all. sos.ga.gov sits behind
    a Cloudflare filter that decides on the TLS client fingerprint, not on
    anything in the request we control: measured interleaved against the same
    IP and the same User-Agent, urllib scored 0/6 while curl scored 4/6, and
    four urllib variants (default context, ALPN pinned to http/1.1, curl's
    cipher list, and both together) scored 0/3 each. No header or TLS setting
    reachable from the standard library gets through, so retrying urllib here
    would be a knob that cannot help the one feed that needs it.

    curl is a standard HTTP client, the User-Agent stays our own, and the
    site's robots.txt disallows nothing under /news/ -- this is ordinary
    crawling of a public agency's press releases, not an attempt to pass as a
    browser. Deliberately NOT added to lib.http: that module is the project's
    single statement of the retry policy and is GET-via-urllib by design, and
    this is one source's transport problem rather than a policy change. Move it
    to lib/ if a second source ever needs it.

    `--fail` matters: without it curl exits 0 on a 403 and hands back the
    "Just a moment..." interstitial as a 200-looking body, which the HTML
    adapter would then scrape to zero items and report as changed markup.
    """
    cmd = ["curl", "--silent", "--show-error", "--fail", "--location",
           "--max-redirs", "3", "--max-time", str(timeout),
           "--user-agent", DEFAULT_USER_AGENT, "--header", "Accept: */*", url]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout + 10)
    except FileNotFoundError:
        print(f"  [{label}] curl not found on PATH -- cannot fetch this feed")
        return None
    except subprocess.SubprocessError as exc:
        if verbose:
            print(f"  [{label}] curl failed: {exc}")
        return None
    if proc.returncode != 0:
        if verbose:
            err = proc.stderr.decode("utf-8", "replace").strip()[:200]
            print(f"  [{label}] curl exit {proc.returncode}: {err or 'blocked'}")
        return None
    return proc.stdout or None


def fetch_feed_bytes(url, label, blocked_retries=0, transport=None):
    """Fetch one feed, with optional extra attempts for a bot-challenge 403.

    lib.http follows CLAUDE.md's policy exactly -- retry 429 and 5xx, return
    None immediately on any other 4xx -- and that is right for an API, where a
    403 means the request itself is wrong and replaying it only burns quota.

    Cloudflare's "Just a moment..." interstitial is also served as a 403, and it
    is not a client error: it is a probabilistic challenge that the identical
    request passes on a later try. sos.ga.gov serves it to roughly half of our
    fetches, which is why that feed contributed zero items to every committed
    run. Nothing about the request was fixable -- measured, the challenge fires
    independently of User-Agent and of the Accept/Accept-Language headers, and
    `/news/` is not disallowed by the site's robots.txt, so this is an
    indiscriminate bot filter rather than a refusal aimed at us.

    Retrying here rather than in lib.http keeps that module's policy (and the
    twelve generators relying on it) untouched, and the opt-in is per feed, so a
    source that genuinely 403s still fails fast instead of stalling the build.
    """
    if transport and transport not in FEED_TRANSPORTS:
        print(f"  WARNING: feed '{label}' names unknown fetch_with "
              f"'{transport}' -- expected one of {sorted(FEED_TRANSPORTS)}; "
              f"falling back to urllib")
        transport = None

    for attempt in range(blocked_retries + 1):
        if transport == "curl":
            raw = fetch_via_curl(url, label, verbose=(attempt == 0))
        else:
            raw = fetch_bytes(url, label=label, verbose=(attempt == 0))
        if raw is not None:
            return raw
        if attempt < blocked_retries:
            print(f"[{label}] blocked or unreachable -- retrying in "
                  f"{BLOCKED_RETRY_WAIT}s (attempt {attempt + 2}/"
                  f"{blocked_retries + 1})")
            time.sleep(BLOCKED_RETRY_WAIT)
    return None


def parse_source(raw_bytes, feed):
    """Parse one source's bytes into normalized items, RSS/Atom or HTML."""
    name = feed["name"]
    parser = feed.get("parser")
    if not parser:
        return parse_feed(raw_bytes, name)
    fn = HTML_PARSERS.get(parser)
    if fn is None:
        print(f"  WARNING: feed '{name}' names unknown parser '{parser}' "
              f"-- expected one of {sorted(HTML_PARSERS)}")
        return []
    items = fn(raw_bytes, name, feed["url"])
    if not items:
        print(f"  WARNING: HTML parser '{parser}' found no items for '{name}' "
              f"-- the page markup may have changed")
    return items

# --------------------------------------------------------------------------- #
# Local sources (already-committed data, no fetch)
# --------------------------------------------------------------------------- #
def make_item_id(url):
    """The feed path's item id, so a local source dedupes by the same rule."""
    return hashlib.sha1(canonical_url(url).encode("utf-8")).hexdigest()[:12]


def load_eo_items(eo_cfg, source_name):
    """Governor's executive orders as news items, read off disk.

    gov.georgia.gov is deliberately NOT added as a feed: the EO pipeline
    (update-ga-executive-orders.yml) already fetches, hashes, archives and
    text-extracts every order twice a day, so a feed here would be a second
    network dependency and a second failure mode for data the repo holds. The
    cards inherit that pipeline's archiveUrl and sha256 as a side benefit.

    Only the years the 45-day window can reach are read, so the file count does
    not grow with the archive (3,508 orders back to 2020).
    """
    now = datetime.now(timezone.utc)
    years = sorted({now.year, (now - timedelta(days=WINDOW_DAYS)).year})
    orders = load_eo_orders(DATA_DIR, years)
    if not orders:
        print(f"[{source_name}] WARNING: no order files for {years} in {DATA_DIR} "
              f"-- expected ga-executive-orders-<year>.json")
        return []

    categories = eo_cfg.get("categories") or list(EO_DEFAULT_CATEGORIES)
    present = {o.get("category") for o in orders}
    unknown = sorted(c for c in categories if c not in present)
    if unknown:
        # A typo'd category silently filters everything out, so name it.
        print(f"[{source_name}] warning: configured categor(ies) match no order "
              f"in {years}: {', '.join(unknown)}")

    items = build_eo_news_items(orders, source_name,
                                make_eo_text_reader(EO_TEXT_DIR),
                                categories, make_item_id, SNIPPET_MAX)
    print(f"[{source_name}] {len(orders)} orders on file -> {len(items)} in "
          f"allowlisted categories ({len(present - set(categories))} categor"
          f"{'y' if len(present - set(categories)) == 1 else 'ies'} excluded)")
    return items


# --------------------------------------------------------------------------- #
# Overrides
# --------------------------------------------------------------------------- #
def load_overrides():
    if not os.path.exists(OVERRIDES_FILE):
        return {"suppress": set(), "patches": {}, "add": []}
    with open(OVERRIDES_FILE, encoding="utf-8") as f:
        data = json.load(f)
    suppress = set(data.get("_suppress") or [])       # match on item id OR url substring
    patches = {k: v for k, v in data.items() if not k.startswith("_")}  # keyed by item id
    return {"suppress": suppress, "patches": patches, "add": data.get("_add") or []}


def load_manual_items(overrides):
    """Hand-curated articles from the overrides file's `_add` list, shaped like
    feed items so they go through the same ingest gates (dedupe, entity
    tagging, topics, window) rather than a second path with its own rules."""
    items = []
    for a in overrides["add"]:
        title, url = clean_text(a.get("title") or ""), (a.get("url") or "").strip()
        if not title or not url:
            print(f"[manual] skipping _add entry without title/url: {a!r}")
            continue
        items.append({
            "id": make_item_id(url),
            "title": title,
            "url": url,
            "source": a.get("source") or "Manual",
            "publishedAt": a.get("publishedAt"),
            "snippet": clean_text(a.get("snippet") or "")[:SNIPPET_MAX],
        })
    return items


def is_suppressed(item, suppress):
    if item["id"] in suppress:
        return True
    return any(s in item["url"] for s in suppress if not s.isalnum() or len(s) > 12)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    feeds, ga_terms, topics, eo_cfg = load_sources()

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
    stats = {"dropped_national": 0}

    def ingest(items, label, bound_vgid, ga_focused, excluded_terms=frozenset(),
               dedupe_titles=True):
        """Dedupe, GA-gate, entity-tag and topic-bucket one source's items.

        Shared by the fetched feeds and the local executive-order source so both
        go through exactly the same gates -- a local source must not be a second
        path with its own tagging rules.

        `dedupe_titles=False` turns off only the normalized-title collapse, for a
        source whose titles are boilerplate rather than a story headline. The
        title rule exists to collapse ONE story syndicated by several outlets;
        two separately signed executive orders can carry a byte-identical title
        ("Amending the State of Emergency for Georgia Wildfires", signed
        2026-05-05 and again 2026-05-12; two Albany State demolition orders
        signed the same day -- three such pairs in 2026 alone), and collapsing
        those drops a real primary document. Their identity is the order number;
        the url-hash id still dedupes a genuine repeat.
        """
        kept_here = 0
        for it in items:
            if it["id"] in seen_ids:
                continue
            norm_title = re.sub(r"[^a-z0-9]", "", it["title"].lower()) if dedupe_titles else None
            if norm_title and norm_title in seen_titles:
                continue
            if is_suppressed(it, overrides["suppress"]):
                continue

            text = f"{it['title']} {it['snippet']}"
            ents = match_entities(toks(text), by_surname, sole_bare)

            if not ga_focused and not is_ga_relevant(
                    text.lower(), bool(ents), ga_terms, excluded_terms):
                stats["dropped_national"] += 1
                continue

            it["entityIds"] = [e["vgId"] for e in ents if e["vgId"]]
            it["entityNames"] = [e["name"] for e in ents]
            # Force-tag the source's bound official (their own press release or
            # their own signed order), first and deduped, on top of anyone
            # name-matched in the text.
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
            if norm_title:
                seen_titles.add(norm_title)
            raw_items.append(it)
            kept_here += 1
        print(f"[{label}] {len(items)} fetched -> {kept_here} kept")

    for feed in feeds:
        name, url = feed["name"], feed["url"]
        bound_vgid = resolve_feed_entity(feed, id_index)
        # An official's own feed is inherently GA-relevant, so a bound feed
        # bypasses the ga_terms gate the same way an explicitly ga_focused one
        # does -- a "Statement on the shutdown" release must not be dropped for
        # never saying "Georgia".
        ga_focused = bool(feed.get("ga_focused")) or bool(bound_vgid)
        excluded_terms = {t.lower() for t in (feed.get("ga_terms_exclude") or [])}
        unknown = sorted(excluded_terms - set(ga_terms))
        if unknown:
            print(f"[{name}] warning: ga_terms_exclude names term(s) not in "
                  f"ga_terms: {', '.join(unknown)}")
        raw = fetch_feed_bytes(
            url, name,
            blocked_retries=int(feed.get("blocked_retries") or 0),
            transport=feed.get("fetch_with"))
        if raw is None:
            print(f"[{name}] fetch failed -- skipping")
            continue
        ingest(parse_source(raw, feed), name, bound_vgid, ga_focused, excluded_terms)

    # Local source: the Governor's executive orders, already on disk.
    eo_source_name = None
    if eo_cfg:
        eo_source_name = eo_cfg.get("name") or "Georgia executive orders"
        # ga_focused is unconditional, not inherited from the entity binding: a
        # Georgia governor's executive order is GA news whether or not its title
        # says "Georgia" ("Lowering flags to half-staff ... Patriot Day").
        ingest(load_eo_items(eo_cfg, eo_source_name), eo_source_name,
               resolve_feed_entity(eo_cfg, id_index), True, dedupe_titles=False)

    # Hand-curated articles (overrides `_add`): GA news by editorial decision.
    manual = load_manual_items(overrides)
    if manual:
        ingest(manual, "manual", None, True)

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
            # Carry the alt-ids so an entity page can reverse-map its own id
            # (bioguideId / ocdPersonId / candidateId) -> vgId and pull just this
            # person's news client-side. Only tagged people land here, so the map
            # stays small. Omit null/empty id fields to keep it compact.
            pids = p.get("ids") or {}
            entry = {"name": display_name((p.get("name") or {}).get("full")), "url": url}
            if pids.get("bioguideId"):
                entry["bioguideId"] = pids["bioguideId"]
            if pids.get("ocdPersonId"):
                entry["ocdPersonId"] = pids["ocdPersonId"]
            if pids.get("votegaCandidateIds"):
                entry["candidateIds"] = pids["votegaCandidateIds"]
            entities[vg] = entry
            if url:
                linked += 1

    output = {
        "metadata": {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "source": "Curated Georgia RSS feeds (_data/news_sources.yml)",
            # Drives the page's source filter chips, so a local source has to be
            # listed here too or its cards cannot be filtered to.
            "sources": [f["name"] for f in feeds] + ([eo_source_name] if eo_source_name else []),
            "count": len(windowed),
            "windowDays": WINDOW_DAYS,
            "entityTagged": tagged,
            "topicCounts": topic_counts,
            "disclaimer": DISCLAIMER,
        },
        "entities": entities,
        "items": windowed,
    }

    write_json_atomic(OUTPUT_FILE, output, indent=2)

    print(f"\nDone. {len(windowed)} items ({tagged} entity-tagged, "
          f"{stats['dropped_national']} dropped as non-GA) -> {OUTPUT_FILE}")
    print(f"Entities: {len(entities)} tagged ({linked} with a clean profile link)")
    print(f"Topics: {topic_counts}")


if __name__ == "__main__":
    main()
