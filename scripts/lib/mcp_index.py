"""Index files for the VoteGA MCP server (spec: docs/superpowers/specs/2026-10-23-mcp-server-design.md,
§5.1 and §12). The one implementation; scripts/build_mcp_index.py loads the inputs and calls these.

Pure functions over parsed inputs: no file reads, no network, no yaml import, so the offline test job
(which installs no packages) can exercise every rule.

Phase 1 (core): the four index families the Phase 2 tools read.
  members-index.json         GA legislators + the Georgia federal delegation
  zip/<zip3>.json            ga-zip-districts.json, one shard per 3-digit prefix
  counties-index.json        districts per county with population shares (counties_doc())
  local-officials-index.json county commissions / city councils + sheriffs
  meta.json                  per-file hashes and sizes, and per-dataset dates (written last)

Phase 3 (the indexes for the remaining tools; executive orders are left out for now):
  former-members-index.json  members found only in a frozen biennium
  local-mentions-index.json  local-topic mentions from agendas and minutes
  vote-files.json            sha256 of each vote index and member slice
  bills/                     lib/mcp_bills.py
  races-, candidates-index   lib/mcp_elections.py

Rules carried from CLAUDE.md:
  - A GA legislator is keyed `ga:<legisGaGovId>`, a federal member `us:<bioguideId>` (spec §5.5).
    The roster `id` is an opaque handle: it appears here only as the vote-slice file name, built
    with the same transform as build_member_votes_slices.member_slug().
  - vgIds follow `metadata.mergedVgIds` forwards, so no row carries a retired vgId.
  - Blank is None, never "".
"""

import re

from lib.ga_former import departure_note, former_records

SITE = "https://www.votega.org"
GA_STATE = "Georgia"

DEPARTED_STATUSES = {"Resigned", "Removed", "Deceased"}

ZIP_MEANING = (
    "Districts and counties TOUCHING the ZIP, ranked by estimated share of the ZIP's residents, "
    "largest first. Every district with any residents is listed. A ZIP is not a district: only a "
    "street address identifies the districts a voter lives in. PO-box ZIPs carry no districts.")

COUNTY_MEANING = (
    "For each county, the 2020 population living in each district, and that as a share of the "
    "county. A county is not a district: a county in several districts lists each of them.")

FORMER_MEANING = (
    "General Assembly members who appear only in a frozen biennium, not on the current roster. "
    "Each row describes their newest biennium. No contact details. A member who left during the "
    "current term is in members-index.json with serving=false.")

MENTIONS_MEANING = (
    "Meeting agendas and minutes in which a topic's keywords appear, newest first. A mention is "
    "not an action taken; future dates are posted agendas. Only some places are scanned.")

OFFICIALS_MEANING = (
    "Human-reviewed rosters, incomplete by design: a place not listed is not covered, which is "
    "not the same as having no officials. Each member row carries its own source. A row with a "
    "future takesOffice is an incoming member who does not hold the seat yet, and a row with a "
    "leavesOffice is still serving until that date; filter on the request date.")


def blank(v):
    """'' and whitespace -> None; everything else unchanged."""
    if isinstance(v, str) and not v.strip():
        return None
    return v


def iso(v):
    """A date/datetime (PyYAML parses bare dates) or string -> 'YYYY-MM-DD' / None."""
    v = blank(v)
    if v is None:
        return None
    if hasattr(v, "isoformat"):
        return v.isoformat()[:10]
    return str(v)


def member_slug(member_id):
    """Vote-slice file name for a roster id. MUST match build_member_votes_slices.member_slug()
    (test_mcp_index.py pins the two together)."""
    return re.sub(r"[^a-zA-Z0-9]+", "-", member_id).strip("-")


def absolute(path):
    if not path:
        return None
    return path if path.startswith("http") else SITE + path


# ---------------------------------------------------------------- vgIds

def vgid_lookup(crosswalk):
    """-> ({legisGaGovId(str): vgId}, {bioguideId: vgId}), forwards applied."""
    merged = (crosswalk.get("metadata") or {}).get("mergedVgIds") or {}

    def canon(v):
        return merged.get(v, v) if v else None

    by_gid, by_bio = {}, {}
    for p in crosswalk.get("people") or []:
        vg = canon(p.get("vgId"))
        if not vg:
            continue
        ids = p.get("ids") or {}
        if ids.get("legisGaGovId") is not None:
            by_gid.setdefault(str(ids["legisGaGovId"]), vg)
        if ids.get("bioguideId"):
            by_bio.setdefault(ids["bioguideId"], vg)
    return by_gid, by_bio


