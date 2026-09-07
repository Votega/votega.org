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
    """Strip inline markers the API appends: '(I)', '(Dem)', '(Rep)', '(Incumbent)'."""
    n = _text(raw) if not isinstance(raw, str) else raw
    n = re.sub(r"\s*\((?:I|Inc|Incumbent|Rep|Dem|Ind|NPA|Lib|Grn|[A-Za-z]{2,3})\)", "", n)
    return re.sub(r"\s+", " ", n).strip()


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
    if "commissioner" in ol or "board of commissioners" in ol:
        n = re.search(r"\b(?:super\s+district|district|dist|d|post)\s*[-#]?\s*(\d+)", ol)
        if n:
            seat = f"Super District {n.group(1)}" if "super" in ol else f"District {n.group(1)}"
        else:
            seat = "At-large"
        return ("Commissioner", None, seat, special)
    return None


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


def draft_county(short_name):
    """Fetch one county and return a draft roster (list of member dicts)."""
    try:
        d = _get(f"{API}/elections/{short_name}/{SEATING_SLUG}/data")
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
        name, abbr, share = w
        m = {
            "name": name,
            "role": role,
            "seat": seat,
            "party": map_party(abbr),
            "email": "",
            "phone": "",
            "last_elected": SEATING_YEAR,
            "term_end": None,      # unknowable from results — curator fills
            "next_election": None,
            "voting": True,
            "source": f"{API}/elections/{short_name}/{SEATING_SLUG}/data",
            "_office": office,     # provenance: the verbatim SoS label
            "_share": round(share, 3),
        }
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
def emit_yaml(county_slug, county_name, draft):
    lines = []
    lines.append(f"  - id: {county_slug}")
    lines.append(f"    name: {county_name}")
    lines.append("    type: county")
    lines.append(f"    county: {county_name.replace(' County', '')}")
    lines.append("    body: Board of Commissioners")
    lines.append("    partisan: true")
    lines.append(f"    official_url: \"\"            # TODO: county government site")
    lines.append("    related_pages:")
    lines.append("    members:")
    for m in draft["members"]:
        flag = ""
        if m.get("_needs_runoff_check"):
            flag = f"   # (!) {int(m['_share']*100)}% — sub-50%, RUNOFF decided this; verify (not in portal)"
        elif m.get("_special"):
            flag = "   # special election"
        lines.append(f"      - name: \"{m['name']}\"{flag}")
        lines.append(f"        role: {m['role']}")
        if m.get("title"):
            lines.append(f"        title: {m['title']}")
        lines.append(f"        seat: \"{m['seat']}\"")
        lines.append(f"        party: {m['party']}")
        lines.append(f"        email: \"\"")
        lines.append(f"        phone: \"\"")
        lines.append(f"        last_elected: {m['last_elected']}")
        lines.append(f"        term_end:                 # TODO: per-county term length")
        lines.append(f"        next_election:")
        lines.append(f"        voting: true")
        lines.append(f"        source: \"{m['source']}\"   # SoS results — CONFIRM before merge")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Diff against the existing hand-curated roster
