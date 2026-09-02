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

import json
import os
import re
import sys
from urllib.parse import urlparse, parse_qs, unquote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(ROOT, "assets", "data")
ENTITIES_DIR = os.path.join(ROOT, "_entities")
ENTITY_URLS_PATH = os.path.join(ROOT, "_data", "entity_urls.json")
ENTITY_URLS_ASSET = os.path.join(ROOT, "assets", "data", "entity-urls.json")

SITE_URL = "https://www.votega.org"


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
                lines.append(f"  {kk}: {yaml_quote(vv)}" if vv is not None else f"  {kk}: ")
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    with open(os.path.join(out_dir, slug + ".html"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n" + body + "\n")


def json_ld(obj):
    return ('<script type="application/ld+json">'
            + json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
            + "</script>")


# ─────────────────────────── GA Legislators ───────────────────────────

def build_ga_legislators(records, urls):
    members = {m["id"]: m for m in load("ga-members.json").get("members", [])}
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

        fm = {
            "layout": "default",
            "title": yaml_quote(name),
            "share-title": yaml_quote(share_title),
            "share-description": yaml_quote(desc),
            "permalink": permalink,
            "entity": {"type": "ga-legislator", "id": mid, "name": name,
                       "title": role_short, "chamber": chamber, "district": district,
                       "party": party},
        }
        body = (f'<script>window.VOTEGA_ENTITY = {{"id": {json.dumps(mid)}}};</script>\n'
                f"{ld}\n"
                f"{{% include entity/ga-legislator.html %}}")
        write_page("ga-legislators", slug, fm, body)
        count += 1
    return count


# ─────────────────────────── U.S. Congress (GA delegation) ───────────────────────────

def build_federal_legislators(records, urls):
    members = {m.get("bioguideId"): m for m in
               (load("current-members.json").get("members") or [])}
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
        fm = {
            "layout": "default",
            "title": yaml_quote(name),
            "share-title": yaml_quote(share_title),
            "share-description": yaml_quote(desc),
            "permalink": permalink,
            "entity": {"type": "us-congress", "id": bid, "name": name,
                       "title": role, "chamber": chamber, "district": district,
                       "party": party},
        }
        body = (f'<script>window.VOTEGA_ENTITY = {{"id": {json.dumps(bid)}}};</script>\n'
                f"{ld}\n"
                f"{{% include entity/federal-legislator.html %}}")
        write_page("us-congress", slug, fm, body)
        count += 1
    return count


# ─────────────────────────── Races ───────────────────────────

def build_races(records, urls):
    races = {r["id"]: r for r in load("races.json").get("races", [])}
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
        fm = {
            "layout": "default",
            "title": yaml_quote(name),
            "share-title": yaml_quote(share_title),
            "share-description": yaml_quote(desc),
            "permalink": permalink,
            "entity": {"type": "race", "id": rid, "name": name, "chamber": chamber,
                       "cycle": cycle, "summary": (level.title() + " race") if level else None},
        }
        body = (f'<script>window.VOTEGA_ENTITY = {{"id": {json.dumps(rid)}}};</script>\n'
                f"{{% include entity/race.html %}}")
        write_page("races", slug, fm, body)
        count += 1
    return count


CATEGORY_BUILDERS = [
    ("GA Legislator", build_ga_legislators),
    ("U.S. Congress", build_federal_legislators),
    ("Race", build_races),
]


def main():
    records = load("search-entities.json").get("records", [])
    os.makedirs(ENTITIES_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(ENTITY_URLS_PATH), exist_ok=True)
    urls = {}
    total = 0
    for label, builder in CATEGORY_BUILDERS:
        try:
            n = builder(records, urls)
        except Exception as exc:
            print(f"  {label}: FAILED — {exc}", file=sys.stderr)
            continue
        print(f"  {label}: {n} pages")
        total += n
    with open(ENTITY_URLS_PATH, "w", encoding="utf-8") as fh:
        json.dump(urls, fh, ensure_ascii=False, separators=(",", ":"))
    # Served copy so the client-side link rewriter (assets/scripts/entity-url.js)
    # can map legacy ?id= links to their clean URLs.
    os.makedirs(os.path.dirname(ENTITY_URLS_ASSET), exist_ok=True)
    with open(ENTITY_URLS_ASSET, "w", encoding="utf-8") as fh:
        json.dump(urls, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"build_entity_pages: {total} pages, {sum(len(v) for v in urls.values())} URL mappings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
