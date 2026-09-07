#!/usr/bin/env python3
"""
Draft county-commission rosters for _data/local_officials.yml from the GA SoS
Enhanced Voting results API (results.sos.ga.gov).

WHY THIS EXISTS
    There is no upstream API for *local* officials, so every roster in
    _data/local_officials.yml is hand-curated (see LOCAL-GOVERNMENT-IA.md). Doing
    that from scratch for all 159 counties is the bottleneck. This script is the
    "Track A (assisted)" drafter named in that file's curation workflow: it turns
    the *winners* of the most recent general election into draft roster blocks a
    human then reviews and confirms.

    It does NOT write _data/local_officials.yml. It emits a draft (YAML blocks to
    paste, or JSON) and a diff against what is already curated, so a person stays
    the merge gate.

HARD LIMITS OF THE SOURCE (verified 2026-09; see memory reference-ga-sos-results-api)
    1. LOCAL offices only exist in the API from ~2024 onward — the 2020/2022 county
       endpoints carry state/federal/ballot-measures only. So this yields ONLY the
       most-recent cohort. GA county boards are 4-yr STAGGERED, so a single cycle
       covers ~half a board; the other half was last elected in a pre-2024 cycle
       the API lacks and must be filled another way (or after the 2026 cycle).
    2. `isWinner` is unreliable on these contests, so we take the vote leader. But
       under GA's MAJORITY rule a leader <50% goes to a runoff, and general/special
       runoffs for local seats are NOT in this portal. So a sub-50% leader is NOT
       asserted as the winner — it is emitted with a _needs_runoff_check flag.
    3. No term-length data. GA county terms are set per-county by local act, are
       non-uniform, and have no machine source. We emit `last_elected` (reliable)
       and leave term_end / next_election blank for the curator.

USAGE
    python scripts/generate_local_officials.py --counties dekalb,douglas,fulton --diff
    python scripts/generate_local_officials.py --all --emit yaml --out draft.yml
    python scripts/generate_local_officials.py --all --emit json --out draft.json
"""

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

API = "https://results.sos.ga.gov/results/public/api"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120 Safari/537.36")
# The seating election: most recent November general that carries LOCAL offices.
# Not guessable — confirmed from the jurisdictions endpoint. Bump after Nov 2026.
SEATING_SLUG = "2024NovGen"
SEATING_YEAR = 2024

LOCAL_OFFICIALS_PATH = "_data/local_officials.yml"

# Offices that are NOT the county commission board (statewide constitutional
# "Commissioner of X", the elected tax commissioner, other elected countywide
# offices, and the separately-elected Board of Education).
_SKIP_OFFICE = re.compile(
    r"commissioner of|insurance commissioner|tax commissioner|soil|water conservation|"
    r"board of education|county boe|\bboe\b|school|superintendent",
    re.I,
)


def _get(url, tries=4):
    """GET JSON with retry on 429/5xx only (4xx are non-retryable — CLAUDE.md)."""
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < tries - 1:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if attempt < tries - 1:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise


def _text(name_field):
    if isinstance(name_field, list) and name_field:
        return (name_field[0].get("text") or "").strip()
    return str(name_field or "").strip()


def list_counties():
    """All 159 county short-names, from the seating election's jurisdiction tree."""
    d = _get(f"{API}/elections/Georgia/{SEATING_SLUG}/data")
    cl = (d.get("jurisdiction") or {}).get("childLocalities") or []
    return [c.get("shortName") for c in cl if c.get("shortName")]


def slug_of(short_name):
    """`dekalb-county-ga` -> `dekalb` (the join key used in local_officials.yml)."""
    return re.sub(r"-county-ga$", "", short_name or "")


def clean_name(raw):
    """The FULL name: strip only the inline markers the API appends ('(I)', '(Dem)',
    '(Rep)', '(Incumbent)'). Keeps middle initials and suffixes — that is the value
    of full_name."""
    n = _text(raw) if not isinstance(raw, str) else raw
    n = re.sub(r"\s*\((?:I|Inc|Incumbent|Rep|Dem|Ind|NPA|Lib|Grn|[A-Za-z]{2,3})\)", "", n)
    return re.sub(r"\s+", " ", n).strip()


