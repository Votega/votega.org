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
import html
import json
from lib.atomic_io import write_json_atomic
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
    """Return a page's last-modified date.

    - Content hash unchanged vs the prior deploy: keep the stored date.
    - Content changed vs a KNOWN prior: stamp today. The rendered output changed
      now, even when the change came from a code/template edit rather than fresh
      source data. Using data_date here (the date the *source* was produced) left
      lastmod in the past for copy/template changes, so the sitemap never advanced
      and indexnow_submit.py — which diffs on lastmod — never re-pinged those
      pages (that stranded the 2026-09 server-rendered-copy fix: pages were fixed
      but Bing kept its old "insufficient content" verdict because it was never
      told to re-crawl).
    - No prior record (new page, or a cache miss): fall back to data_date, which
      is deterministic from the inputs so a lost lastmod cache doesn't spuriously
      bump every page to today.
    """
    h = hashlib.sha1(
        json.dumps(fingerprint, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:16]
    prev = prior.get(permalink)
    if prev and prev.get("d"):
        d = prev["d"] if prev.get("h") == h else date.today().isoformat()
    else:
        d = data_date
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
    # Collapse newlines/tabs and drop control characters: scraped bios can carry
    # them, and a raw one makes the front matter unparseable for Jekyll.
    s = re.sub(r"[\x00-\x1f\x7f]+", " ", str(s)).strip()
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


# Compact office/chamber labels used ONLY in the SEO <title> tag (share-title),
# which head.html appends " | Vote GA" to. Bing flags titles over 70 characters,
# and the verbose forms below blow past that on every districted entity page. The
# full names stay in page.title (the H1) and in descriptions — this only trims the
# browser-tab/search-result title. Longest replacement wins, so order isn't load-
# bearing, but keep specific phrases (e.g. "of Representatives") intact.
_OFFICE_ABBREV = (
    ("Georgia House of Representatives", "GA House"),
    ("U.S. House of Representatives", "U.S. House"),
    ("Georgia State Senate", "GA Senate"),
    ("Insurance & Fire Safety Commissioner", "Insurance Commissioner"),
    ("Public Service Commissioner", "PSC"),
    ("State School Superintendent", "School Superintendent"),
    ("Commissioner of Agriculture", "Agriculture Commissioner"),
    ("Secretary of Health and Human Services", "HHS Secretary"),
    ("Director of the Office of Management and Budget", "OMB Director"),
    ("Supreme Court of Georgia", "GA Supreme Court"),
    ("Georgia Court of Appeals", "GA Court of Appeals"),
    ("District Attorney", "DA"),
    ("Judicial Circuit", "Circuit"),
)


def abbrev_office(s):
    """Shorten verbose office/chamber names for the SEO <title> only (see above)."""
    if not s:
        return s
    for long, short in _OFFICE_ABBREV:
        s = s.replace(long, short)
    return s


# ─────────────────────── Server-rendered "about" copy ───────────────────────
# Bing Webmaster flags pages with too few words. Candidate / race / legislator
# pages hydrate their real content client-side, so the crawlable HTML was a
# one-line stub. These helpers build a few factual paragraphs from the same
# data (no invented claims) and hand them to the include as entity.about; the
# JS profile still overwrites the container for human visitors.

def _fmt_date(iso):
    try:
        d = datetime.fromisoformat(str(iso)[:10]).date()
        return f"{d.strftime('%B')} {d.day}, {d.year}"
    except (ValueError, TypeError):
        return None


def _office_blurb(race):
    ch = (race.get("chamber") or "").lower()
    if ch == "georgia house of representatives":
        return ("The Georgia House of Representatives has 180 members, each elected "
                "from a single district to a two-year term. Representatives vote on "
                "state laws, the annual state budget, and how tax dollars are spent.")
    if ch == "georgia state senate":
        return ("The Georgia State Senate has 56 members, each elected from a single "
                "district to a two-year term. Senators vote on state laws and the "
                "state budget, and confirm certain appointments.")
    if ch == "superior court":
        return ("Superior Court judges hear felony criminal cases, major civil disputes, "
                "and land title cases in Georgia's judicial circuits. Judges are elected "
                "in nonpartisan elections to four-year terms.")
    if ch == "district attorney":
        return ("A District Attorney prosecutes felony cases on behalf of the state "
                "within a judicial circuit and is elected to a four-year term.")
    if ch == "u.s. house":
        return ("Georgia sends 14 members to the U.S. House of Representatives. "
                "Members serve two-year terms and vote on federal legislation and spending.")
    if ch == "u.s. senate":
        return ("Georgia's two U.S. senators serve six-year terms and vote on federal "
                "legislation, treaties, and confirmations of judges and cabinet officials.")
    if ch in ("georgia court of appeals", "supreme court of georgia"):
        return ("Georgia appellate judges and justices are elected statewide in "
                "nonpartisan elections and review decisions made by lower courts.")
    if (race.get("level") or "") == "state-executive":
        return ("This is a statewide executive office, so every Georgia voter "
                "can vote in this race regardless of where in the state they live.")
    return ""


def _race_active_candidates(race):
    """(phase_key, candidates) for the race's active phase (else the latest with candidates)."""
    phases = {k: v for k, v in (race.get("phases") or {}).items() if isinstance(v, dict)}
    order = [race.get("activePhase")] + ["general", "runoff", "primary"]
    for key in order:
        ph = phases.get(key)
        if not ph:
            continue
        out, seen = [], set()
        groups = list((ph.get("ballots") or {}).values()) + [ph.get("candidates") or []]
        for g in groups:
            for c in (g or []):
                cn = (c.get("name") or "").strip()
                k = c.get("id") or cn
                if cn and k not in seen and not c.get("withdrawn") and not c.get("disqualified"):
                    seen.add(k)
                    out.append(c)
        if out:
            return key, out
    return None, []


def _party_txt(c):
    p = (c.get("party") or "").strip()
    return "nonpartisan" if p.lower() in ("non-partisan", "nonpartisan") else p


def _cand_phrase(c):
    tags = [t for t in (_party_txt(c), "incumbent" if c.get("isIncumbent") else "") if t]
    txt = c["name"].strip() + (f" ({', '.join(tags)})" if tags else "")
    bits = []
    if c.get("occupation"):
        bits.append(c["occupation"].strip().lower() if c["occupation"].isupper() else c["occupation"].strip())
    if c.get("county"):
        bits.append(f"{c['county'].strip()} County")
    return txt + (f", {', '.join(bits)}" if bits else "")


def _election_dates_txt(race):
    ph = race.get("phases") or {}
    bits = []
    for key, label in (("primary", "primary"), ("runoff", "runoff"), ("general", "general election")):
        d = _fmt_date((ph.get(key) or {}).get("electionDate")) if isinstance(ph.get(key), dict) else None
        if d:
            bits.append(f"the {label} on {d}")
    return bits


_VOTE_HOWTO = ("To vote in Georgia, you must be registered by the state's registration deadline "
               "ahead of each election. You can check your registration, find your polling place, "
               "and see your personal sample ballot on the Georgia Secretary of State's My Voter "
               "Page (mvp.sos.ga.gov), or vote early in person or by absentee ballot.")


def race_about(name, race):
    paras = []
    seat = race.get("displayTitle") or name
    # The manifest-derived name has the cycle baked in (e.g. "Labor Commissioner
    # 2026"), so the sentence below would read "…2026 race on Georgia's 2026
    # ballot". Strip a trailing cycle year from the seat for the prose only; the
    # page <title> still carries the year. displayTitles never end in the cycle,
    # so clean labels (legislative seats) are untouched.
    cycle = str(race.get("cycle") or "").strip()
    if cycle and seat.endswith(cycle):
        seat = seat[: -len(cycle)].rstrip(" -–—")
    paras.append(f"This page covers the {seat} race on Georgia's {cycle} ballot. "
                 "Georgia voters choose who fills this office in the elections listed below, and "
                 "the candidate list is updated as the Georgia Secretary of State and campaigns "
                 "publish new information.")
    dates = _election_dates_txt(race)
    if dates:
        paras.append("Key dates for this race: " + "; ".join(dates) + ". Early voting runs "
                     "before each election, and voters can confirm their registration and "
                     "polling place on the Georgia Secretary of State's My Voter Page.")
    key, cands = _race_active_candidates(race)
    if cands:
        label = {"general": "general election", "runoff": "runoff", "primary": "primary"}.get(key, "ballot")
        paras.append(f"Candidates on the {label} ballot: " + "; ".join(_cand_phrase(c) for c in cands) + ".")
    blurb = _office_blurb(race)
    if blurb:
        paras.append(blurb)
    paras.append(_VOTE_HOWTO)
    return paras


def candidate_about(name, race, cand, race_label):
    paras = []
    party = _party_txt(cand)
    seat = race_label or "office"
    role = "the incumbent" if cand.get("isIncumbent") else "a candidate"
    art = "an" if party[:1].upper() in "AEIOU" else "a"
    paras.append(f"{name} is {role} for {seat} in Georgia's {race.get('cycle') or ''} elections"
                 f"{', running as ' + art + ' ' + party + ' candidate' if party and party != 'nonpartisan' else ''}"
                 f"{', on the nonpartisan ballot' if party == 'nonpartisan' else ''}.")
    facts = []
    if cand.get("occupation"):
        facts.append(f"Listed occupation: {cand['occupation'].strip()}")
    if cand.get("county"):
        facts.append(f"County of residence: {cand['county'].strip()}")
    if facts:
        paras.append("; ".join(facts) + ". This information comes from the candidate's "
                     "qualifying paperwork with the Georgia Secretary of State.")
    bio = (cand.get("bio") or "").strip()
    if bio:
        paras.append(bio)
    dates = _election_dates_txt(race)
    if dates:
        paras.append("Election dates for this race: " + "; ".join(dates) + ".")
    others = [c for c in _race_active_candidates(race)[1] if (c.get("id") or c["name"]) != (cand.get("id") or name)]
    if others:
        paras.append("Also on the ballot in this race: " + "; ".join(_cand_phrase(c) for c in others) + ".")
    blurb = _office_blurb(race)
    if blurb:
        paras.append(blurb)
    paras.append(_VOTE_HOWTO)
    return paras


def ga_legislator_about(name, role, m, is_senate):
    chamber = "State Senate" if is_senate else "House of Representatives"
    party = (m.get("party") or "").strip()
    d = m.get("district")
    paras = [f"{name} is a{'n' if party[:1].upper() in 'AEIOU' and party else ''} "
             f"{party + ' ' if party else ''}member of the Georgia {chamber}"
             f"{', representing District ' + str(d) if d else ''}."
             + (f" {name} has served in the General Assembly since {m['termStartYear']}." if m.get("termStartYear") else "")]
    comms = [c for c in (m.get("committees") or []) if c]
    if comms:
        paras.append(f"Committee assignments: {', '.join(comms)}. Committees review bills in their "
                     "subject area before those bills reach a vote of the full chamber.")
    if m.get("address"):
        paras.append(f"Capitol office: {m['address'].strip()}.")
    paras.append(("The Georgia State Senate has 56 members" if is_senate else
                  "The Georgia House of Representatives has 180 members")
                 + ", each elected from a single district to a two-year term. This profile also "
                 "shows voting record, party-line loyalty, campaign finance, and contact "
                 "information once the interactive profile loads.")
    paras.append("Not sure who represents you? Use VoteGA's Find My Representatives tool to look up "
                 "your U.S. Congress members and your Georgia House and Senate districts by address.")
    return paras


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


def _nth_weekday(year, month, weekday, n):
    """Date of the nth `weekday` (Mon=0…Sun=6) in month; e.g. 2nd Sunday of March."""
    first = date(year, month, 1)
    return date(year, month, 1 + (weekday - first.weekday()) % 7 + (n - 1) * 7)


def _eastern_offset(d):
    """UTC offset for America/New_York on date d, per US DST rules (2007+): EDT
    (-04:00) from the 2nd Sunday of March to the 1st Sunday of November, else EST
    (-05:00). Computed locally so the build needs no tzdata dependency."""
    dst_start = _nth_weekday(d.year, 3, 6, 2)   # 2nd Sunday of March
    dst_end = _nth_weekday(d.year, 11, 6, 1)    # 1st Sunday of November
    return "-04:00" if dst_start <= d < dst_end else "-05:00"


def _parse_clock(when):
    """Pull a HH:MM:SS 24-hour time from a free-text schedule string like
    "1st Tuesday of every month, 5:30 p.m." Returns None when no time is present."""
    if not when:
        return None
    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*([ap])\.?\s*m\.?", when, re.I)
    if not m:
        return None
    hour = int(m.group(1)) % 12
    if m.group(3).lower() == "p":
        hour += 12
    return f"{hour:02d}:{int(m.group(2) or 0):02d}:00"


def build_meeting_events(place, slug, name, permalink, org_id, limit=10):
    """Server-rendered schema.org Event JSON-LD for a place's *upcoming* meetings.

    Joins concrete dates from the meetings sidecar
    (assets/data/local-<slug>-meetings.json, otherwise loaded client-side) with the
    time + location from the curated per-body schedule in _data/places.yml, matched
    on the meeting body. Emits only future-dated meetings (Google favors upcoming
    events and a long tail of past ones adds no value). Returns (jsonld_str,
    fingerprint_list); both empty when there is nothing upcoming.
    """
    path = os.path.join(SRC_DIR, f"local-{slug}-meetings.json")
    if not os.path.exists(path):
        return "", []
    try:
        with open(path, encoding="utf-8") as fh:
            meetings = (json.load(fh) or {}).get("meetings", []) or []
    except (ValueError, OSError):
        return "", []

    # Per-body schedule lookup (exact, then case-insensitive) → {when, location}.
    sched = ((place.get("domains") or {}).get("meetings") or {}).get("schedule") or []
    by_body = {s.get("body"): s for s in sched if isinstance(s, dict) and s.get("body")}
    by_body_lc = {b.lower(): s for b, s in by_body.items()}

    today = date.today().isoformat()
    upcoming = sorted(
        (m for m in meetings if isinstance(m, dict) and (m.get("date") or "") >= today),
        key=lambda m: m["date"],
    )[:limit]

    events, fp = [], []
    for m in upcoming:
        d = _date_only(m["date"])
        body = m.get("body") or ""
        title = m.get("title") or "Meeting"
        s = by_body.get(body) or by_body_lc.get(body.lower()) or {}
        clock = _parse_clock(s.get("when"))
        try:
            start = f"{d}T{clock}{_eastern_offset(date.fromisoformat(d))}" if clock else d
        except ValueError:
            start = d

        # Build a non-redundant name: some titles already restate the body/place
        # (e.g. "Banks County Board of Commissioners Meeting"), others are generic
        # ("Regular Meeting"). Join only when neither string contains the other.
        base = f"{name} {body}".strip()
        t = title.strip()
        if t and t.lower() not in base.lower() and base.lower() not in t.lower():
            label = f"{base} — {t}"
        else:
            label = t if len(t) >= len(base) else base

        cancelled = "cancel" in title.lower()
        ev = {
            "@context": "https://schema.org",
            "@type": "Event",
            "name": label,
            "startDate": start,
            "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
            "eventStatus": ("https://schema.org/EventCancelled" if cancelled
                            else "https://schema.org/EventScheduled"),
            "organizer": {"@id": org_id},
            "url": SITE_URL + permalink,
        }
        loc = (s.get("location") or "").strip()
        if loc:
            ev["location"] = {"@type": "Place", "name": loc, "address": loc}
        agenda = m.get("agendaUrl")
        if agenda:
            ev["subjectOf"] = {"@type": "CreativeWork", "name": "Agenda", "url": agenda}
        events.append(ev)
        fp.append(f"{start}|{ev['name']}")

    if not events:
        return "", []
    return "\n".join(json_ld(e) for e in events), fp


# ─────────────────────────── GA Legislators ───────────────────────────

def _ga_general_election_date(year):
    """Date of the November general election in `year`: the first Tuesday
    after the first Monday of November (GA follows the federal rule)."""
    d = date(year, 11, 1)
    while d.weekday() != 0:            # advance to the first Monday (Mon == 0)
        d = date(year, 11, d.day + 1)
    return date(year, 11, d.day + 1)   # the Tuesday immediately after


def ga_next_general_election(today=None):
    """Year of the next Georgia General Assembly general election.

    Both chambers of the GA General Assembly serve two-year terms, so every
    House and Senate seat is on the ballot at the November general election of
    each even-numbered year. The *year* is derived from the current date rather
    than hardcoded, so this never needs a per-cycle edit (cycle-agnostic rule).
    """
    today = today or date.today()
    y = today.year
    if y % 2 == 1:                     # odd year → next even year
        return y + 1
    # Even year: this cycle if the general hasn't happened yet, else the next.
    return y if today <= _ga_general_election_date(y) else y + 2


# Statuses for which a member still holds the seat and is on the next ballot.
_GA_ACTIVE_STATUSES = (None, "", "Suspended", "Vacant")


# ─────────────────────────── Directory / browse index pages ───────────────────────────
# WHY: every entity page was reachable only via sitemap.xml — the finder/hub pages
# build their lists client-side, so Googlebot saw no internal <a href> to any of the
# ~1,400 profiles. GSC reported them all as "Discovered – currently not indexed"
# (Referring page: None detected, Last crawl: N/A). These server-rendered directory
# pages give every profile a real inbound link, and are themselves linked site-wide
# from the footer sitemap, turning sitemap-only orphans into a crawlable graph.
#
# Each builder appends one record here as it already computes name/permalink/group,
# so the directory never drifts from the pages it lists. build_directory_pages()
# consumes it after all builders run.
_DIRECTORY = []


def _dir_add(section, group, group_order, sort_key, name, url, group_url=None):
    _DIRECTORY.append({"section": section, "group": group, "group_order": group_order,
                       "sort": sort_key, "name": name, "url": url, "group_url": group_url})


def _race_category(chamber):
    """(section-heading label, order) bucket for a race/candidate's office."""
    cl = (chamber or "").strip().lower()
    if cl in ("u.s. senate", "u.s. house"):
        return ("U.S. Congress", 1)
    if cl == "georgia state senate":
        return ("Georgia State Senate", 2)
    if cl == "georgia house of representatives":
        return ("Georgia House of Representatives", 3)
    if "court" in cl:  # Supreme Court of Georgia, Court of Appeals, Superior Court
        return ("Judicial", 4)
    if cl == "district attorney":
        return ("District Attorney", 5)
    if any(x in cl for x in ("governor", "lieutenant", "attorney general", "commissioner",
                             "secretary of state", "superintendent")):
        return ("Statewide Executive", 0)
    return ("Other Races", 6)


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
        _dir_add("legislators",
                 "Georgia State Senate" if is_senate else "Georgia House of Representatives",
                 0 if is_senate else 1, (district if isinstance(district, int) else 9999, name),
                 (f"District {district} — {name}" if district else name), permalink)

        dist_txt = f", District {district}" if district else ""
        # <title> uses the compact "GA House/Senate District N" form to stay under
        # 70 chars; the full "Georgia State Representative, District N" lives in the
        # description below and the page H1.
        share_title = (f"{name} — GA {'Senate' if is_senate else 'House'} District {district}"
                       if district else f"{name} — Georgia {role}")
        desc = (f"{rec.get('desc') or (role + dist_txt)}. Voting record, party-line "
                f"loyalty, committee assignments, campaign finance, and contact "
                f"information for {name}.")

        # High-value, stable facts baked into the page for crawlers / no-JS
        # readers (the JS profile still overwrites #memberDetails for humans).
        committees = [c for c in (m.get("committees") or []) if c]
        phone = m.get("phone") or None
        website = m.get("officialWebsiteUrl") or None
        status = m.get("status")
        next_election = (ga_next_general_election()
                         if status in _GA_ACTIVE_STATUSES else None)

        org = "Georgia State Senate" if is_senate else "Georgia House of Representatives"
        person = {
            "@context": "https://schema.org", "@type": "Person", "name": name,
            "jobTitle": role, "url": SITE_URL + permalink,
            "memberOf": {"@type": "GovernmentOrganization", "name": org,
                         "url": SITE_URL + "/ga-state-reps"},
            "affiliation": party or None,
        }
        if phone:
            person["telephone"] = phone
        ld = json_ld(person)

        entity = {"type": "ga-legislator", "id": mid, "name": name,
                  "title": role_short, "chamber": chamber, "district": district,
                  "party": party, "committees": committees, "phone": phone,
                  "website": website, "nextElection": next_election,
                  "about": ga_legislator_about(name, role, m, is_senate)}
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
        _dir_add("congress", "U.S. Senate" if is_senate else "U.S. House",
                 0 if is_senate else 1, (district if isinstance(district, int) else 0, name),
                 (f"{name} — District {district}" if district and not is_senate else name),
                 permalink)

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
        _rcat, _rorder = _race_category(chamber)
        _dir_add("races", _rcat, _rorder, name, name, permalink)

        share_title = f"{abbrev_office(name)} — Candidates & Results"
        desc = (f"Candidates, the incumbent, district information, and results for the "
                f"{name} race in Georgia.")
        # Candidates in this race, across phases, deduped by id/name — for an
        # ItemList of Person so search engines read the page as "who is running
        # for <office>". We link each Person to their own website (sameAs) when
        # present, not to a /candidates/ page: that URL map is built by the later
        # Candidate pass, and not every named candidate gets a page.
        cands, seen_c = [], set()
        for phase in (r.get("phases") or {}).values():
            if not isinstance(phase, dict):
                continue
            groups = list((phase.get("ballots") or {}).values()) + [phase.get("candidates") or []]
            for group in groups:
                for c in (group or []):
                    cn = (c.get("name") or "").strip()
                    key = c.get("id") or cn
                    if not cn or key in seen_c:
                        continue
                    seen_c.add(key)
                    cands.append(c)

        il = ""
        if cands:
            items = []
            for i, c in enumerate(cands, start=1):
                person = {"@type": "Person", "name": c["name"].strip()}
                party = (c.get("party") or "").strip()
                if party:
                    person["affiliation"] = party
                site = (c.get("website") or "").strip()
                if site.startswith("http"):
                    person["sameAs"] = site
                items.append({"@type": "ListItem", "position": i, "item": person})
            il = json_ld({
                "@context": "https://schema.org", "@type": "ItemList",
                "name": f"Candidates for {name}",
                "numberOfItems": len(items),
                "itemListElement": items,
            })

        entity = {"type": "race", "id": rid, "name": name, "chamber": chamber,
                  "cycle": cycle, "summary": (level.title() + " race") if level else None,
                  "about": race_about(name, r)}
        lastmod = resolve_lastmod(
            permalink,
            {"e": entity, "t": share_title, "d": desc, "c": [c["name"] for c in cands]},
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
                + (f"{il}\n" if il else "")
                + "{% include entity/race.html %}")
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
        _ccat_order = _race_category(race.get("chamber"))[1]
        _dir_add("candidates", race_label, (_ccat_order, race_label), name, name, permalink,
                 group_url=race_url)
        # Party from the structured candidate object; fall back to the desc prefix
        # ("Republican — U.S. Senate 2026"). The old "·" split never matched (the
        # separator is an em dash), so affiliation had silently been null.
        cand_obj = (cand_index.get(cid) or ({}, None))[0] or {}
        party = (cand_obj.get("party") or "").strip()
        if not party and "—" in desc:
            party = desc.split("—")[0].strip()

        # Compact office label + "Candidate," (not "Candidate for") keeps the
        # <title> under 70 chars; the full race_label stays in jobTitle/description.
        share_title = f"{name} — Candidate, {abbrev_office(race_label)}".strip()
        page_desc = desc or f"Candidate profile for {name}."
        person = {
            "@context": "https://schema.org", "@type": "Person", "name": name,
            "url": SITE_URL + permalink,
            "description": desc or None,
        }
        if race_label:  # office sought — the candidacy context
            person["jobTitle"] = f"Candidate for {race_label}"
        if party:       # typed party (schema.org affiliation expects an Organization)
            person["affiliation"] = {"@type": "PoliticalParty", "name": party}
        ld = json_ld(person)
        entity = {"type": "candidate", "id": cid, "name": name,
                  "about": candidate_about(name, race, cand_obj, race_label)}
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
        _dir_add("executive", "Federal Executive Branch", 0, name, name, permalink)

        share_title = f"{name} — {abbrev_office(role)}" if role else name
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
        _dir_add("judges", "U.S. Supreme Court", 0, name, name, permalink)

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
    """Best public URL to link when data is missing, per meetings platform.

    Prefer an explicit agendas_url (the county's agenda/minutes hub); else derive
    from base_url (CivicPlus exposes its hub at /AgendaCenter)."""
    cfg = ((place.get("domains") or {}).get("meetings")) or {}
    agendas = (cfg.get("agendas_url") or "").strip()
    if agendas:
        return agendas
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
        if p.get("hidden"):
            continue  # kept in the registry, but no /local/<slug>/ page is emitted
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
        share_title = f"{name}, Georgia — Local Government"
        if has_officials:
            desc = (f"Elected officials, plus public meeting agendas and minutes, for "
                    f"{name}, Georgia — who represents you locally, their seats, terms, "
                    f"and next elections, with meetings aggregated from the "
                    f"{'city' if ptype == 'city' else 'county'}'s official site.")
        else:
            desc = (f"Public meeting agendas, minutes, and video for {name}, Georgia. "
                    f"Board and commission meetings aggregated from the "
                    f"{'city' if ptype == 'city' else 'county'}'s official Agenda Center.")

        org_id = SITE_URL + permalink + "#organization"
        ld = json_ld({
            "@context": "https://schema.org", "@type": "GovernmentOrganization",
            "@id": org_id,
            "name": name, "url": SITE_URL + permalink,
            "areaServed": {"@type": "AdministrativeArea", "name": name},
            "containedInPlace": {"@type": "State", "name": "Georgia"},
        })
        bc = breadcrumb_ld([("Home", "/"), ("Local Government", "/local/"), (name, None)])
        events_ld, events_fp = build_meeting_events(p, slug, name, permalink, org_id)

        entity = {
            "type": "place", "slug": slug, "placeType": ptype, "name": name,
            "parentCountySlug": (parent or {}).get("slug"),
            "parentCountyName": (parent or {}).get("name"),
            "domains": domains,  # lets place.html branch server-side (officials/meetings)
        }
        lastmod = resolve_lastmod(
            permalink,
            {"e": entity, "t": share_title, "d": desc, "dom": domains, "ev": events_fp},
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
        head = f"<script>window.VOTEGA_PLACE = {json.dumps(place_js)};</script>\n{ld}\n{bc}\n"
        if events_ld:
            head += f"{events_ld}\n"
        body = head + "{% include entity/place.html %}"
        write_page("local", slug, fm, body)
        count += 1
    return count


_DIRECTORY_CSS = (
    "<style>\n"
    "  .dir-lede { font-size: 1.05rem; color: #444; line-height: 1.6; max-width: 46rem; margin: 0 0 1.5rem; }\n"
    "  .dir-group { font-size: 1.1rem; color: #1a2733; margin: 1.6rem 0 0.4rem; border-bottom: 1px solid #eee; padding-bottom: 0.25rem; }\n"
    "  .dir-group a { color: #1a56a8; }\n"
    "  .dir-count { font-size: 0.8rem; font-weight: 600; color: #8894a8; }\n"
    "  .dir-list { list-style: none; padding: 0; margin: 0.4rem 0 0; columns: 3 14rem; column-gap: 1.5rem; }\n"
    "  .dir-list li { margin: 0 0 0.3rem; break-inside: avoid; line-height: 1.4; }\n"
    "  .dir-list a { color: #1a56a8; text-decoration: none; }\n"
    "  .dir-list a:hover { text-decoration: underline; }\n"
    "  .dir-hub { list-style: none; padding: 0; margin: 0; display: grid; gap: 0.6rem; max-width: 34rem; }\n"
    "  .dir-hub li { font-size: 1.1rem; }\n"
    "</style>"
)

# (section-key, url-slug, <h1>/title, lede paragraph) — order = order on the hub page.
_DIR_SECTIONS = [
    ("candidates", "candidates", "All 2026 Georgia Candidates",
     "Every candidate on Georgia's 2026 ballot with a VoteGA profile, grouped by the office they are running for. Each race heading links to that race's full page."),
    ("races", "races", "All 2026 Georgia Races",
     "Every race on Georgia's 2026 ballot — federal, statewide executive, state legislative, judicial, and district attorney."),
    ("legislators", "legislators", "All Georgia Legislators",
     "Every current member of the Georgia General Assembly, by chamber and district."),
    ("congress", "congress", "Georgia's Members of U.S. Congress",
     "Georgia's delegation to the U.S. House and Senate."),
    ("executive", "executive", "Federal Executive Officials",
     "Officials of the U.S. federal executive branch profiled on VoteGA."),
    ("judges", "judges", "U.S. Supreme Court Justices",
     "The justices of the Supreme Court of the United States."),
]


def _dir_section_page(section, slug, title, lede, rows, prior, new_state):
    """Render one directory section into a grouped list of entity links."""
    groups = {}
    for r in rows:
        groups.setdefault((r["group_order"], r["group"], r.get("group_url")), []).append(r)
    parts = [f'<p class="dir-lede">{html.escape(lede)}</p>']
    fp = []
    for key in sorted(groups, key=lambda k: (k[0], str(k[1]))):
        _order, gname, gurl = key
        items = sorted(groups[key], key=lambda r: r["sort"])
        heading = f'<a href="{gurl}">{html.escape(gname)}</a>' if gurl else html.escape(gname)
        parts.append(f'<h2 class="dir-group">{heading} <span class="dir-count">{len(items)}</span></h2>')
        parts.append('<ul class="dir-list">')
        for it in items:
            parts.append(f'<li><a href="{it["url"]}">{html.escape(it["name"])}</a></li>')
            fp.append(it["url"])
        parts.append('</ul>')
    permalink = f"/directory/{slug}/"
    lastmod = resolve_lastmod(permalink, {"items": fp}, date.today().isoformat(), prior, new_state)
    fm = {
        "layout": "default",
        "title": yaml_quote(title),
        "share-title": yaml_quote(f"{title} — VoteGA"),
        "share-description": yaml_quote(lede),
        "permalink": permalink,
        "last_modified_at": lastmod,
    }
    bc = breadcrumb_ld([("Home", "/"), ("Directory", "/directory/"), (title, None)])
    body = f"{bc}\n{_DIRECTORY_CSS}\n" + "\n".join(parts)
    write_page("directory", slug, fm, body)


def build_directory_pages(prior, new_state):
    """Server-rendered browse/index pages that link every entity profile, plus a hub
    at /directory/. Consumes the records each builder appended to _DIRECTORY."""
    by_section = {}
    for rec in _DIRECTORY:
        by_section.setdefault(rec["section"], []).append(rec)

    hub = []
    for section, slug, title, lede in _DIR_SECTIONS:
        rows = by_section.get(section) or []
        if not rows:
            continue
        _dir_section_page(section, slug, title, lede, rows, prior, new_state)
        hub.append((title, f"/directory/{slug}/", len(rows)))

    if not hub:
        return 0

    parts = ['<p class="dir-lede">Browse every person and race profiled on VoteGA. '
             'These pages link to each profile so readers &mdash; and search engines &mdash; can reach them all.</p>',
             '<ul class="dir-hub">']
    for title, url, n in hub:
        parts.append(f'<li><a href="{url}">{html.escape(title)}</a> <span class="dir-count">{n}</span></li>')
    parts.append('</ul>')
    lastmod = resolve_lastmod("/directory/", {"hub": [u for _t, u, _n in hub]},
                              date.today().isoformat(), prior, new_state)
    fm = {
        "layout": "default",
        "title": yaml_quote("Site Directory"),
        "share-title": yaml_quote("Site Directory — VoteGA"),
        "share-description": yaml_quote("Browse every candidate, race, legislator, and official profiled on VoteGA."),
        "permalink": "/directory/",
        "last_modified_at": lastmod,
    }
    bc = breadcrumb_ld([("Home", "/"), ("Directory", None)])
    body = f"{bc}\n{_DIRECTORY_CSS}\n" + "\n".join(parts)
    write_page("directory", "index", fm, body)
    return len(hub) + 1


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
    _DIRECTORY[:] = []  # reset the cross-builder directory accumulator
    for label, builder in CATEGORY_BUILDERS:
        try:
            n = builder(records, urls, prior, new_state)
        except Exception as exc:
            print(f"  {label}: FAILED — {exc}", file=sys.stderr)
            continue
        print(f"  {label}: {n} pages")
        total += n
    try:
        n = build_directory_pages(prior, new_state)
        print(f"  Directory: {n} pages")
        total += n
    except Exception as exc:
        print(f"  Directory: FAILED — {exc}", file=sys.stderr)
    write_json_atomic(ENTITY_URLS_PATH, urls, separators=(",", ":"))
    write_json_atomic(LASTMOD_STATE_PATH, new_state, separators=(",", ":"))
    changed = sum(1 for k, v in new_state.items() if prior.get(k, {}).get("h") != v["h"])
    print(f"build_entity_pages: {total} pages, {sum(len(v) for v in urls.values())} URL mappings, "
          f"{changed} changed since last run")
    return 0


if __name__ == "__main__":
    sys.exit(main())
