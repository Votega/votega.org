#!/usr/bin/env python3
"""Reconcile the SOAP roster against the committed Open States one, field by field.

Phase 0 of Roadmap/ROSTER-SOAP-MIGRATION-SPEC.md, and its actual deliverable: the table
this prints is what decides whether Phase 1 is worth doing. Reads two local files, calls
no API, writes nothing.

    python scripts/generate_ga_members_soap.py     # build the parallel roster first
    python scripts/compare_members_soap_vs_os.py

Exit criteria for Phase 0 (spec §5): 100% agreement on `legisGaGovId`, `chamber`,
`district` and `party`, and every other difference explained. This script enforces the
first half — it exits non-zero if any IDENTITY field disagrees — and categorises the rest
so the explaining is quick.

The members are joined on `legisGaGovId`, never on name: that is the whole point of the
official source. The four statewide executives carry no legisGaGovId and are reported
separately rather than counted as misses.
"""
from __future__ import annotations

import json
import io
import os
import re
import sys
from collections import Counter, defaultdict

OS_FILE   = "assets/data/ga-members.json"
SOAP_FILE = "assets/data/ga-members.soap.json"

#: Must match exactly, or the migration is unsafe. These drive the whole site: a wrong
#: chamber or district misfiles a member, and party feeds every tally and the scorecard.
IDENTITY = ("legisGaGovId", "chamber", "district", "party")

#: Name fields are display content, not identity — identity is legisGaGovId. SOAP returns
#: the FORMAL name ("Timothy Bearden") where the site publishes the common one ("Tim
#: Bearden"), and all 18 such members would have their entity URL move, since
#: build_entity_pages.py slugs on the name. The producer therefore preserves the published
#: name and reports a divergence for review, so these are expected to agree here.
NAMES = ("name", "firstName", "lastName")

#: Compared and reported, but a difference is a judgement call rather than a defect.
CONTENT = NAMES + ("title", "imageUrl", "phone", "address", "email",
                   "officialWebsiteUrl", "committees")

#: Copied from the committed roster by construction (SOAP cannot supply them), so
#: comparing them would only ever report equality. Named here so the output says why.
PRESERVED = ("id", "birthDate", "birthYear", "termStart", "status", "statusDate",
             "statusNote")


def load(path):
    if not os.path.exists(path):
        sys.exit(f"missing {path} — run generate_ga_members_soap.py first")
    with io.open(path, encoding="utf-8") as fh:
        return json.load(fh)


def norm(field, value):
    """Fold the differences that are formatting rather than disagreement."""
    if value is None:
        return None
    if field == "committees":
        # Order is incidental; "&" vs "and" is the two services disagreeing with each
        # other (and with themselves) about the same committee.
        return tuple(sorted(re.sub(r"[^a-z0-9]+", " ", c.lower().replace("&", " and ")).strip()
                            for c in value))
    if isinstance(value, str):
        s = value.strip()
        if field == "phone":
            return re.sub(r"\D", "", s) or None
        if field in ("email", "imageUrl", "officialWebsiteUrl"):
            return s.lower()
        return s
    return value


def main():
    os_doc, soap_doc = load(OS_FILE), load(SOAP_FILE)
    os_members, soap_members = os_doc.get("members", []), soap_doc.get("members", [])

    os_by_id = {m["legisGaGovId"]: m for m in os_members if m.get("legisGaGovId")}
    soap_by_id = {m["legisGaGovId"]: m for m in soap_members if m.get("legisGaGovId")}
    os_exec = [m for m in os_members if not m.get("legisGaGovId")]
    soap_exec = [m for m in soap_members if not m.get("legisGaGovId")]

    print(f"{OS_FILE}: {len(os_members)} records ({len(os_by_id)} with a legisGaGovId)")
    print(f"{SOAP_FILE}: {len(soap_members)} records ({len(soap_by_id)} with a legisGaGovId)")
    print(f"executives (no legisGaGovId, preserved verbatim): "
          f"{len(os_exec)} -> {len(soap_exec)}\n")

    only_os = sorted(set(os_by_id) - set(soap_by_id))
    only_soap = sorted(set(soap_by_id) - set(os_by_id))
    shared = sorted(set(os_by_id) & set(soap_by_id))
    print(f"roster overlap: {len(shared)} shared, {len(only_os)} OS-only, "
          f"{len(only_soap)} SOAP-only")
    for mid in only_os:
        m = os_by_id[mid]
        print(f"   OS-only   {mid} {m.get('name')} ({m.get('chamber')} {m.get('district')}) "
              f"status={m.get('status')!r}")
    for mid in only_soap:
        m = soap_by_id[mid]
        print(f"   SOAP-only {mid} {m.get('name')} ({m.get('chamber')} {m.get('district')})")

    diffs = defaultdict(list)
    for mid in shared:
        a, b = os_by_id[mid], soap_by_id[mid]
        for field in IDENTITY + CONTENT:
            if norm(field, a.get(field)) != norm(field, b.get(field)):
                diffs[field].append((mid, a.get("name"), a.get(field), b.get(field)))

    print(f"\n{'field':20s} {'agree':>7s} {'differ':>7s}   verdict")
    print("-" * 72)
    identity_fail = 0
    for field in IDENTITY + CONTENT:
        d = len(diffs[field])
        agree = len(shared) - d
        if field in IDENTITY:
            verdict = "OK" if d == 0 else "*** MUST BE ZERO ***"
            identity_fail += d
        else:
            verdict = "identical" if d == 0 else "review"
        print(f"{field:20s} {agree:7d} {d:7d}   {verdict}")
    print("-" * 72)
    print(f"preserved by construction (not compared): {', '.join(PRESERVED)}")

    for field in IDENTITY + CONTENT:
        if not diffs[field]:
            continue
        rows = diffs[field]
        print(f"\n--- {field}: {len(rows)} of {len(shared)} differ ---")
        for mid, name, osv, soapv in rows[:12]:
            print(f"  {name} ({mid})")
            print(f"     OS  : {osv!r}")
            print(f"     SOAP: {soapv!r}")
        if len(rows) > 12:
            print(f"  ... and {len(rows) - 12} more")

    # Coverage is the other half of the question: a field SOAP fills where OS did not is
    # the upside, and the reverse is the cost.
    print("\n--- coverage, shared members only ---")
    print(f"{'field':20s} {'OS':>6s} {'SOAP':>6s}   {'delta':>6s}")
    for field in CONTENT + ("birthYear", "termStartYear", "leadershipRole", "occupation",
                            "pressUrl", "residence", "dateVacated"):
        o = sum(1 for mid in shared if os_by_id[mid].get(field) not in (None, "", [], {}))
        s = sum(1 for mid in shared if soap_by_id[mid].get(field) not in (None, "", [], {}))
        flag = "" if s >= o else "   <-- regression"
        print(f"{field:20s} {o:6d} {s:6d}   {s - o:+6d}{flag}")

    review = soap_doc.get("review") or {}
    if any(review.values()):
        print("\n--- producer review lists ---")
        for k, rows in review.items():
            if rows:
                print(f"  {k}: {len(rows)}")
                for r in rows[:6]:
                    print(f"     {r}")

    print()
    if identity_fail:
        print(f"FAIL: {identity_fail} identity-field disagreement(s). Phase 1 is unsafe "
              f"until each is understood.", file=sys.stderr)
        return 1
    print("PASS: every identity field agrees on all shared members.")
    print("Remaining differences are content/formatting — explain each in the spec "
          "before starting Phase 1.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
