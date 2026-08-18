#!/usr/bin/env python3
"""
Build prefilled Tally claim links for the general-election ballot.

Reads assets/data/races.json (general phase only), assigns each candidate a
questionnaire tier, masks the on-file email into a display hint, and emits one
prefilled claim URL per candidate — plus the real email — as a CSV for mail merge.

Tier assignment (drives which questionnaire pages the Tally form shows):
    federal, state          -> B   (legislative: U.S./GA House & Senate)
    state-executive         -> C   (statewide executive; PSC also C, its two
                                     extra questions are gated in Tally on
                                     race_label containing "Public Service")
    state-judicial          -> D   (restricted judicial questionnaire)

The URL parameter names must match the Tally hidden-field names exactly —
Tally has no parameter aliasing. See candidate-claim-form-copy.md sec. 2.

Output CSV (candidate-claim-links.csv) is a local outreach artifact and is
gitignored; it is regenerable from races.json at any time. This script is
committed because the mapping is cycle-recurring infrastructure.

Usage:
    python scripts/build_candidate_claim_links.py
    python scripts/build_candidate_claim_links.py --out some.csv --form-id q48agY
"""

import argparse
import csv
import json
import sys
from urllib.parse import urlencode

RACES_PATH = "assets/data/races.json"
CONGRESS_PATH = "assets/data/current-members.json"
DEFAULT_OUT = "candidate-claim-links.csv"
DEFAULT_FORM_ID = "q48agY"

TIER_BY_LEVEL = {
    "federal": "B",
    "state": "B",
    "state-executive": "C",
    "state-judicial": "D",
}


def load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def build_congress_names(path):
    """bioguideId -> 'First Last' (races.json stores federal incumbents by id only)."""
    names = {}
    try:
        data = load_json(path)
    except FileNotFoundError:
        print(f"warning: {path} not found; federal incumbent names may be blank", file=sys.stderr)
        return names
    for m in data.get("members", []):
        bid = m.get("bioguideId")
        if not bid:
            continue
        first, last = m.get("firstName"), m.get("lastName")
        if first and last:
            names[bid] = f"{first} {last}"
        elif m.get("name") and ", " in m["name"]:  # "Ossoff, Jon" -> "Jon Ossoff"
            ln, fn = m["name"].split(", ", 1)
            names[bid] = f"{fn} {ln}"
        elif m.get("name"):
            names[bid] = m["name"]
    return names


def mask_email(email):
    """d***@dooleyforgeorgia.com — first char, then stars, preserving domain."""
    if not email or "@" not in email:
        return ""
    local, domain = email.split("@", 1)
    if not local:
        return ""
    return f"{local[0]}***@{domain}"


def general_candidates(race):
    """Flatten a race's general phase into a candidate list (handles both shapes)."""
    g = (race.get("phases") or {}).get("general")
    if not g:
        return []
    cands = list(g.get("candidates") or [])
    for ballot in (g.get("ballots") or {}).values():
        cands.extend(ballot or [])
    return cands


def resolve_key(cand):
    """Return (candidate_key, key_type). Prefer id; fall back to memberId."""
    if cand.get("id"):
        return cand["id"], "id"
    if cand.get("memberId"):
        return cand["memberId"], "memberId"
    return None, None


def build_rows(races, congress_names, base_url):
    rows = []
    skipped = []
    for race in races:
        level = race.get("level")
        tier = TIER_BY_LEVEL.get(level)
        race_label = race.get("chamber") or ""
        race_id = race.get("id") or ""
        for cand in general_candidates(race):
            if cand.get("withdrawn") or cand.get("disqualified"):
                continue
            key, key_type = resolve_key(cand)
            if not key:
                skipped.append((race_id, cand.get("name")))
                continue

            name = cand.get("name")
            if not name and cand.get("memberSource") == "congress":
                name = congress_names.get(cand.get("memberId"), "")
            name = name or ""

            email = cand.get("email") or ""
            member_source = cand.get("memberSource") or ""

            params = {
                "candidate_key": key,
                "key_type": key_type,
                "member_source": member_source,
                "race_id": race_id,
                "candidate_name": name,
                "race_label": race_label,
                "tier": tier or "",
                "onfile_email_hint": mask_email(email),
                "src": "email",
            }
            url = f"{base_url}?{urlencode(params)}"
            rows.append({
                "candidate_name": name,
                "race_label": race_label,
                "party": cand.get("party") or "",
                "level": level or "",
                "tier": tier or "",
                "candidate_key": key,
                "key_type": key_type,
                "member_source": member_source,
                "race_id": race_id,
                "email": email,
                "onfile_email_hint": mask_email(email),
                "has_email": "yes" if email else "no",
                "claim_url": url,
            })
    return rows, skipped


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--form-id", default=DEFAULT_FORM_ID)
    args = ap.parse_args()

    base_url = f"https://tally.so/r/{args.form_id}"

    races = load_json(RACES_PATH).get("races", [])
    congress_names = build_congress_names(CONGRESS_PATH)
    rows, skipped = build_rows(races, congress_names, base_url)

    fieldnames = [
        "candidate_name", "race_label", "party", "level", "tier",
        "candidate_key", "key_type", "member_source", "race_id",
        "email", "onfile_email_hint", "has_email", "claim_url",
    ]
    with open(args.out, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    # Summary to stderr so it doesn't pollute a piped CSV.
    by_tier = {}
    with_email = 0
    for r in rows:
        by_tier[r["tier"]] = by_tier.get(r["tier"], 0) + 1
        if r["has_email"] == "yes":
            with_email += 1
    print(f"wrote {len(rows)} rows -> {args.out}", file=sys.stderr)
    print(f"  by tier: {dict(sorted(by_tier.items()))}", file=sys.stderr)
    print(f"  with on-file email: {with_email}  (phone/social verify: {len(rows) - with_email})", file=sys.stderr)
    if skipped:
        print(f"  skipped {len(skipped)} candidate(s) with no id/memberId:", file=sys.stderr)
        for rid, nm in skipped[:10]:
            print(f"    - {rid}: {nm}", file=sys.stderr)

    missing_tier = [r for r in rows if not r["tier"]]
    if missing_tier:
        lv = sorted({r["level"] for r in missing_tier})
        print(f"  WARNING: {len(missing_tier)} rows have no tier (unmapped level(s): {lv})", file=sys.stderr)


if __name__ == "__main__":
    main()