# ---------------------------------------------------------------- members

def ga_member_row(m, vg_by_gid, existing):
    gid = m.get("legisGaGovId")
    votes = f"ga-votes/{member_slug(m['id'])}.json"
    spons = f"ga-sponsorship/{gid}.json"
    status = blank(m.get("status"))
    return {
        "key": f"ga:{gid}",
        "vgId": vg_by_gid.get(str(gid)),
        "level": "state",
        "name": m.get("name"),
        "firstName": blank(m.get("firstName")),
        "lastName": blank(m.get("lastName")),
        "chamber": m.get("chamber"),
        "district": m.get("district"),
        "party": blank(m.get("party")),
        "status": status,
        "statusDate": iso(m.get("statusDate")),
        "serving": status not in DEPARTED_STATUSES,
        "leadershipRole": blank(m.get("leadershipRole")),
        "committees": m.get("committees") or [],
        "phone": blank(m.get("phone")),
        "email": blank(m.get("email")),
        "officialWebsiteUrl": blank(m.get("officialWebsiteUrl")),
        "votegaUrl": blank(m.get("votegaUrl")),
        "slices": {
            "votes": votes if votes in existing else None,
            "sponsorship": spons if spons in existing else None,
        },
    }


def federal_chamber(m):
    items = ((m.get("terms") or {}).get("item")) or []
    return items[-1].get("chamber") if items else None  # terms run oldest -> newest


def federal_member_row(m, vg_by_bio, entity_urls, existing):
    bio = m["bioguideId"]
    first, last = blank(m.get("firstName")), blank(m.get("lastName"))
    chamber = federal_chamber(m)
    votes = f"federal-votes/{bio}.json"
    spons = f"federal-sponsorship/{bio}.json"
    contact = m.get("contactInfo") or {}
    return {
        "key": f"us:{bio}",
        "vgId": vg_by_bio.get(bio),
        "level": "federal",
        "name": " ".join(x for x in (first, last) if x) or m.get("name"),
        "firstName": first,
        "lastName": last,
        "chamber": chamber,
        "district": m.get("district") if chamber == "House of Representatives" else None,
        "party": blank(m.get("partyName")),
        "status": None,
        "statusDate": None,
        "serving": True,
        "leadershipRole": None,
        "committees": [],
        "phone": blank(contact.get("phoneNumber")),
        "email": None,
        "officialWebsiteUrl": blank(m.get("officialWebsiteUrl")),
        "votegaUrl": absolute((entity_urls.get("us-congress") or {}).get(bio)),
        "slices": {
            "votes": votes if votes in existing else None,
            "sponsorship": spons if spons in existing else None,
        },
    }


def build_members(ga, federal, crosswalk, entity_urls, existing, generated_at, congress):
    """`existing` is the set of slice paths (relative to assets/data/) present on disk."""
    vg_by_gid, vg_by_bio = vgid_lookup(crosswalk)
    ga_rows = [ga_member_row(m, vg_by_gid, existing)
               for m in ga.get("members") or []
               if m.get("chamber") in ("Senate", "House of Representatives")
               and m.get("legisGaGovId") is not None]
    fed_rows = [federal_member_row(m, vg_by_bio, entity_urls, existing)
                for m in federal.get("members") or []
                if m.get("state") == GA_STATE and m.get("bioguideId")]
    rows = sorted(ga_rows, key=lambda r: (r["chamber"], r["district"] or 0, r["name"] or "")) + \
        sorted(fed_rows, key=lambda r: (r["chamber"] or "", r["district"] or 0, r["name"] or ""))
    gmeta = ga.get("metadata") or {}
    return {
        "metadata": {
            "generatedAt": generated_at,
            "count": len(rows),
            "state": {"count": len(ga_rows), "session": gmeta.get("session"),
                      "legisSessionId": gmeta.get("legisSessionId"),
                      "sourceGeneratedAt": gmeta.get("generatedAt")},
            "federal": {"count": len(fed_rows), "congress": congress,
                        "sourceGeneratedAt": (federal.get("metadata") or {}).get("generatedAt")},
            "keys": "ga:<legisGaGovId> for the General Assembly, us:<bioguideId> for Congress",
            "serving": "false for a member who resigned, was removed or died this term; their "
                       "page still exists. Suspended members still hold the seat (status says so).",
            "slices": "paths under https://www.votega.org/assets/data/; null when no slice exists",
        },
        "members": rows,
    }


# ---------------------------------------------------------------- former members

