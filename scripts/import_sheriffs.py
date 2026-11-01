#!/usr/bin/env python3
"""Draft county sheriffs for _data/county_officers.yml.

Two sources, joined per county:

  * Georgia Sheriffs' Association "Sheriffs by County" table - the CURRENT sheriff's
    name, office address and phone. Hand-maintained by the association, so it can lag
    a mid-term replacement. It carries no party and no election year.
  * The SoS results API (the same one generate_local_officials.py uses) for the
    seating election's Sheriff race - party, election year, and a cross-check that the
    association's name is the person who won.

A HUMAN confirms every row (the file is human-gated, like local_officials.yml); this
script only drafts. It never edits a county already present in the file.

    python scripts/import_sheriffs.py                 # report only
    python scripts/import_sheriffs.py --write         # append counties not yet in the file
    python scripts/import_sheriffs.py --diff          # compare the file to the association page

Scope is the counties in _data/places.yml (type: county): a sheriff is shown on a place
page, so a county with no page has nowhere to appear.
"""

import argparse
import difflib
import html
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(__file__))
from generate_local_officials import (  # noqa: E402
    API, SEATING_SLUG, SEATING_YEAR, UA, _get, _text, clean_name, map_party,
    short_name, winner_of,
)
from lib.atomic_io import atomic_write  # noqa: E402

ASSOC_URL = "https://georgiasheriffs.org/resources/sheriffs-by-county/"
PLACES_PATH = "_data/places.yml"
OUT_PATH = "_data/county_officers.yml"
TERM_YEARS = 4  # Georgia sheriffs: four-year terms, elected in presidential-year generals

_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")


def _norm(s):
    return re.sub(r"[^a-z]", "", (s or "").lower())


def _cell(s):
    return re.sub(r"\s+", " ", html.unescape(_TAG.sub(" ", s))).strip()


