#!/usr/bin/env python3
"""Generate static, crawlable per-entity pages from the search-entities manifest.

Entity detail pages (legislators, members of Congress, races, candidates,
executives, justices) were served by single query-string templates
(ga-member.html?id=…) that rendered client-side and all self-canonicalized to one
URL — so thousands of high-intent pages could not be indexed. This script reads
assets/data/search-entities.json (the daily-rebuilt search manifest) and emits one
Jekyll page per entity into the _entities/ collection, each with a clean, stable
permalink, a unique title/description, server-rendered summary content, and
schema.org JSON-LD. GitHub Pages builds Jekyll in safe mode (no generator
plugins), so the pages are materialized here at deploy time instead.

It also writes _data/entity_urls.json (id → clean path, per type) so the legacy
?id= shells can client-redirect and hubs can link to clean URLs.

Both outputs are build artifacts (git-ignored). Run before `jekyll build`:
    python3 scripts/build_entity_pages.py

Phase 1 covers GA Legislators, U.S. Congress (GA delegation), and Races.
Additional categories (Candidate, Federal Executive, Justice) are added in later
phases via the CATEGORY_BUILDERS table.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime, date
from urllib.parse import urlparse, parse_qs, unquote

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(ROOT, "assets", "data")
ENTITIES_DIR = os.path.join(ROOT, "_entities")
PLACES_PATH = os.path.join(ROOT, "_data", "places.yml")
LOCAL_OFFICIALS_PATH = os.path.join(ROOT, "_data", "local_officials.yml")
ENTITY_URLS_PATH = os.path.join(ROOT, "_data", "entity_urls.json")
# Persisted {permalink: {"h": content-hash, "d": "YYYY-MM-DD"}} so a page's
# last_modified_at only advances when its content actually changes. Restored from
# the Actions cache across deploys (see deploy-pages.yml); missing = treat all as
# changed on the current data date, a safe (if noisier) fallback.
LASTMOD_STATE_PATH = os.path.join(ROOT, "_data", "entity_lastmod.json")

SITE_URL = "https://www.votega.org"


def _date_only(s):
    """Best-effort YYYY-MM-DD from an ISO date/datetime; today if unparseable."""
    if isinstance(s, str) and s.strip():
        try:
            return datetime.fromisoformat(s.strip().replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            m = re.match(r"(\d{4}-\d{2}-\d{2})", s.strip())
            if m:
                return m.group(1)
    return date.today().isoformat()


def resolve_lastmod(permalink, fingerprint, data_date, prior, new_state):
    """Return a page's last-modified date: the stored date when its content hash is
    unchanged, else data_date (the date the source data was produced)."""
    h = hashlib.sha1(
        json.dumps(fingerprint, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:16]
    prev = prior.get(permalink)
    d = prev["d"] if (prev and prev.get("h") == h and prev.get("d")) else data_date
    new_state[permalink] = {"h": h, "d": d}
    return d


def load(name):
    with open(os.path.join(SRC_DIR, name), encoding="utf-8") as fh:
        return json.load(fh)


def slugify(*parts):
    s = " ".join(str(p) for p in parts if p not in (None, ""))
    s = s.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return re.sub(r"-{2,}", "-", s)


def yaml_quote(s):
    """Double-quote a scalar for YAML front matter, escaping backslashes and quotes."""
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def qs_id(url, key="id"):
    return (parse_qs(urlparse(url).query).get(key) or [None])[0]


def write_page(subdir, slug, front_matter, body):
    out_dir = os.path.join(ENTITIES_DIR, subdir)
    os.makedirs(out_dir, exist_ok=True)
    lines = ["---"]
    for k, v in front_matter.items():
        if isinstance(v, dict):
            lines.append(f"{k}:")
            for kk, vv in v.items():
                if isinstance(vv, list):
                    lines.append(f"  {kk}: [{', '.join(yaml_quote(x) for x in vv)}]")
                elif vv is not None:
                    lines.append(f"  {kk}: {yaml_quote(vv)}")
                else:
                    lines.append(f"  {kk}: ")
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    with open(os.path.join(out_dir, slug + ".html"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n" + body + "\n")


def json_ld(obj):
    return ('<script type="application/ld+json">'
            + json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
            + "</script>")


def breadcrumb_ld(items):
    """items: list of (name, path_or_None). Final crumb (the page itself) omits the url."""
    elements = []
    for i, (name, path) in enumerate(items, start=1):
        el = {"@type": "ListItem", "position": i, "name": name}
        if path:
            el["item"] = SITE_URL + path
        elements.append(el)
    return json_ld({"@context": "https://schema.org", "@type": "BreadcrumbList",
                    "itemListElement": elements})


# ─────────────────────────── GA Legislators ───────────────────────────

def build_ga_legislators(records, urls, prior, new_state):
    data = load("ga-members.json")
    members = {m["id"]: m for m in data.get("members", [])}
    data_date = _date_only((data.get("metadata") or {}).get("generatedAt"))
    seen = set()
    count = 0
    for rec in records:
        if rec.get("category") != "GA Legislator":
            continue
        mid = qs_id(rec["url"])
        if not mid:
            continue
        m = members.get(mid, {})
        name = m.get("name") or rec.get("title") or ""
        chamber = m.get("chamber") or ""
        district = m.get("district")
        party = m.get("party") or ""
        is_senate = "senate" in chamber.lower()
        chamber_short = "senate" if is_senate else "house"
        role = "State Senator" if is_senate else "State Representative"
        role_short = "Senator" if is_senate else "Representative"

        slug = slugify(name, chamber_short, district)
        if slug in seen:  # extremely unlikely; disambiguate with a short id fragment
            slug = slugify(slug, mid.split("/")[-1][:8])
        seen.add(slug)
        permalink = f"/ga-legislators/{slug}/"
        urls.setdefault("ga-legislator", {})[mid] = permalink

        dist_txt = f", District {district}" if district else ""
        share_title = f"{name} — Georgia {role}{dist_txt}"
        desc = (f"{rec.get('desc') or (role + dist_txt)}. Voting record, party-line "
                f"loyalty, committee assignments, campaign finance, and contact "
                f"information for {name}.")

        org = "Georgia State Senate" if is_senate else "Georgia House of Representatives"
        ld = json_ld({
            "@context": "https://schema.org", "@type": "Person", "name": name,
            "jobTitle": role, "url": SITE_URL + permalink,
            "memberOf": {"@type": "GovernmentOrganization", "name": org,
                         "url": SITE_URL + "/ga-state-reps"},
            "affiliation": party or None,
        })

        entity = {"type": "ga-legislator", "id": mid, "name": name,
                  "title": role_short, "chamber": chamber, "district": district,
                  "party": party}
        lastmod = resolve_lastmod(permalink, {"e": entity, "t": share_title, "d": desc},
                                  data_date, prior, new_state)
        fm = {
            "layout": "default",
            "title": yaml_quote(name),
            "share-title": yaml_quote(share_title),
            "share-description": yaml_quote(desc),
            "permalink": permalink,
            "last_modified_at": lastmod,
            "entity": entity,
        }
        bc = breadcrumb_ld([("Home", "/"), ("Georgia Legislators", "/ga-state-reps"), (name, None)])
        body = (f'<script>window.VOTEGA_ENTITY = {{"id": {json.dumps(mid)}}};</script>\n'
                f"{ld}\n{bc}\n"
                f"{{% include entity/ga-legislator.html %}}")
        write_page("ga-legislators", slug, fm, body)
        count += 1
    return count


# ─────────────────────────── U.S. Congress (GA delegation) ───────────────────────────

def build_federal_legislators(records, urls, prior, new_state):
    data = load("current-members.json")
    members = {m.get("bioguideId"): m for m in (data.get("members") or [])}
    data_date = _date_only((data.get("metadata") or {}).get("generatedAt"))
    seen = set()
    count = 0
    for rec in records:
        if rec.get("category") != "U.S. Congress":
            continue
        bid = qs_id(rec["url"], "bioguideId")
        if not bid:
            continue
        m = members.get(bid, {})
        name = " ".join(x for x in (m.get("firstName"), m.get("lastName")) if x)
        if not name:  # manifest name is "Last, First"
            t = rec.get("title") or ""
            name = " ".join(reversed([p.strip() for p in t.split(",")])) if "," in t else t
        desc_txt = rec.get("desc") or ""
        is_senate = "senate" in desc_txt.lower()
        district = m.get("district")
        party = m.get("party") or (desc_txt.split(",")[-1].strip() if "," in desc_txt else "")
        role = "U.S. Senator" if is_senate else "U.S. Representative"
        chamber = "U.S. Senate" if is_senate else "U.S. House of Representatives"

        anchor = "senate" if is_senate else f"ga-{district}"
        slug = slugify(name, anchor)
        if slug in seen:
            slug = slugify(slug, bid)
        seen.add(slug)
        permalink = f"/us-congress/{slug}/"
        urls.setdefault("us-congress", {})[bid] = permalink

        dist_txt = f", Georgia District {district}" if district and not is_senate else " for Georgia"
        share_title = f"{name} — {role}{dist_txt}"
        desc = (f"{desc_txt or role}. Voting record, sponsored legislation, committee "
                f"assignments, campaign finance, and contact information for {name}, "
                f"member of the {chamber} from Georgia.")
        ld = json_ld({
            "@context": "https://schema.org", "@type": "Person", "name": name,
            "jobTitle": role, "url": SITE_URL + permalink,
            "memberOf": {"@type": "GovernmentOrganization", "name": chamber},
            "affiliation": party or None,
        })
        entity = {"type": "us-congress", "id": bid, "name": name,
                  "title": role, "chamber": chamber, "district": district, "party": party}
        lastmod = resolve_lastmod(permalink, {"e": entity, "t": share_title, "d": desc},
                                  data_date, prior, new_state)
        fm = {
            "layout": "default",
            "title": yaml_quote(name),
            "share-title": yaml_quote(share_title),
            "share-description": yaml_quote(desc),
            "permalink": permalink,
            "last_modified_at": lastmod,
            "entity": entity,
        }
        bc = breadcrumb_ld([("Home", "/"), ("U.S. Congress", "/federal-reps"), (name, None)])
        body = (f'<script>window.VOTEGA_ENTITY = {{"id": {json.dumps(bid)}}};</script>\n'
                f"{ld}\n{bc}\n"
                f"{{% include entity/federal-legislator.html %}}")
        write_page("us-congress", slug, fm, body)
        count += 1
    return count


# ─────────────────────────── Races ───────────────────────────

def build_races(records, urls, prior, new_state):
    data = load("races.json")
    races = {r["id"]: r for r in data.get("races", [])}
    data_date = _date_only(data.get("updatedAt"))
    seen = set()
    count = 0
    for rec in records:
        if rec.get("category") != "Race":
            continue
        rid = qs_id(rec["url"])
        if not rid:
            continue
        r = races.get(rid, {})
        name = rec.get("title") or rid
        chamber = r.get("chamber") or ""
        cycle = r.get("cycle")
        level = (r.get("level") or "").replace("-", " ")

        slug = slugify(rid)  # race ids are already clean & stable (e.g. senate-2026, ga-01-2026)
        if slug in seen:
            slug = slugify(slug, str(count))
        seen.add(slug)
        permalink = f"/races/{slug}/"
        urls.setdefault("race", {})[rid] = permalink

        share_title = f"{name} — Candidates & Results"
        desc = (f"Candidates, the incumbent, district information, and results for the "
                f"{name} race in Georgia.")
        entity = {"type": "race", "id": rid, "name": name, "chamber": chamber,
                  "cycle": cycle, "summary": (level.title() + " race") if level else None}
        lastmod = resolve_lastmod(permalink, {"e": entity, "t": share_title, "d": desc},
                                  data_date, prior, new_state)
        fm = {
            "layout": "default",
            "title": yaml_quote(name),
            "share-title": yaml_quote(share_title),
            "share-description": yaml_quote(desc),
            "permalink": permalink,
            "last_modified_at": lastmod,
            "entity": entity,
        }
        bc = breadcrumb_ld([("Home", "/"), ("2026 Elections", "/elections/"), (name, None)])
        body = (f'<script>window.VOTEGA_ENTITY = {{"id": {json.dumps(rid)}}};</script>\n'
                f"{bc}\n"
                f"{{% include entity/race.html %}}")
        write_page("races", slug, fm, body)
        count += 1
    return count


# ─────────────────────────── Candidates ───────────────────────────

def build_candidates(records, urls, prior, new_state):
    """One page per candidate at /candidates/<slug>/.

    Runs AFTER build_federal_legislators so urls['us-congress'] is populated: the
    11 federal incumbents running for re-election appear in the manifest with a
    ?raceId=&memberId= url (no candidate id) and already have a /us-congress/ page,
    so we point the legacy shell at that page rather than build a duplicate profile.

    Slug is name + seat, never the candidate id: make_candidate_id() ends ids with a
    positional row index (…-d-1), so a re-ordered source export would silently move
    a URL. The seat comes from the race id with its cycle stripped, which is stable.
    """
    data = load("races.json")
    data_date = _date_only(data.get("updatedAt"))
    races = data.get("races", [])

    # cid -> (candidate, race). A candidate id is stable per person across phases,
    # so the first occurrence wins.
    cand_index = {}
    for r in races:
        for phase in (r.get("phases") or {}).values():
            if not isinstance(phase, dict):
                continue
            groups = list((phase.get("ballots") or {}).values()) + [phase.get("candidates") or []]
            for group in groups:
                for c in (group or []):
                    cid = c.get("id")
                    if cid and cid not in cand_index:
                        cand_index[cid] = (c, r)

    us_urls = urls.get("us-congress", {})
    seen = set()
    count = 0
    for rec in records:
        if rec.get("category") != "Candidate":
            continue
        name = rec.get("title") or ""
        desc = rec.get("desc") or ""
        cid = qs_id(rec["url"])

        # Federal incumbent (?raceId=&memberId=…): redirect the shell to their
        # /us-congress/ page; don't emit a duplicate candidate page.
        if not cid:
            member_id = qs_id(rec["url"], "memberId")
            dest = us_urls.get(member_id)
            if member_id and dest:
                urls.setdefault("candidate", {})[member_id] = dest
            continue

        race = (cand_index.get(cid) or (None, {}))[1]
        rid = race.get("id") or ""
        anchor = re.sub(r"-20\d\d$", "", rid) if rid else slugify(desc)
        slug = slugify(name, anchor) or slugify(cid)
        if slug in seen:  # two different people, same name+seat (not seen in current data)
            slug = slugify(slug, hashlib.sha1(cid.encode()).hexdigest()[:6])
        seen.add(slug)
        permalink = f"/candidates/{slug}/"
        urls.setdefault("candidate", {})[cid] = permalink

        dist = race.get("district")
        race_label = (race.get("displayTitle")
                      or ((race.get("chamber") or "") + (f" District {dist}" if dist else ""))
                      or rid)
        race_url = urls.get("race", {}).get(rid)
        party = desc.split("·")[0].strip() if "·" in desc else ""

        share_title = f"{name} — Candidate for {race_label}".strip()
        page_desc = desc or f"Candidate profile for {name}."
        ld = json_ld({
            "@context": "https://schema.org", "@type": "Person", "name": name,
            "url": SITE_URL + permalink,
            "description": desc or None,
            "affiliation": party or None,
        })
        entity = {"type": "candidate", "id": cid, "name": name}
        lastmod = resolve_lastmod(permalink, {"e": entity, "t": share_title, "d": page_desc},
                                  data_date, prior, new_state)
        fm = {
            "layout": "default",
            "title": yaml_quote(name),
            "share-title": yaml_quote(share_title),
            "share-description": yaml_quote(page_desc),
            "permalink": permalink,
            "last_modified_at": lastmod,
            "entity": entity,
        }
        crumbs = [("Home", "/"), ("2026 Elections", "/elections/")]
        if race_url:
            crumbs.append((race_label, race_url))
        crumbs.append((name, None))
        bc = breadcrumb_ld(crumbs)
        body = (f'<script>window.VOTEGA_ENTITY = {{"id": {json.dumps(cid)}}};</script>\n'
                f"{ld}\n{bc}\n"
                f"{{% include entity/candidate.html %}}")
        write_page("candidates", slug, fm, body)
        count += 1
    return count


# ─────────────────────────── Federal Executives ───────────────────────────

def build_federal_executives(records, urls, prior, new_state):
    """One page per federal executive at /federal-executives/<slug>/.

    Data (bios, tabs) is rendered client-side by _includes/entity/federal-executive.html;
    the builder only needs the manifest record (name + role + the shell's ?id=). Slug is
    the person's name — the 19 names are unique — so it is stable and readable.
    """
    # executive.json is a Jekyll-rendered template (front matter), not plain JSON, so
    # it can't be loaded here — and isn't needed: the body renders client-side and the
    # builder works from the manifest record. Stamp with today's date.
    data_date = date.today().isoformat()
    seen = set()
    count = 0
    for rec in records:
        if rec.get("category") != "Federal Executive":
            continue
        oid = qs_id(rec["url"])
        if not oid:
            continue
        name = rec.get("title") or oid
        role = rec.get("desc") or ""
        slug = slugify(name) or slugify(oid)
        if slug in seen:
            slug = slugify(slug, oid)
        seen.add(slug)
        permalink = f"/federal-executives/{slug}/"
        urls.setdefault("federal-executive", {})[oid] = permalink

        share_title = f"{name} — {role}" if role else name
        desc = (f"{role}. Profile, background, and official actions for {name} in the "
                f"U.S. federal executive branch.") if role else f"Profile of {name}."
        ld = json_ld({
            "@context": "https://schema.org", "@type": "Person", "name": name,
            "jobTitle": role or None, "url": SITE_URL + permalink,
        })
        entity = {"type": "federal-executive", "id": oid, "name": name}
        lastmod = resolve_lastmod(permalink, {"e": entity, "t": share_title, "d": desc},
                                  data_date, prior, new_state)
        fm = {
            "layout": "default",
            "title": yaml_quote(name),
            "share-title": yaml_quote(share_title),
            "share-description": yaml_quote(desc),
            "permalink": permalink,
            "last_modified_at": lastmod,
            "entity": entity,
        }
        bc = breadcrumb_ld([("Home", "/"), ("Executive Branch", "/executive-branch.html"), (name, None)])
        body = (f'<script>window.VOTEGA_ENTITY = {{"id": {json.dumps(oid)}}};</script>\n'
                f"{ld}\n{bc}\n"
                f"{{% include entity/federal-executive.html %}}")
        write_page("federal-executives", slug, fm, body)
        count += 1
    return count


# ─────────────────────────── Supreme Court Justices ───────────────────────────

def build_justices(records, urls, prior, new_state):
    """One page per justice at /justices/<slug>/. Body renders client-side from
    supreme-court.json + scotus-decisions.json; the builder uses the manifest record."""
    court = load("supreme-court.json")
    data_date = _date_only((court.get("metadata") or {}).get("generatedAt"))
    seen = set()
    count = 0
    for rec in records:
        if rec.get("category") != "U.S. Supreme Court":
            continue
        jid = qs_id(rec["url"])
        if not jid:
            continue
        name = rec.get("title") or jid
        role = rec.get("desc") or "Justice of the Supreme Court of the United States"
        slug = slugify(name) or slugify(jid)
        if slug in seen:
            slug = slugify(slug, jid)
        seen.add(slug)
        permalink = f"/justices/{slug}/"
        urls.setdefault("justice", {})[jid] = permalink

        share_title = f"{name} — U.S. Supreme Court"
        desc = (f"{role}. Appointment, tenure, and voting record for {name} on the "
                f"Supreme Court of the United States.")
        ld = json_ld({
            "@context": "https://schema.org", "@type": "Person", "name": name,
            "jobTitle": role, "url": SITE_URL + permalink,
            "memberOf": {"@type": "GovernmentOrganization",
                         "name": "Supreme Court of the United States"},
        })
        entity = {"type": "justice", "id": jid, "name": name}
        lastmod = resolve_lastmod(permalink, {"e": entity, "t": share_title, "d": desc},
                                  data_date, prior, new_state)
        fm = {
            "layout": "default",
            "title": yaml_quote(name),
            "share-title": yaml_quote(share_title),
            "share-description": yaml_quote(desc),
            "permalink": permalink,
            "last_modified_at": lastmod,
            "entity": entity,
        }
        bc = breadcrumb_ld([("Home", "/"), ("Supreme Court", "/supreme-court.html"), (name, None)])
        body = (f'<script>window.VOTEGA_ENTITY = {{"id": {json.dumps(jid)}}};</script>\n'
                f"{ld}\n{bc}\n"
                f"{{% include entity/justice.html %}}")
        write_page("justices", slug, fm, body)
        count += 1
    return count


# ─────────────────────────── Local government (places) ───────────────────────────

def _places_source_fallback(place):
    """Best public URL to link when data is missing, per meetings platform."""
    cfg = ((place.get("domains") or {}).get("meetings")) or {}
    base = (cfg.get("base_url") or "").rstrip("/")
    if not base:
        return ""
    return base + "/AgendaCenter" if cfg.get("platform") == "civicplus" else base


def build_places(records, urls, prior, new_state):
    """Emit /local/<slug>/ pages from the places registry.

    Unlike the other builders this iterates _data/places.yml directly rather than
    the search manifest: the registry is the authoritative, committed source of
    truth for which places exist, so pages materialize at deploy even before the
    (separately scheduled) search index has picked a new place up.
    """
    if not os.path.exists(PLACES_PATH):
        return 0
    with open(PLACES_PATH, encoding="utf-8") as fh:
        places = (yaml.safe_load(fh) or {}).get("places", [])
    by_slug = {p["slug"]: p for p in places}
    # Officials is a derived domain: a place has it when a jurisdiction in
    # local_officials.yml shares its slug (join key == slug == id). See
    # LOCAL-GOVERNMENT-IA.md. It is the precedence domain, so it leads the list.
    officials_slugs = set()
    if os.path.exists(LOCAL_OFFICIALS_PATH):
        with open(LOCAL_OFFICIALS_PATH, encoding="utf-8") as fh:
            for j in (yaml.safe_load(fh) or {}).get("jurisdictions", []) or []:
                if isinstance(j, dict) and j.get("id"):
                    officials_slugs.add(j["id"])
    data_date = date.today().isoformat()  # registry is hand-edited; use today

    count = 0
    for p in places:
        slug = p["slug"]
        name = p.get("name") or slug
        ptype = p.get("type") or "county"
        permalink = f"/local/{slug}/"
        urls.setdefault("place", {})[slug] = permalink

        parent = by_slug.get(p.get("parentCounty") or "")
        # Officials leads (precedence domain), then the configured adapter domains.
        domains = (["officials"] if slug in officials_slugs else []) \
            + sorted((p.get("domains") or {}).keys())
        fallback = _places_source_fallback(p)

        kind = "City" if ptype == "city" else "County"
        has_officials = slug in officials_slugs
        share_title = f"{name}, Georgia — Local Officials & Government"
        if has_officials:
            desc = (f"Elected officials, plus public meeting agendas and minutes, for "
                    f"{name}, Georgia — who represents you locally, their seats, terms, "
                    f"and next elections, with meetings aggregated from the "
                    f"{'city' if ptype == 'city' else 'county'}'s official site.")
        else:
            desc = (f"Public meeting agendas, minutes, and video for {name}, Georgia. "
                    f"Board and commission meetings aggregated from the "
                    f"{'city' if ptype == 'city' else 'county'}'s official Agenda Center.")

        ld = json_ld({
            "@context": "https://schema.org", "@type": "GovernmentOrganization",
            "name": name, "url": SITE_URL + permalink,
            "areaServed": {"@type": "AdministrativeArea", "name": name},
            "containedInPlace": {"@type": "State", "name": "Georgia"},
        })
        bc = breadcrumb_ld([("Home", "/"), ("Local Government", "/local/"), (name, None)])

        entity = {
            "type": "place", "slug": slug, "placeType": ptype, "name": name,
            "parentCountySlug": (parent or {}).get("slug"),
            "parentCountyName": (parent or {}).get("name"),
            "domains": domains,  # lets place.html branch server-side (officials/meetings)
        }
        lastmod = resolve_lastmod(
            permalink, {"e": entity, "t": share_title, "d": desc, "dom": domains},
            data_date, prior, new_state)

        place_js = {"slug": slug, "placeName": name,
                    "sourceFallback": fallback, "domains": domains}
        fm = {
            "layout": "default",
            "title": yaml_quote(name),
            "share-title": yaml_quote(share_title),
            "share-description": yaml_quote(desc),
            "permalink": permalink,
            "last_modified_at": lastmod,
            "entity": entity,
        }
        body = (f"<script>window.VOTEGA_PLACE = {json.dumps(place_js)};</script>\n"
                f"{ld}\n{bc}\n"
                f"{{% include entity/place.html %}}")
        write_page("local", slug, fm, body)
        count += 1
    return count


CATEGORY_BUILDERS = [
    ("GA Legislator", build_ga_legislators),
    ("U.S. Congress", build_federal_legislators),
    ("Race", build_races),
    ("Candidate", build_candidates),  # after U.S. Congress: reuses urls['us-congress']
    ("Federal Executive", build_federal_executives),
    ("U.S. Supreme Court", build_justices),
    ("Local Government", build_places),  # iterates _data/places.yml, ignores records
]


def main():
    records = load("search-entities.json").get("records", [])
    os.makedirs(ENTITIES_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(ENTITY_URLS_PATH), exist_ok=True)

    prior = {}
    if os.path.exists(LASTMOD_STATE_PATH):
        try:
            with open(LASTMOD_STATE_PATH, encoding="utf-8") as fh:
                prior = json.load(fh)
        except (ValueError, OSError):
            prior = {}
    new_state = {}

    urls = {}
    total = 0
    for label, builder in CATEGORY_BUILDERS:
        try:
            n = builder(records, urls, prior, new_state)
        except Exception as exc:
            print(f"  {label}: FAILED — {exc}", file=sys.stderr)
            continue
        print(f"  {label}: {n} pages")
        total += n
    with open(ENTITY_URLS_PATH, "w", encoding="utf-8") as fh:
        json.dump(urls, fh, ensure_ascii=False, separators=(",", ":"))
    with open(LASTMOD_STATE_PATH, "w", encoding="utf-8") as fh:
        json.dump(new_state, fh, ensure_ascii=False, separators=(",", ":"))
    changed = sum(1 for k, v in new_state.items() if prior.get(k, {}).get("h") != v["h"])
    print(f"build_entity_pages: {total} pages, {sum(len(v) for v in urls.values())} URL mappings, "
          f"{changed} changed since last run")
    return 0


if __name__ == "__main__":
    sys.exit(main())