def build_former_members(ga, frozen, labels, crosswalk, existing, generated_at):
    """`frozen` = ga_former.load_frozen() ({tag: {gid: record}}), `labels` =
    ga-departure-labels.json, whose approved wording is copied for its own session only."""
    vg_by_gid, _ = vgid_lookup(crosswalk)
    label_tag = (labels.get("metadata") or {}).get("session")
    rows = []
    for rec, tag in former_records(ga.get("members") or [], frozen):
        if tag == "current" or rec.get("chamber") not in ("Senate", "House of Representatives"):
            continue
        gid = str(rec["legisGaGovId"])
        row = ga_member_row(rec, vg_by_gid, set())
        votes = f"ga-bienniums/{tag}/ga-votes/{member_slug(rec['id'])}.json"
        spons = f"ga-bienniums/{tag}/ga-sponsorship/{gid}.json"
        label = ((labels.get("labels") or {}).get(gid) or {}).get("label") if tag == label_tag else None
        row.update({
            "serving": False, "phone": None, "email": None, "officialWebsiteUrl": None,
            "slices": {"votes": votes if votes in existing else None,
                       "sponsorship": spons if spons in existing else None},
            "biennium": tag,
            "bienniums": sorted((t for t in frozen if gid in frozen[t]), reverse=True),
            "departure": blank(label) or departure_note(rec),
        })
        rows.append(row)
    return {"metadata": {"generatedAt": generated_at, "count": len(rows), "meaning": FORMER_MEANING},
            "members": rows}


# ---------------------------------------------------------------- ZIPs

def build_zip_shards(zipdoc, generated_at):
    """-> {zip3: shard document}."""
    meta = zipdoc.get("metadata") or {}
    shards = {}
    for z in sorted(zipdoc.get("zips") or {}):
        shards.setdefault(z[:3], {})[z] = zipdoc["zips"][z]
    return {
        p: {
            "metadata": {"generatedAt": generated_at, "prefix": p, "count": len(zips),
                         "hudRelease": meta.get("hudRelease"), "statePlans": meta.get("statePlans"),
                         "sourceGeneratedAt": meta.get("generatedAt"), "meaning": ZIP_MEANING},
            "zips": zips,
        }
        for p, zips in shards.items()
    }


# ---------------------------------------------------------------- counties

def build_counties(county_doc, generated_at):
    """`county_doc` is publish_ga_district_information.counties_doc(tracts), so the figures match
    the published ga-district-information county table by construction (spec §12.6)."""
    meta = county_doc.get("metadata") or {}
    return {
        "metadata": {"generatedAt": generated_at, "count": len(county_doc.get("counties") or {}),
                     "plans": meta.get("plans"), "censusVintage": meta.get("censusVintage"),
                     "sourceGeneratedAt": meta.get("generatedAt"), "meaning": COUNTY_MEANING},
        "counties": county_doc.get("counties") or {},
    }


# ---------------------------------------------------------------- local officials

def _letters(s):
    return re.sub(r"[^a-z]", "", (s or "").lower())


def county_fips_by_name(fips_by_slug):
    """GA_COUNTY_FIPS (slug -> fips) re-keyed on letters only, so 'DeKalb', 'Ben Hill' resolve."""
    return {_letters(k): v for k, v in fips_by_slug.items()}


def _member(m):
    return {
        "name": m.get("name"),
        "role": blank(m.get("role")),
        "title": blank(m.get("title")),
        "seat": blank(m.get("seat")),
        "seatId": blank(m.get("seat_id")),
        "party": blank(m.get("party")),
        "phone": blank(m.get("phone")),
        "email": blank(m.get("email")),
        "takesOffice": iso(m.get("takes_office")),
        "leavesOffice": iso(m.get("leaves_office")),
        "lastElected": m.get("last_elected"),
        "nextElection": m.get("next_election"),
        "status": blank(m.get("status")),
        "statusNote": blank(m.get("statusNote")),
        "source": blank(m.get("source")),
    }


def _not_history(m, today):
    """Keep the sitting board and staged incoming rows; drop rows whose hold already ended.
    `today` is an ISO date string; leaves_office is exclusive (lib/local_terms.py)."""
    end = iso(m.get("leaves_office"))
    return end is None or end > today