# ---------------------------------------------------------------------------
def _norm(s):
    """Normalize a name for comparison: lowercase, drop suffixes/titles, and turn
    any non-letter (hyphen, period, comma) into a space so 'Cochran-Johnson' ==
    'Cochran Johnson'. Middle initials are kept — they are a real difference worth
    surfacing, so 'Whitney Kenner Jones' != 'Whitney C. Kenner Jones'."""
    s = (s or "").lower()
    s = re.sub(r"\b(jr|sr|ii|iii|iv|phd|dr|mr|mrs|ms)\b", " ", s)
    s = re.sub(r"[^a-z]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _seat_key(seat):
    m = re.search(r"(\d+)", seat or "")
    sup = "super" in (seat or "").lower()
    return ("super" if sup else "dist", m.group(1) if m else (seat or "").lower())


def load_curated():
    import yaml
    with open(LOCAL_OFFICIALS_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return {j.get("id"): j for j in (data.get("jurisdictions") or []) if isinstance(j, dict)}


def diff_county(slug, draft, curated):
    """Three-pass reconciliation so the same person isn't double-reported when a
    seat label differs (SoS 'D6' vs your 'Super District 6'):
      1. pair by NAME  -> '=' match (note any seat-label difference)
      2. pair remaining by SEAT -> '~' MISMATCH (a turnover, or a stale entry)
      3. leftovers -> '+' results-only / '-' roster-only (pre-2024 cohort)."""
    j = curated.get(slug)
    if not j:
        return f"  {slug}: not yet curated ({len(draft['members'])} seats drafted from {SEATING_SLUG})"
    gen = list(draft["members"])
    man = list(j.get("members") or [])
    used_g, used_m = set(), set()
    out = [f"  {slug}:"]

    # Pass 1 — by name
    for gi, g in enumerate(gen):
        for mi, m in enumerate(man):
            if mi in used_m:
                continue
            if _norm(g["name"]) and _norm(g["name"]) == _norm(m.get("name")):
                used_g.add(gi); used_m.add(mi)
                seatnote = ("" if _seat_key(g["seat"]) == _seat_key(m.get("seat"))
                            else f"  (seat: yours='{m.get('seat')}' vs results='{g['seat']}')")
                extra = "  [!] results <50%, runoff-decided" if g.get("_needs_runoff_check") else ""
                out.append(f"      = {g['name']} - match{seatnote}{extra}")
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
                break

    # Pass 3 — leftovers
    for gi, g in enumerate(gen):
        if gi in used_g:
            continue
        note = "  [!] <50%, runoff-unverified" if g.get("_needs_runoff_check") else ""
        out.append(f"      + {g['seat']:16} {g['name']} [{g['party'][:3]}] - in results, not in your roster{note}")
    for mi, m in enumerate(man):
        if mi in used_m:
            continue
        out.append(f"      - {(m.get('seat') or '?'):16} {m.get('name')} - in your roster, NOT in "
                   f"{SEATING_SLUG} (likely a pre-2024 cohort the API lacks)")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--counties", help="comma-separated county slugs (e.g. dekalb,douglas)")
    grp.add_argument("--all", action="store_true", help="all 159 counties")
    ap.add_argument("--emit", choices=["yaml", "json", "none"], default="none",
                    help="draft output format (default none — diff/summary only)")
    ap.add_argument("--out", help="write --emit output here instead of stdout")
    ap.add_argument("--diff", action="store_true", help="diff drafts against _data/local_officials.yml")
    ap.add_argument("--sleep", type=float, default=0.2, help="delay between county fetches")
    args = ap.parse_args()

    if args.all:
        print(f"Enumerating counties from {SEATING_SLUG}…", file=sys.stderr)
        shorts = list_counties()
    else:
        shorts = [f"{s.strip()}-county-ga" for s in args.counties.split(",") if s.strip()]
    print(f"Drafting {len(shorts)} counties from {SEATING_SLUG}…", file=sys.stderr)

    # County display names from the seating election tree (for YAML blocks).
    names = {}
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
        print(f"\n=== DIFF vs {LOCAL_OFFICIALS_PATH} ({SEATING_SLUG}) ===")
        print("  =match  ~mismatch  +results-only  -roster-only(pre-2024 cohort)")
        for slug, (short, d) in drafts.items():
            print(diff_county(slug, d, curated))

    if errors:
        print(f"\n{len(errors)} counties errored:", file=sys.stderr)
        for s, e in list(errors.items())[:10]:
            print(f"  {s}: {e}", file=sys.stderr)

    # Summary
    total = sum(len(d["members"]) for _s, d in drafts.values())
    print(f"\n{len(drafts)} counties, {total} seats drafted, {len(errors)} errors.", file=sys.stderr)


if __name__ == "__main__":
    main()