def short_name(full):
    """The DISPLAY name: drop quotes and interior single-letter middle initials,
    keeping the first and last tokens. 'Lisa N. Cupid' -> 'Lisa Cupid'; 'Whitney C.
    Kenner Jones' -> 'Whitney Kenner Jones'. First/last are never dropped, so a
    lone initial that IS the name survives."""
    parts = full.replace('"', "").replace("'", "").split()
    keep = []
    for i, p in enumerate(parts):
        interior = 0 < i < len(parts) - 1
        if interior and len(p.rstrip(".")) == 1:
            continue
        keep.append(p)
    return " ".join(keep) or full


def map_party(abbr):
    a = (abbr or "").strip().lower()
    if a.startswith("rep"):
        return "Republican"
    if a.startswith("dem"):
        return "Democratic"
    return "Nonpartisan"  # independents/nonpartisan land here — flagged in the draft


def classify(office):
    """Map an SoS office label to (role, title, seat) for the commission board,
    or None if the office is not a county-commission seat.

    role is CANONICAL (validator vocab): 'Chair' for the presiding officer,
    'Commissioner' for a district/at-large member. title carries the verbatim
    label only when it is distinctive (CEO, Sole Commissioner, 'Commission Chair')."""
    o = office.strip()
    ol = o.lower()
    if _SKIP_OFFICE.search(ol):
        return None
    special = "(special)" in ol

    if "chief executive officer" in ol:
        return ("Chair", "Chief Executive Officer", "At-large", special)
    if "sole commissioner" in ol:
        return ("Chair", "Sole Commissioner", "At-large", special)
    if "commission" in ol and "chair" in ol:
        # e.g. "Commission Chair", "Board of Commissioners Chairman"
        title = re.sub(r"\s*\(special\)", "", o, flags=re.I).strip()
        return ("Chair", title, "At-large", special)
    # A county-commission member seat. Gate on the county board specifically, then
    # extract the seat from the many label styles GA counties use.
    if re.search(r"commissioner|board of commissioners|county commission", ol):
        return ("Commissioner", None, _commission_seat(o, ol), special)
    return None


def _commission_seat(o, ol):
    """Extract a commission member's seat label from the varied SoS forms:
      'County Commissioner - District 2' / 'County Commission - District 2'  -> District 2
      'County Commissioner D6' / 'Super District 6'                          -> (Super) District 6
      'County Commission 1' / 'County Commission 5 At Large'  (bare number)  -> District 1 / District 5 (At-Large)
      'County Commission - Anna' / 'Board of Commissioners, Elmodel' (named)  -> Anna / Elmodel
      'County Commission - At Large'                                          -> At-large
    Falls back to 'At-large' when nothing else parses."""
    at_large = "at large" in ol or "at-large" in ol
    # 1) explicit District/Post/Super District N
    m = re.search(r"\b(?:super\s+district|district|dist|post)\s*[-#]?\s*(\d+)", ol)
    if not m:
        m = re.search(r"\bd\s*[-#]?\s*(\d+)\b", ol)  # 'D6' short form
    # 2) bare number after 'commission' (e.g. 'County Commission 1')
    if not m:
        m = re.search(r"commission[^0-9a-z]+(\d+)", ol)
    if m:
        n = m.group(1)
        if "super" in ol:
            return f"Super District {n}"
        return f"District {n} (At-Large)" if at_large else f"District {n}"
    if at_large:
        return "At-large"
    # 3) named district: text after 'commission -' / 'commissioners,' that isn't a number
    m = re.search(r"commission(?:ers?)?\s*[-,]\s*([a-z][a-z .'&]+?)\s*(?:\(special\))?$",
                  o.strip(), re.I)
    if m:
        return m.group(1).strip().title()
    return "At-large"


def winner_of(ballot_item):
    """Return (name, party_abbr, share) for the vote leader, or None."""
    opts = (ballot_item.get("summaryResults") or {}).get("ballotOptions") or []
    opts = [o for o in opts if (o.get("voteCount") or 0) > 0 or not o.get("isWriteIn")]
    if not opts:
        return None
    lead = max(opts, key=lambda o: o.get("voteCount") or 0)
    total = sum(o.get("voteCount") or 0 for o in opts) or 1
    share = (lead.get("voteCount") or 0) / total
    abbr = (lead.get("party") or {}).get("abbreviation") or ""
    return (clean_name(lead.get("name")), abbr, share)