def build_local_officials(officials, officers, places, fips_by_slug, today, generated_at):
    """officials = _data/local_officials.yml, officers = _data/county_officers.yml,
    places = _data/places.yml (all parsed). `today` = 'YYYY-MM-DD' (the build date)."""
    place_by_slug = {p["slug"]: p for p in (places.get("places") or []) if p.get("slug")}
    by_name = county_fips_by_name(fips_by_slug)
    out = {}

    def entry(slug, name, kind, county_name):
        p = place_by_slug.get(slug) or {}
        fips = p.get("fips") or by_name.get(_letters(county_name))
        if not fips and p.get("parentCounty"):
            fips = (place_by_slug.get(p["parentCounty"]) or {}).get("fips")
        return out.setdefault(slug, {
            "slug": slug, "name": name, "type": kind, "countyFips": fips,
            "votegaUrl": f"{SITE}/local/{slug}/" if slug in place_by_slug and not p.get("hidden") else None,
            "body": None, "partisan": None, "officialUrl": None, "termYears": None,
            "members": [], "constitutionalOfficers": [],
        })

    for j in officials.get("jurisdictions") or []:
        e = entry(j["id"], j.get("name"), j.get("type"), j.get("county"))
        e.update({"body": blank(j.get("body")), "partisan": j.get("partisan"),
                  "officialUrl": blank(j.get("official_url")), "termYears": j.get("term_years")})
        e["members"] = [_member(m) for m in j.get("members") or []
                        if isinstance(m, dict) and _not_history(m, today)]

    for c in officers.get("counties") or []:
        p = place_by_slug.get(c["id"]) or {}
        e = entry(c["id"], c.get("name") or p.get("name"), p.get("type") or "county", c.get("name"))
        e["constitutionalOfficers"] = [_member(m) for m in c.get("officers") or []
                                       if isinstance(m, dict) and _not_history(m, today)]

    by_county = {}
    for slug in sorted(out):
        if out[slug]["countyFips"]:
            by_county.setdefault(out[slug]["countyFips"], []).append(slug)
    meta = officials.get("meta") or {}
    return {
        "metadata": {"generatedAt": generated_at, "asOf": today, "count": len(out),
                     "lastReviewed": iso(meta.get("last_reviewed")), "meaning": OFFICIALS_MEANING},
        "places": {s: out[s] for s in sorted(out)},
        "byCounty": by_county,
    }


# ---------------------------------------------------------------- local topic mentions

def build_local_mentions(topic_docs, places, fips_by_slug, generated_at):
    """`topic_docs` = the parsed local-topics-*.json files; topics are read from them. Excerpts
    and vote outcomes are not carried."""
    place_by_slug = {p["slug"]: p for p in (places.get("places") or []) if p.get("slug")}
    by_name = county_fips_by_name(fips_by_slug)
    topics, rows, seen_places = [], [], {}
    for doc in topic_docs:
        meta = doc.get("metadata") or {}
        slug = meta["topic"]
        mentions = doc.get("mentions") or []
        topics.append({"slug": slug, "label": blank(meta.get("label")), "count": len(mentions),
                       "generatedAt": meta.get("generatedAt"),
                       "votegaUrl": f"{SITE}/local/topics/{slug}/"})
        for m in mentions:
            pid = m["placeId"]
            if pid not in seen_places:
                p = place_by_slug.get(pid) or {}
                parent = place_by_slug.get(p.get("parentCounty")) or {}
                fips = (blank(m.get("fips")) or p.get("fips") or parent.get("fips")
                        or (by_name.get(_letters(pid)) if m.get("placeType") == "county" else None))
                seen_places[pid] = {
                    "name": m.get("placeName"), "type": m.get("placeType"), "countyFips": fips,
                    "votegaUrl": f"{SITE}/local/{pid}/" if p and not p.get("hidden") else None}
            row = {"place": pid, "topic": slug}
            for f in ("date", "body", "docType", "confidence", "sourceUrl", "minutesUrl"):
                row[f] = blank(m.get(f))
            for f in ("terms", "tags", "vendors"):
                row[f] = [x for x in m.get(f) or [] if blank(x)]
            rows.append(row)
    rows.sort(key=lambda r: (r["place"], r["topic"], r["sourceUrl"] or ""))
    rows.sort(key=lambda r: r["date"] or "", reverse=True)
    return {"metadata": {"generatedAt": generated_at, "count": len(rows),
                         "topics": sorted(topics, key=lambda t: t["slug"]),
                         "places": {k: seen_places[k] for k in sorted(seen_places)},
                         "meaning": MENTIONS_MEANING},
            "mentions": rows}


# ---------------------------------------------------------------- MCP resources (spec §8)

def _text(v):
    """Catalog strings may carry HTML entities (`&amp;`) for the Jekyll page; resources are plain
    text, so unescape and collapse whitespace. None stays None."""
    import html
    v = blank(v)
    if v is None:
        return None
    return re.sub(r"\s+", " ", html.unescape(str(v))).strip()


