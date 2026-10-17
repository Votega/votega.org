#!/usr/bin/env python3
"""Generate the Cabinet-department rules data for the federal-executive page.

For each Cabinet department: every final rule and proposed rule the Federal
Register has published since the current term began, written to
assets/data/agency-actions/<slug>.json, plus a small
assets/data/agency-actions-index.json mapping department name -> slice.

This replaces the page's live, browser-side Federal Register call, which had no
date filter: it asked for a department's ENTIRE history and printed "Showing 20 of
10000", the API's own cap on `count`, not a number of rules. Scoped to the term it
is a real count (USDA: 224) the page can page over locally.

Why a slice per department rather than one file: all 16 together are ~5,500 rules,
~1 MB gzipped, and a visitor reads one department. Slices run 8-114 KB gzipped;
Transportation is the outlier (371 KB; 1,046 of its 2,191 rules are FAA
airworthiness directives). Abstracts are ~80% of the bytes and are kept in full,
since they are what the page shows.

Failure policy: any department failing to fetch exits 1 before anything is
written, so the committed files stay a consistent set. A department whose
hardcoded Federal Register ID no longer resolves to the expected agency slug is
fatal too - a wrong ID would silently publish another agency's rules.

Output files keep the previous `generatedAt` when the documents are unchanged, so a
quiet day is a byte-identical (empty) commit.
"""

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from generate_presidential_executive_orders import TERM_START  # noqa: E402
from lib.atomic_io import write_json_atomic  # noqa: E402
from lib.federal_register import AGENCIES_URL, fetch_all  # noqa: E402
from lib.http import fetch_json  # noqa: E402

OUT_DIR = "assets/data"
SLICE_DIR = "agency-actions"
INDEX_NAME = "agency-actions-index.json"
FIELDS = ["document_number", "title", "type", "publication_date", "html_url", "abstract"]
PER_PAGE = 1000   # one request covers every department but Transportation

#: department (as `department` appears in _data/executive.json) -> Federal Register
#: agency id and slug. The Office of the Director of National Intelligence has no
#: Register entry (it coordinates the intelligence community and issues no rules
#: of its own), so it is absent on purpose and the page says tracking is not
#: available for it. Verified against agencies.json on every run.
AGENCIES = {
    "Department of State":                         (476, "state-department"),
    "Department of the Treasury":                  (497, "treasury-department"),
    "Department of Defense":                       (103, "defense-department"),
    "Department of Justice":                       (268, "justice-department"),
    "Department of the Interior":                  (253, "interior-department"),
    "Department of Agriculture":                   (12,  "agriculture-department"),
    "Department of Commerce":                      (54,  "commerce-department"),
    "Department of Labor":                         (271, "labor-department"),
    "Department of Health and Human Services":     (221, "health-and-human-services-department"),
    "Department of Housing and Urban Development": (228, "housing-and-urban-development-department"),
    "Department of Transportation":                (492, "transportation-department"),
    "Department of Energy":                        (136, "energy-department"),
    "Department of Education":                     (126, "education-department"),
    "Department of Veterans Affairs":              (520, "veterans-affairs-department"),
    "Office of Management and Budget":             (280, "management-and-budget-office"),
    "Department of Homeland Security":             (227, "homeland-security-department"),
}


def verify_agency_ids(agencies_json, registry=AGENCIES):
    """Names of departments whose id does not resolve to the expected slug."""
    by_id = {a.get("id"): a for a in agencies_json or []}
    return [name for name, (aid, slug) in registry.items()
            if (by_id.get(aid) or {}).get("slug") != slug]


def fetch_department(agency_id, term_start, fetcher=fetch_json):
    """Rules and proposed rules since term_start, or None if any page failed."""
    return fetch_all(
        f"conditions%5Bagency_ids%5D%5B%5D={agency_id}"
        "&conditions%5Btype%5D%5B%5D=RULE&conditions%5Btype%5D%5B%5D=PRORULE"
        f"&conditions%5Bpublication_date%5D%5Bgte%5D={term_start}",
        FIELDS, fetcher=fetcher, per_page=PER_PAGE, label="Federal Register rules")


def build_slice(name, agency_id, slug, documents, term_start, generated_at):
    return {
        "metadata": {"generatedAt": generated_at, "department": name,
                     "agencyId": agency_id, "slug": slug, "termStart": term_start,
                     "count": len(documents),
                     "source": "Federal Register API (federalregister.gov)"},
        "documents": documents,
    }


def build_index(slices, term_start, generated_at):
    return {
        "metadata": {"generatedAt": generated_at, "termStart": term_start,
                     "count": len(slices),
                     "source": "Federal Register API (federalregister.gov)"},
        "departments": {name: {"agencyId": s["metadata"]["agencyId"], "slug": s["metadata"]["slug"],
                               "file": f"{SLICE_DIR}/{s['metadata']['slug']}.json",
                               "count": s["metadata"]["count"]}
                        for name, s in slices.items()},
    }


def keep_timestamp_if_unchanged(new, path, content_key):
    """Reuse the committed file's generatedAt when its content is identical."""
    try:
        with open(path, encoding="utf-8") as f:
            old = json.load(f)
    except (OSError, ValueError):
        return new
    if old.get(content_key) == new.get(content_key) and \
            {k: v for k, v in old["metadata"].items() if k != "generatedAt"} == \
            {k: v for k, v in new["metadata"].items() if k != "generatedAt"}:
        new["metadata"]["generatedAt"] = old["metadata"]["generatedAt"]
    return new


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else OUT_DIR
    term_start = os.environ.get("TERM_START", TERM_START)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    bad = verify_agency_ids(fetch_json(AGENCIES_URL))
    if bad:
        print(f"FATAL: agency id no longer resolves to the expected slug for: {bad}", file=sys.stderr)
        sys.exit(1)

    slices = {}
    for name, (aid, slug) in AGENCIES.items():
        docs = fetch_department(aid, term_start)
        if docs is None:
            print(f"FATAL: fetch failed for {name}; nothing written", file=sys.stderr)
            sys.exit(1)
        slices[name] = build_slice(name, aid, slug, docs, term_start, now)
        print(f"  {name}: {len(docs)} rules since {term_start}")

    for s in slices.values():
        path = os.path.join(out_dir, SLICE_DIR, f"{s['metadata']['slug']}.json")
        write_json_atomic(path, keep_timestamp_if_unchanged(s, path, "documents"),
                          separators=(",", ":"))
    index_path = os.path.join(out_dir, INDEX_NAME)
    write_json_atomic(index_path, keep_timestamp_if_unchanged(
        build_index(slices, term_start, now), index_path, "departments"), indent=2)
    print(f"Wrote {len(slices)} department files + {INDEX_NAME}")


if __name__ == "__main__":
    main()