def fetch_association():
    """{normalized county: {name, address, phone}} from the association table."""
    req = urllib.request.Request(ASSOC_URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        page = r.read().decode("utf-8", "replace")
    out = {}
    for row in _ROW.findall(page):
        cells = [_cell(c) for c in _CELL.findall(row)]
        if len(cells) < 4 or not cells[1].lower().startswith("sheriff"):
            continue
        county, who, addr, phone = cells[0], cells[1], cells[2], cells[3]
        who = re.sub(r"^sheriff\s+", "", who, flags=re.I).strip()
        out[_norm(county)] = {"name": who, "address": addr, "phone": phone}
    return out


def registry_counties():
    import yaml  # lazy: the offline test job installs no packages
    with open(PLACES_PATH, encoding="utf-8") as f:
        places = yaml.safe_load(f)["places"]
    return [p for p in places if p.get("type") == "county"]


def sos_sheriff(slug):
    """(full name, party, share, unopposed, county_ok) of the seating election's winner."""
    try:
        d = _get(f"{API}/elections/{slug}-county-ga/{SEATING_SLUG}/data")
    except Exception as e:  # noqa: BLE001 - report, never abort the whole run
        return {"error": str(e)}
    for it in d.get("ballotItems") or []:
        if _text(it.get("name")).lower().startswith("sheriff"):
            w = winner_of(it)
            if not w:
                return {"error": "no votes recorded"}
            full, abbr, share = w
            party = "Independent" if abbr.strip().lower().startswith("ind") else map_party(abbr)
            n = len((it.get("summaryResults") or {}).get("ballotOptions") or [])
            return {"full": full, "party": party, "share": share,
                    "unopposed": n == 1, "special": "special" in _text(it.get("name")).lower()}
    return {"error": "no Sheriff race on the ballot"}


def same_person(a, b):
    """Association name vs SoS name: the surname must agree and the first names must
    share an initial ('William Massee, Jr.' vs 'William Massee Jr.' agree)."""
    def toks(x):
        return [t for t in re.findall(r"[a-z]+", x.lower()) if t not in ("jr", "sr", "ii", "iii")]
    ta, tb = toks(a), toks(b)
    if not ta or not tb:
        return False
    # Surname: equal, or one letter off ('Scarbrough' / 'Scarborough' is a real pair).
    if difflib.SequenceMatcher(None, ta[-1], tb[-1]).ratio() < 0.85:
        return False
    # Given name: the association's first name appears among the SoS given names
    # (initial is enough) - the SoS leads with a legal first name ('James Kevin Chaney',
    # 'W.C. "Bill" Massee') where the association uses the name in daily use.
    return any(t[0] == ta[0][0] for t in tb[:-1]) or len(tb) == 1


def build(counties):
    assoc = fetch_association()
    rows, notes = [], []
    for p in counties:
        slug, cname = p["slug"], p["name"]
        a = assoc.get(_norm(re.sub(r"\s+County$", "", cname)))
        s = sos_sheriff(slug)
        if not a:
            notes.append(f"{slug}: not in the association table")
            continue
        entry = {
            "name": short_name(clean_name(a["name"])),
            "role": "Sheriff",
            "seat": "Countywide",
            "party": None,
            "last_elected": None,
            "next_election": None,
            "phone": a["phone"] or None,
            "address": a["address"] or None,
            "source": ASSOC_URL,
        }
        if "error" in s:
            notes.append(f"{slug}: SoS {s['error']} - party and election year left blank")
        elif not same_person(a["name"], s["full"]):
            notes.append(f"{slug}: association says {a['name']!r} but the {SEATING_YEAR} winner "
                         f"was {s['full']!r} ({s['party']}) - party/year left blank; check for a "
                         f"mid-term replacement")
        else:
            entry["party"] = s["party"]
            entry["last_elected"] = SEATING_YEAR
            entry["next_election"] = SEATING_YEAR + TERM_YEARS
            if s["party"] == "Nonpartisan":
                notes.append(f"{slug}: winner has no Republican/Democratic label - confirm party")
            if s["special"]:
                notes.append(f"{slug}: Sheriff race was a special election")
        rows.append((slug, entry))
    return rows, notes


def q(v):
    if v is None:
        return ""
    return '"%s"' % str(v).replace("\\", "\\\\").replace('"', '\\"')


def emit(slug, name, entry):
    out = [f"  - id: {slug}", f"    name: {name}", "    officers:"]
    out.append(f"      - name: {q(entry['name'])}")
    out.append("        role: Sheriff")
    out.append(f"        seat: {q(entry['seat'])}")
    out.append(f"        party: {entry['party'] or ''}".rstrip())
    out.append("        phone: " + (q(entry["phone"]) or '""'))
    out.append("        address: " + (q(entry["address"]) or '""'))
    out.append(f"        last_elected: {entry['last_elected'] or ''}".rstrip())
    out.append(f"        next_election: {entry['next_election'] or ''}".rstrip())
    out.append(f"        source: {q(entry['source'])}")
    return "\n".join(out)


HEADER = """\
# ============================================================================
# COUNTY CONSTITUTIONAL OFFICERS - elected countywide, NOT on the commission
# ============================================================================
# Sheriffs today (Probate Judge, Tax Commissioner, Clerk of Superior Court could
# follow the same shape). Rendered on /local/<slug>/ as "Constitutional officers",
# separately from the commission roster in local_officials.yml: these people do not
# sit on or vote on the board, so they are never mixed into its `members:` list.
#
# Joined to a place by `id` == the places.yml slug (the validator enforces it). A
# county does NOT need a commission roster to appear here.
#
# HUMAN-GATED, like local_officials.yml. scripts/import_sheriffs.py DRAFTS rows from
# the Georgia Sheriffs' Association table (name, address, phone) cross-checked against
# the SoS results for the seating election (party, last_elected). The association page
# is hand-maintained and can lag a mid-term replacement, so confirm against the
# sheriff's office site and record that in `source`. A blank party / last_elected means
# the two sources disagreed or the SoS portal had no race - fill it from a primary
# source rather than guessing. Georgia sheriffs serve four-year terms, elected in
# presidential-year general elections (2024, then 2028).
#
# Per officer: name, role (Sheriff), seat, party (Republican | Democratic |
# Independent | Nonpartisan), phone, address, last_elected, next_election, source.
# Optional: email, full_name, status/statusNote/statusSource/statusDate (same meaning
# as in local_officials.yml). Run scripts/validate_county_officers.py after editing.
# ============================================================================

counties:
"""


def main():
    import yaml
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--write", action="store_true",
                    help="append counties not yet in the file (never edits an existing one)")
    ap.add_argument("--diff", action="store_true",
                    help="compare the committed sheriffs to the association page")
    ap.add_argument("--counties", help="comma-separated slugs to limit the run")
    args = ap.parse_args()

    counties = registry_counties()
    if args.counties:
        want = set(args.counties.split(","))
        counties = [p for p in counties if p["slug"] in want]

    if args.diff:
        with open(OUT_PATH, encoding="utf-8") as f:
            have = yaml.safe_load(f)["counties"]
        assoc = fetch_association()
        names = {p["slug"]: p["name"] for p in counties}
        bad = 0
        for c in have:
            a = assoc.get(_norm(re.sub(r"\s+County$", "", names.get(c["id"], c["name"]))))
            for o in c["officers"]:
                if o["role"] == "Sheriff" and a and not same_person(a["name"], o["name"]):
                    bad += 1
                    print(f"{c['id']}: file has {o['name']!r}, association lists {a['name']!r}")
        print("no differences" if not bad else f"{bad} difference(s)")
        return

    rows, notes = build(counties)
    print(f"{len(rows)} of {len(counties)} registry counties drafted")
    for n in notes:
        print("  note:", n)
    if not args.write:
        return

    existing = set()
    text = ""
    if os.path.exists(OUT_PATH):
        with open(OUT_PATH, encoding="utf-8") as f:
            text = f.read()
        existing = {c["id"] for c in (yaml.safe_load(text) or {}).get("counties", [])}
    else:
        text = HEADER
    names = {p["slug"]: p["name"] for p in counties}
    new = [(s, e) for s, e in rows if s not in existing]
    if not new:
        print("nothing to add")
        return
    body = "\n".join(emit(s, names[s], e) for s, e in new) + "\n"
    if not text.endswith("\n"):
        text += "\n"
    with atomic_write(OUT_PATH, newline="\n") as f:
        f.write(text + body)
    print(f"appended {len(new)} counties to {OUT_PATH}")


if __name__ == "__main__":
    main()