def site_url(path):
    """A site path from the catalog -> an absolute votega.org URL, kept exactly as written.
    Paths are not normalized: some pages are served only without a trailing slash
    (/open-data; /open-data/ is a 404) and others redirect to one, so guessing breaks links.
    Absolute URLs pass through."""
    if not path:
        return None
    if path.startswith("http"):
        return path
    return SITE + path


def build_resources(mcp, open_data, generated_at):
    """The votega:// resources. `mcp` = _data/mcp.yml, `open_data` = _data/open_data.yml (parsed).
    The /ai-assistants/ page renders the same mcp.yml, so the two cannot drift."""
    about = mcp.get("about") or {}
    datasets = []
    for d in open_data.get("datasets") or []:
        datasets.append({
            "id": d["id"],
            "title": _text(d.get("title")),
            "summary": _text(d.get("summary")),
            "source": _text(d.get("source")),
            "scope": _text(d.get("scope")),
            "cadence": _text(d.get("cadence")),
            "repo_url": blank(d.get("repo_url")),
            "docs_url": site_url(d.get("docs")),
            "files": [{"name": _text(f.get("name")), "description": _text(f.get("desc")),
                       "url": site_url(f.get("url"))} for f in d.get("files") or []],
        })
    return {
        "metadata": {"generatedAt": generated_at, "count": 3,
                     "sources": ["_data/mcp.yml", "_data/open_data.yml"]},
        "about": {
            "summary": _text(about.get("summary")),
            "principles": [_text(x) for x in about.get("principles") or []],
            "covers": [_text(x) for x in about.get("covers") or []],
            "not_yet": [_text(x) for x in about.get("not_yet") or []],
            "license": _text(about.get("license")),
            "corrections": _text(about.get("corrections")),
            "page_url": f"{SITE}/ai-assistants/",
        },
        "glossary": [{"term": _text(g["term"]), "definition": _text(g["definition"])}
                     for g in mcp.get("glossary") or []],
        "datasets": {
            "intro": _text((open_data.get("meta") or {}).get("intro")),
            "page_url": f"{SITE}/open-data",
            "license": "CC BY-SA 4.0",
            "datasets": datasets,
        },
    }


def resources_errors(doc, open_data_ids):
    errs = []
    about = doc.get("about") or {}
    for k in ("summary", "license", "corrections"):
        if not about.get(k):
            errs.append(f"resources.json: about.{k} is empty")
    for k in ("principles", "covers"):
        if not about.get(k):
            errs.append(f"resources.json: about.{k} is empty")
    terms = [g.get("term") for g in doc.get("glossary") or []]
    if not terms:
        errs.append("resources.json: glossary is empty")
    if len(terms) != len(set(terms)):
        errs.append("resources.json: glossary has a duplicate term")
    for g in doc.get("glossary") or []:
        if not g.get("term") or not g.get("definition"):
            errs.append(f"resources.json: glossary entry {g.get('term')!r} is incomplete")
    ids = [d["id"] for d in (doc.get("datasets") or {}).get("datasets") or []]
    if set(ids) != set(open_data_ids) or len(ids) != len(set(ids)):
        errs.append("resources.json: datasets do not match _data/open_data.yml")

    def walk(o, path):
        if isinstance(o, str):
            if re.search(r"&[a-z#0-9]+;|<[a-z/!][^>]*>", o):
                errs.append(f"resources.json: HTML at {path} (resources are plain text)")
        elif isinstance(o, dict):
            for k, v in o.items():
                walk(v, f"{path}.{k}")
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, f"{path}[{i}]")
    walk(doc, "$")
    return errs


# ---------------------------------------------------------------- vote file hashes

VOTE_FILES_MEANING = (
    "sha256 of every vote index and per-member vote slice under assets/data/. A slice names votes "
    "by their POSITION in its index, and positions move between builds, so a reader must use only "
    "an index and a slice that both match this list.")


def build_vote_files(hashes, generated_at):
    """`hashes` = {path under assets/data/: sha256 hex}."""
    return {"metadata": {"generatedAt": generated_at, "count": len(hashes), "meaning": VOTE_FILES_MEANING},
            "files": {k: hashes[k] for k in sorted(hashes)}}


def vote_file_errors(docs, src):
    doc = docs.get("vote-files.json")
    if doc is None:
        return ["vote-files.json is missing"]
    if doc["metadata"].get("count") != len(doc.get("files") or {}) or doc.get("files") != src["vote_hashes"]:
        return ["vote files differ from the files on disk (hashes or the list of files)"]
    return []