def draft_county(county_short):
    """Fetch one county and return a draft roster (list of member dicts)."""
    try:
        d = _get(f"{API}/elections/{county_short}/{SEATING_SLUG}/data")
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}"}
    members = []
    for it in d.get("ballotItems") or []:
        office = _text(it.get("name"))
        cls = classify(office)
        if not cls:
            continue
        role, title, seat, special = cls
        w = winner_of(it)
        if not w:
            continue
        full, abbr, share = w
        disp = short_name(full)
        m = {
            "name": disp,          # short display name (what the site shows)
            "role": role,
            "seat": seat,
            "party": map_party(abbr),
            "email": "",
            "phone": "",
            "last_elected": SEATING_YEAR,
            "term_end": None,      # unknowable from results — curator fills
            "next_election": None,
            "voting": True,
            "source": f"{API}/elections/{county_short}/{SEATING_SLUG}/data",
            "_office": office,     # provenance: the verbatim SoS label
            "_share": round(share, 3),
        }
        if full != disp:           # keep the authoritative full name when it adds info
            m["full_name"] = full
        if title:
            m["title"] = title
        if special:
            m["_special"] = True
        if share < 0.5:
            # Sub-50% leader → a runoff decided this, and the portal lacks it.
            m["_needs_runoff_check"] = True
        members.append(m)
    # Presiding officer first, then by seat.
    members.sort(key=lambda m: (m["role"] != "Chair", m["seat"]))
    return {"members": members}