# ---------------------------------------------------------------- groups
# The core files are what the live tools read: any error there fails the whole index. Each other
# group stands alone: if it cannot be built or fails a check, only its files are dropped.

OPTIONAL_GROUPS = {
    "former-members": ("former-members-index.json",),
    "local-mentions": ("local-mentions-index.json",),
    "bills": ("bills/",),
    "elections": ("races-index.json", "candidates-index.json"),
    "vote-files": ("vote-files.json",),
}


def group_of(name):
    """An index file (or a SOURCES key) -> its group; anything not listed is "core"."""
    for group, names in OPTIONAL_GROUPS.items():
        if any(name == n or (n.endswith("/") and name.startswith(n)) for n in names):
            return group
    return "core"


def prune_meta(meta, failed):
    """meta.json without the failed groups. `failed` = {group: reason}."""
    out = dict(meta)
    out["files"] = {k: v for k, v in meta["files"].items() if group_of(k) not in failed}
    out["metadata"] = {**meta["metadata"], "count": len(out["files"])}
    out["sources"] = {k: v for k, v in (meta.get("sources") or {}).items() if group_of(k) not in failed}
    out["failedGroups"] = [{"group": g, "reason": failed[g]} for g in sorted(failed)]
    stamps = dict(meta.get("sourceStamps") or {})
    if "bills" in failed:
        stamps.pop("ga-bills", None)
        sessions = dict(out.get("sessions") or {})
        sessions["ga"] = {**(sessions.get("ga") or {}), "activeBillSession": None}
        out["sessions"] = sessions
    if "elections" in failed:
        stamps.pop("races", None)
    if "local-mentions" in failed:
        out["localTopics"] = []
    out["sourceStamps"] = stamps
    return out


# ---------------------------------------------------------------- checks (validate_mcp_index.py)

GZIP_BUDGET = 150_000  # bytes per index file (spec §5.1)
KEY_RE = re.compile(r"^(ga:\d+|us:[A-Z]\d{6})$")
VGID_RE = re.compile(r"^vg-ga-p-\d{6}$")
FIPS_RE = re.compile(r"^13\d{3}$")
MEMBER_FIELDS = ("key", "vgId", "level", "name", "firstName", "lastName", "chamber", "district",
                 "party", "status", "statusDate", "serving", "leadershipRole", "committees",
                 "phone", "email", "officialWebsiteUrl", "votegaUrl", "slices")


def _empty_strings(obj, path="$"):
    if isinstance(obj, str):
        return [path] if not obj.strip() else []
    if isinstance(obj, dict):
        return [p for k, v in obj.items() for p in _empty_strings(v, f"{path}.{k}")]
    if isinstance(obj, list):
        return [p for i, v in enumerate(obj) for p in _empty_strings(v, f"{path}[{i}]")]
    return []


def index_errors(docs, file_meta, src):
    """Every error from grouped_errors(), in one list."""
    return [e for errs in grouped_errors(docs, file_meta, src).values() for e in errs]


def grouped_errors(docs, file_meta, src):
    """{group: [errors]}, only for groups that have any. Tier-1 checks: the index contradicts itself or the files it was built from.

    docs       {name: parsed index document} for every file in the output except meta.json
    file_meta  {name: {bytes, gzipBytes, sha256}} computed from the bytes on disk, plus
               meta.json's own claims under the key "__claimed__"
    src        the inputs: ga, federal, zipdoc, county_fips (set), place_slugs (set),
               jurisdiction_ids (set), officer_ids (set), slices (set of existing paths),
               retired_vgids (set, the keys of id-crosswalk.json metadata.mergedVgIds),
               frozen (ga_former.load_frozen()), bill_docs (live ga-bills.json first, then
               frozen), races (races.json), topic_docs (local-topics-*.json), vote_hashes, and optionally
               load_errors ({group: reason}) for a group whose sources could not be read
    """
    out = {}

    def add(group, *found):
        if found:
            out.setdefault(group, []).extend(found)

    errs = []  # the core group's
    claimed = file_meta.get("__claimed__") or {}
    actual = {k: v for k, v in file_meta.items() if k != "__claimed__"}

    # meta.json describes exactly the files on disk, byte for byte
    for name in sorted(set(claimed) | set(actual)):
        group = group_of(name)
        if name not in actual:
            add(group, f"meta.json lists {name}, which is not on disk")
        elif name not in claimed:
            add(group, f"{name} is on disk but not in meta.json")
        else:
            for k in ("bytes", "sha256"):
                if claimed[name].get(k) != actual[name].get(k):
                    add(group, f"{name}: meta.json {k} does not match the file")
        if name in actual and actual[name]["gzipBytes"] > GZIP_BUDGET:
            add(group, f"{name}: {actual[name]['gzipBytes']} bytes gzipped, over the "
                       f"{GZIP_BUDGET} budget (shard it)")

    for name, doc in docs.items():
        meta = doc.get("metadata") or {}
        for p in _empty_strings(doc)[:5]:
            add(group_of(name), f"{name}: empty string at {p} (use null)")
        if name in claimed and claimed[name].get("count") != meta.get("count"):
            add(group_of(name), f"{name}: meta.json count differs from the file's own metadata.count")

    # members
    m = docs.get("members-index.json")
    if m is None:
        errs.append("members-index.json is missing")
    else:
        rows = m.get("members") or []
        if m["metadata"].get("count") != len(rows):
            errs.append("members-index.json: metadata.count != len(members)")
        seen = set()
        for r in rows:
            k = r.get("key")
            missing = [f for f in MEMBER_FIELDS if f not in r]
            if missing:
                errs.append(f"member {k}: missing fields {missing}")
            if not KEY_RE.match(k or ""):
                errs.append(f"member key {k!r} is not ga:<legisGaGovId> or us:<bioguideId>")
            if k in seen:
                errs.append(f"member key {k} appears twice")
            seen.add(k)
            if r.get("vgId") is not None and not VGID_RE.match(r["vgId"]):
                errs.append(f"member {k}: malformed vgId {r['vgId']!r}")
            if r.get("vgId") in src.get("retired_vgids", ()):
                errs.append(f"member {k}: carries retired vgId {r['vgId']} (follow mergedVgIds)")
            if not (r.get("votegaUrl") or "").startswith(SITE + "/"):
                errs.append(f"member {k}: votegaUrl {r.get('votegaUrl')!r} is not a votega.org page")
            for kind, path in (r.get("slices") or {}).items():
                if path is not None and path not in src["slices"]:
                    errs.append(f"member {k}: {kind} slice {path} does not exist")
            if r.get("serving") is False and r.get("status") not in DEPARTED_STATUSES:
                errs.append(f"member {k}: serving=false without a departed status")
        want_ga = {f"ga:{x['legisGaGovId']}" for x in src["ga"].get("members") or []
                   if x.get("chamber") in ("Senate", "House of Representatives")
                   and x.get("legisGaGovId") is not None}
        want_us = {f"us:{x['bioguideId']}" for x in src["federal"].get("members") or []
                   if x.get("state") == GA_STATE and x.get("bioguideId")}
        for label, want, level in (("GA roster", want_ga, "state"),
                                   ("GA delegation", want_us, "federal")):
            have = {r["key"] for r in rows if r.get("level") == level}
            if have != want:
                errs.append(f"members-index.json: {label} mismatch (missing {sorted(want - have)[:5]}, "
                            f"extra {sorted(have - want)[:5]})")

    # ZIP shards
    zips_src = set((src["zipdoc"].get("zips") or {}).keys())
    zips_have = set()
    for name, doc in docs.items():
        if not name.startswith("zip/"):
            continue
        prefix = name[len("zip/"):-len(".json")]
        z = doc.get("zips") or {}
        if doc["metadata"].get("count") != len(z):
            errs.append(f"{name}: metadata.count != number of ZIPs")
        bad = [x for x in z if x[:3] != prefix]
        if bad:
            errs.append(f"{name}: ZIPs filed under the wrong prefix: {bad[:5]}")
        dup = zips_have & set(z)
        if dup:
            errs.append(f"{name}: ZIPs also in another shard: {sorted(dup)[:5]}")
        zips_have |= set(z)
    if zips_have != zips_src:
        errs.append(f"ZIP shards do not match ga-zip-districts.json (missing "
                    f"{sorted(zips_src - zips_have)[:5]}, extra {sorted(zips_have - zips_src)[:5]})")

    # counties
    c = docs.get("counties-index.json")
    if c is None:
        errs.append("counties-index.json is missing")
    else:
        have = set((c.get("counties") or {}).keys())
        want = src["county_fips"]
        if have != want:
            errs.append(f"counties-index.json: counties differ from the GA FIPS codes (missing "
                        f"{sorted(want - have)[:5]}, extra {sorted(have - want)[:5]})")

    # local officials
    lo = docs.get("local-officials-index.json")
    if lo is None:
        errs.append("local-officials-index.json is missing")
    else:
        places = lo.get("places") or {}
        as_of = lo["metadata"].get("asOf")
        want = src["jurisdiction_ids"] | src["officer_ids"]
        if set(places) != want:
            errs.append(f"local-officials-index.json: places differ from the YAML (missing "
                        f"{sorted(want - set(places))[:5]}, extra {sorted(set(places) - want)[:5]})")
        for slug, p in places.items():
            if slug not in src["place_slugs"]:
                errs.append(f"local officials: {slug} is not a places.yml slug")
            fips = p.get("countyFips") or ""
            if not FIPS_RE.match(fips) or fips not in src["county_fips"]:
                errs.append(f"local officials: {slug} has no valid county FIPS ({p.get('countyFips')!r})")
            for row in (p.get("members") or []) + (p.get("constitutionalOfficers") or []):
                if row.get("leavesOffice") and as_of and row["leavesOffice"] <= as_of:
                    errs.append(f"local officials: {slug} {row.get('name')} left office "
                                f"{row['leavesOffice']} but is listed")
                if not row.get("source"):
                    errs.append(f"local officials: {slug} {row.get('name')} has no source")
        listed = {s for slugs in (lo.get("byCounty") or {}).values() for s in slugs}
        with_fips = {s for s, p in places.items() if p.get("countyFips")}
        if listed != with_fips:
            errs.append("local officials: byCounty does not list exactly the places with a county")

    # resources (votega://about, glossary, datasets)
    r = docs.get("resources.json")
    if r is None:
        errs.append("resources.json is missing")
    elif "open_data_ids" in src:
        errs += resources_errors(r, src["open_data_ids"])

    add("core", *errs)

    # imported here: those modules import this one's helpers
    from lib.mcp_bills import bill_errors
    from lib.mcp_elections import election_errors
    checks = {
        "former-members": lambda: former_errors(docs, src),
        "local-mentions": lambda: mention_errors(docs, src),
        "bills": lambda: bill_errors(docs, src["bill_docs"]),
        "elections": lambda: election_errors(docs, src["races"]),
        "vote-files": lambda: vote_file_errors(docs, src),
    }
    load_errors = src.get("load_errors") or {}
    for group, check in checks.items():
        if group in load_errors:
            add(group, f"{group}: not built or sources unreadable: {load_errors[group]}")
            continue
        try:
            add(group, *check())
        except Exception as e:  # a crashing check condemns its own group, not the index
            add(group, f"{group}: check crashed: {type(e).__name__}: {e}")
    return out