# ---------------------------------------------------------------------------
# YAML emission (hand-rolled to control comments/ordering — no yaml.dump)
# ---------------------------------------------------------------------------
def load_place_slugs():
    """Slugs already registered in _data/places.yml — skip these when stubbing."""
    import yaml
    try:
        with open("_data/places.yml", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        return set()
    return {p.get("slug") for p in (data.get("places") or []) if isinstance(p, dict)}


def emit_places_yaml(county_slug, county_name):
    """A _data/places.yml stub: identity + an empty meeting-schedule scaffold. The
    schedule (body/when/location) is HAND-entered from the county site — it is not
    in any API. FIPS comes from the Census (scripts/lib/ga_county_fips.py)."""
    try:
        from lib.ga_county_fips import GA_COUNTY_FIPS
    except ImportError:
        GA_COUNTY_FIPS = {}
    fips = GA_COUNTY_FIPS.get(county_slug)
    fips_line = f'    fips: "{fips}"' if fips else '    fips:            # TODO: county FIPS (13xxx)'
    return "\n".join([
        f"  - slug: {county_slug}",
        f"    name: {county_name}",
        "    type: county",
        fips_line,
        "    parentCounty: null",
        "    region:                         # optional hub grouping label",
        "    domains:",
        "      meetings:",
        "        # Curated recurring schedule -> the \"When they meet\" note on /local/"
        f"{county_slug}/.",
        "        # Fill when: (and optional location:) per body. No scraper adapter needed",
        "        # for a schedule; add a platform (civicplus|corecode|civicclerk|legistar|teammunicode|primegov) later to",
        "        # auto-aggregate agendas/minutes (see the places.yml header).",
        '        agendas_url: ""            # direct agenda/minutes hub (optional; works with or without a scraper adapter)',
        "        schedule:",
        "          - body: Board of Commissioners",
        '            when: ""                # e.g. "2nd Tuesday of every month, 9:00 a.m."',
        '            location: ""            # optional',
    ])


def _yq(s):
    """YAML-safe double-quoted scalar — escapes backslash and quote so a name with
    an inline nickname (Howard "Hal" Wiley) can't break the document."""
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def derive_government_form(members):
    """ceo | sole-commissioner | commission-chair | commission, from roster titles."""
    tl = " | ".join((m.get("title") or "") for m in members).lower()
    if "chief executive" in tl:
        return "ceo"
    if "sole commissioner" in tl:
        return "sole-commissioner"
    if any(m.get("role") == "Chair" for m in members):
        return "commission-chair"
    return "commission"


def emit_yaml(county_slug, county_name, draft):
    members = draft["members"]
    lines = []
    lines.append(f"  - id: {county_slug}")
    lines.append(f"    name: {county_name}")
    lines.append("    type: county")
    lines.append(f"    county: {county_name.replace(' County', '')}")
    lines.append("    body: Board of Commissioners")
    lines.append("    partisan: true")
    lines.append("    term_years: 4            # GA terms are per-county local act; most are 4 — override if different")
    lines.append(f"    board_size: {len(members)}             # auto: current roster size — verify against authorized seats")
    lines.append(f"    government_form: {derive_government_form(members)}   # ceo | sole-commissioner | commission-chair | commission")
    lines.append(f"    official_url: \"\"            # TODO: county government site")
    lines.append("    related_pages:")
    lines.append("    members:")
    for m in members:
        flag = ""
        if m.get("_needs_runoff_check"):
            flag = f"   # (!) {int(m['_share']*100)}% — sub-50%, RUNOFF decided this; verify (not in portal)"
        elif m.get("_special"):
            flag = "   # special election"
        lines.append(f"      - name: {_yq(m['name'])}{flag}")
        if m.get("full_name"):
            lines.append(f"        full_name: {_yq(m['full_name'])}   # authoritative full name (matching); site shows `name`")
        lines.append(f"        role: {m['role']}")
        if m.get("title"):
            lines.append(f"        title: {m['title']}")
        lines.append(f"        seat: {_yq(m['seat'])}")
        lines.append(f"        party: {m['party']}")
        lines.append(f"        email: \"\"")
        lines.append(f"        phone: \"\"")
        lines.append(f"        last_elected: {m['last_elected']}")
        lines.append(f"        term_end: {m['last_elected'] + 4}         # last_elected + term_years (default 4) — verify")
        lines.append(f"        next_election: {m['last_elected'] + 4}")
        lines.append(f"        voting: true")
        lines.append(f"        source: {_yq(m['source'])}   # SoS results — CONFIRM before merge")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Diff against the existing hand-curated roster
# ---------------------------------------------------------------------------
_NAME_STOP = {"jr", "sr", "ii", "iii", "iv", "phd", "dr", "mr", "mrs", "ms"}


def _norm(s, loose=False):
    """Normalize a name for the 'is this the same person?' comparison. Lowercase,
    turn any non-letter (hyphen, period, comma, quotes) into a space, drop honorific
    /suffix words.

    strict (default) KEEPS middle initials, so it only equates identical forms
    ('lisa n cupid'). loose ALSO drops single-letter tokens, collapsing middle-
    initial variants ('Lisa Cupid' == 'Lisa N. Cupid'). We match strict first (on
    the stored full_name, for confidence), then fall back to loose so a roster that
    only stored the short display name still pairs and doesn't nag every run."""
    s = (s or "").lower()
    s = re.sub(r"[^a-z]+", " ", s)
    toks = [t for t in s.split() if t not in _NAME_STOP and (not loose or len(t) > 1)]
    return " ".join(toks)


def _cmp_name(m):
    """The richest name a member carries, for matching: prefer stored full_name."""
    return m.get("full_name") or m.get("name") or ""


def _seat_key(seat):
    m = re.search(r"(\d+)", seat or "")
    sup = "super" in (seat or "").lower()
    return ("super" if sup else "dist", m.group(1) if m else (seat or "").lower())


def load_curated():
    import yaml
    with open(LOCAL_OFFICIALS_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return {j.get("id"): j for j in (data.get("jurisdictions") or []) if isinstance(j, dict)}


def diff_county(slug, draft, curated, changes_only=False):
    """Three-pass reconciliation so the same person isn't double-reported when a
    seat label differs (SoS 'D6' vs your 'Super District 6'):
      1. pair by NAME  -> '=' match (note any seat-label difference)
      2. pair remaining by SEAT -> '~' MISMATCH (a turnover, or a stale entry)
      3. leftovers -> '+' results-only / '-' roster-only (pre-2024 cohort)."""
    j = curated.get(slug)
    if not j:
        if changes_only:
            return None
        return f"  {slug}: not yet curated ({len(draft['members'])} seats drafted from {SEATING_SLUG})"
    gen = list(draft["members"])
    man = list(j.get("members") or [])
    used_g, used_m = set(), set()
    out = [f"  {slug}:"]
    actionable = 0  # '~' mismatches and '+' results-only (real drift signals)

    # Pass 1 — by name (strict on full_name first, then loose)
    for gi, g in enumerate(gen):
        gstrict, gloose = _norm(_cmp_name(g)), _norm(_cmp_name(g), loose=True)
        for mi, m in enumerate(man):
            if mi in used_m:
                continue
            mstrict, mloose = _norm(_cmp_name(m)), _norm(_cmp_name(m), loose=True)
            if not gloose or gloose != mloose:
                continue  # not the same person
            used_g.add(gi); used_m.add(mi)
            if not changes_only:  # '=' match is confirmation, not a to-do
                seatnote = ("" if _seat_key(g["seat"]) == _seat_key(m.get("seat"))
                            else f"  (seat: yours='{m.get('seat')}' vs results='{g['seat']}')")
                # Loose-but-not-strict = same person, different name form. Offer the
                # authoritative full name so the curator can store it (upgrades
                # future matches to strict) without changing the display `name`.
                formnote = ("" if gstrict == mstrict
                            else f"  (consider full_name: \"{g.get('full_name') or g['name']}\")")
                extra = "  [!] results <50%, runoff-decided" if g.get("_needs_runoff_check") else ""
                out.append(f"      = {g['name']} - match{seatnote}{formnote}{extra}")
            break

    # Pass 2 — remaining, by seat (name differs => turnover or stale)
    for gi, g in enumerate(gen):
        if gi in used_g:
            continue
        for mi, m in enumerate(man):
            if mi in used_m:
                continue
            if _seat_key(g["seat"]) == _seat_key(m.get("seat")):
                used_g.add(gi); used_m.add(mi)
                note = ("  (results leader <50% -> runoff decided this; trust your roster)"
                        if g.get("_needs_runoff_check") else "")
                out.append(f"      ~ {g['seat']:16} MISMATCH  yours={m.get('name')}  results={g['name']}{note}")
                actionable += 1
                break

    # Pass 3 — leftovers
    for gi, g in enumerate(gen):
        if gi in used_g:
            continue
        note = "  [!] <50%, runoff-unverified" if g.get("_needs_runoff_check") else ""
        out.append(f"      + {g['seat']:16} {g['name']} [{g['party'][:3]}] - in results, not in your roster{note}")
        actionable += 1
    if not changes_only:  # a roster-only seat is expected (pre-2024 cohort), not a to-do
        for mi, m in enumerate(man):
            if mi in used_m:
                continue
            out.append(f"      - {(m.get('seat') or '?'):16} {m.get('name')} - in your roster, NOT in "
                       f"{SEATING_SLUG} (likely a pre-2024 cohort the API lacks)")

    if changes_only and actionable == 0:
        return None
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--counties", help="comma-separated county slugs (e.g. dekalb,douglas)")
    grp.add_argument("--all", action="store_true", help="all 159 counties")
    grp.add_argument("--curated", action="store_true",
                     help="only county-type jurisdictions already in local_officials.yml "
                          "(the drift-check mode for the scheduled report)")
    ap.add_argument("--emit", choices=["yaml", "json", "places-yaml", "none"], default="none",
                    help="draft output: yaml/json = local_officials roster blocks; "
                         "places-yaml = _data/places.yml stubs (identity + empty meeting "
                         "schedule scaffold) for counties not already registered; "
                         "default none = diff/summary only")
    ap.add_argument("--out", help="write --emit output here instead of stdout")
    ap.add_argument("--diff", action="store_true", help="diff drafts against _data/local_officials.yml")
    ap.add_argument("--changes-only", action="store_true",
                    help="in --diff, print only actionable lines (mismatches / results-only), "
                         "hiding matches and expected pre-2024-cohort seats")
    ap.add_argument("--sleep", type=float, default=0.2, help="delay between county fetches")
    args = ap.parse_args()

    if args.all:
        print(f"Enumerating counties from {SEATING_SLUG}…", file=sys.stderr)
        shorts = list_counties()
    elif args.curated:
        cur = load_curated()
        shorts = [f"{jid}-county-ga" for jid, j in cur.items()
                  if isinstance(j, dict) and j.get("type") == "county"]
    else:
        shorts = [f"{s.strip()}-county-ga" for s in args.counties.split(",") if s.strip()]
    print(f"Drafting {len(shorts)} counties from {SEATING_SLUG}…", file=sys.stderr)

    # County display names from the seating election tree (needed for YAML blocks).
    names = {}
    if args.emit in ("yaml", "places-yaml"):
        try:
            tree = _get(f"{API}/elections/Georgia/{SEATING_SLUG}/data")
            for c in (tree.get("jurisdiction") or {}).get("childLocalities") or []:
                names[c.get("shortName")] = _text(c.get("name"))
        except Exception:
            pass

    drafts, errors = {}, {}
    for short in shorts:
        d = draft_county(short)
        if "error" in d:
            errors[short] = d["error"]
        else:
            drafts[slug_of(short)] = (short, d)
        time.sleep(args.sleep)

    # Emit drafts
    if args.emit != "none":
        chunks = []
        if args.emit == "json":
            payload = {
                "metadata": {
                    "generatedAt": datetime.now(timezone.utc).isoformat(),
                    "source": f"GA SoS Enhanced Voting results API — {SEATING_SLUG}",
                    "note": ("DRAFT from most-recent-cycle winners; local offices only exist "
                             "in this API from ~2024. Covers ~half of staggered boards. Sub-50% "
                             "seats need runoff verification. No term dates."),
                    "count": len(drafts),
                },
                "counties": {slug: d for slug, (_s, d) in drafts.items()},
            }
            text = json.dumps(payload, indent=2)
        elif args.emit == "places-yaml":
            existing = load_place_slugs()
            skipped = 0
            for slug, (short, d) in drafts.items():
                if slug in existing:
                    skipped += 1
                    continue
                nm = names.get(short) or f"{slug.title()} County"
                chunks.append(emit_places_yaml(slug, nm))
            text = "\n\n".join(chunks)
            print(f"places-yaml: {len(chunks)} stubs, skipped {skipped} already in places.yml",
                  file=sys.stderr)
        else:
            for slug, (short, d) in drafts.items():
                nm = names.get(short) or f"{slug.title()} County"
                chunks.append(emit_yaml(slug, nm, d))
            text = "\n\n".join(chunks)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(text + "\n")
            print(f"Wrote {args.emit} for {len(drafts)} counties -> {args.out}", file=sys.stderr)
        else:
            print(text)

    # Diff
    if args.diff:
        curated = load_curated()
        blocks = []
        for slug, (short, d) in drafts.items():
            b = diff_county(slug, d, curated, changes_only=args.changes_only)
            if b:
                blocks.append(b)
        if args.changes_only:
            if blocks:
                print(f"Results-API drift vs {LOCAL_OFFICIALS_PATH} ({SEATING_SLUG}) — "
                      f"'~' seat turnover/stale, '+' won a {SEATING_YEAR} seat you don't list:")
                print("\n".join(blocks))
            else:
                print(f"No results-API drift: every curated county's {SEATING_YEAR} winners "
                      f"match the roster (checked {len(drafts)} counties).")
        else:
            print(f"\n=== DIFF vs {LOCAL_OFFICIALS_PATH} ({SEATING_SLUG}) ===")
            print("  =match  ~mismatch  +results-only  -roster-only(pre-2024 cohort)")
            print("\n".join(blocks))

    if errors:
        print(f"\n{len(errors)} counties errored:", file=sys.stderr)
        for s, e in list(errors.items())[:10]:
            print(f"  {s}: {e}", file=sys.stderr)

    # Summary
    total = sum(len(d["members"]) for _s, d in drafts.values())
    print(f"\n{len(drafts)} counties, {total} seats drafted, {len(errors)} errors.", file=sys.stderr)


if __name__ == "__main__":
    main()