def former_errors(docs, src):
    doc = docs.get("former-members-index.json")
    if doc is None:
        return ["former-members-index.json is missing"]
    errs = []
    rows = doc.get("members") or []
    if doc["metadata"].get("count") != len(rows):
        errs.append("former-members-index.json: metadata.count != len(members)")
    live = {str(m.get("legisGaGovId")) for m in src["ga"].get("members") or []}
    want = {f"ga:{gid}" for recs in src["frozen"].values() for gid, m in recs.items()
            if gid not in live and m.get("chamber") in ("Senate", "House of Representatives")}
    have = [r.get("key") for r in rows]
    if len(have) != len(set(have)) or set(have) != want:
        errs.append(f"former members differ from the frozen bienniums (missing "
                    f"{sorted(want - set(have))[:5]}, extra {sorted(set(have) - want)[:5]})")
    for r in rows:
        k = r.get("key")
        if r.get("serving") is not False or any(r.get(f) for f in ("phone", "email", "officialWebsiteUrl")):
            errs.append(f"former member {k}: marked serving, or carries contact details")
        if r.get("vgId") is not None and r["vgId"] in src.get("retired_vgids", ()):
            errs.append(f"former member {k}: carries retired vgId {r['vgId']}")
        for kind, path in (r.get("slices") or {}).items():
            if path is not None and path not in src["slices"]:
                errs.append(f"former member {k}: {kind} slice {path} does not exist")
    return errs


def mention_errors(docs, src):
    doc = docs.get("local-mentions-index.json")
    if doc is None:
        return ["local-mentions-index.json is missing"]
    errs = []
    rows = doc.get("mentions") or []
    if doc["metadata"].get("count") != len(rows):
        errs.append("local-mentions-index.json: metadata.count != len(mentions)")
    want = {d["metadata"]["topic"]: len(d.get("mentions") or []) for d in src["topic_docs"]}
    have = {}
    for r in rows:
        have[r.get("topic")] = have.get(r.get("topic"), 0) + 1
    if have != {t: n for t, n in want.items() if n}:
        errs.append(f"local mentions differ from the topic files (have {have}, want {want})")
    if any(r.get("place") not in doc["metadata"].get("places", {}) for r in rows):
        errs.append("local-mentions-index.json: a mention names a place missing from metadata.places")
    return errs
