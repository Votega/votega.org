"""House Clerk financial-disclosure index: an independent check on the trades file.

The kadoa dataset the trades come from carries no stable person ID, so the
generator joins filers to the roster by surname. The Clerk publishes a yearly
index (`<year>FD.zip`, a tab-separated `<year>FD.txt`) of every filing with its
state+district, filing type and DocID. A periodic transaction report's DocID is
the number in a trade's `doc_url` (…/ptr-pdfs/2026/20035821.pdf), so it ties a
trade to a filing independent of any name.

Only the *state* prefix of StateDst is used. The district is whatever the filer
typed on the form and is wrong for McCormick (GA06 on every filing since 2023,
while he represents GA-07), so it is never a key. The roster stays the
authority for district.

audit() is pure (no network) so the checks can be tested on fixtures.
"""

import csv
import io
import re
import zipfile
from datetime import date, datetime, timedelta

from lib.http import fetch_bytes

INDEX_URL = "https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{year}FD.zip"
PTR = "P"
RECENT_DAYS = 90
LIST_CAP = 25  # keep metadata small if something goes badly wrong

_SUFFIX_RE = re.compile(r"\b(jr|sr|ii|iii|iv)\b\.?$", re.IGNORECASE)
_DOC_RE = re.compile(r"/ptr-pdfs/(\d{4})/(\d+)\.pdf", re.IGNORECASE)


def surname(name):
    cleaned = _SUFFIX_RE.sub("", (name or "").strip()).strip()
    parts = cleaned.split()
    return parts[-1].lower() if parts else ""


def parse_index(text):
    """Rows of a Clerk `<year>FD.txt` as dicts (Last, First, FilingType, StateDst, FilingDate, DocID)."""
    return list(csv.DictReader(io.StringIO(text.lstrip("﻿")), delimiter="\t"))


def fetch_index(year):
    """Rows for one year, or None if the zip cannot be fetched or read."""
    raw = fetch_bytes(INDEX_URL.format(year=year), label=f"Clerk {year}FD index")
    if not raw:
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            name = next(n for n in z.namelist() if n.lower().endswith(".txt"))
            return parse_index(z.read(name).decode("utf-8-sig", errors="replace"))
    except (zipfile.BadZipFile, StopIteration, KeyError):
        return None


def doc_ref(doc_url):
    """(year, docId) from a House PTR url, else None (e.g. a Senate eFD link)."""
    m = _DOC_RE.search(doc_url or "")
    return (int(m.group(1)), m.group(2)) if m else None


def _iso(us_date):
    try:
        return datetime.strptime(us_date, "%m/%d/%Y").date().isoformat()
    except (TypeError, ValueError):
        return ""


def audit(by_member, departed_names, rows, years, today=None):
    """Cross-check published trades against the Clerk index.

    by_member       the published byMember dict
    departed_names  full names of GA filers dropped for not being in the roster
    rows            Clerk index rows for `years` (list of ints actually fetched)
    Returns the dict stored as metadata.clerkCheck.
    """
    today = today or date.today()
    cutoff = (today - timedelta(days=RECENT_DAYS)).isoformat()
    index = {r["DocID"]: r for r in rows}
    ga_ptr = [r for r in rows
              if (r.get("StateDst") or "").upper().startswith("GA")
              and r.get("FilingType") == PTR]

    published = {}   # docId -> member name
    in_years = {}    # docId -> member name, only filings in an indexed year
    for name, m in by_member.items():
        for t in m.get("trades", []):
            ref = doc_ref(t.get("doc_url"))
            if not ref:
                continue
            published.setdefault(ref[1], name)
            if ref[0] in years:
                in_years.setdefault(ref[1], name)

    wrong_state, unverified, verified = [], [], 0
    for doc, name in sorted(in_years.items()):
        row = index.get(doc)
        if row is None:
            unverified.append({"docId": doc, "member": name})
        elif not (row.get("StateDst") or "").upper().startswith("GA"):
            wrong_state.append({"docId": doc, "member": name,
                                "stateDst": row.get("StateDst")})
        else:
            verified += 1

    departed = {surname(n) for n in departed_names}
    missing, departed_recent = [], {}
    for r in ga_ptr:
        doc = r["DocID"]
        if doc in published:
            continue
        who = f"{(r.get('First') or '').strip()} {(r.get('Last') or '').strip()}".strip()
        filed = _iso(r.get("FilingDate"))
        if surname(r.get("Last")) in departed:
            if filed >= cutoff:
                e = departed_recent.setdefault(who, {"name": who, "filings": 0,
                                                    "latest": "", "docIds": []})
                e["filings"] += 1
                e["latest"] = max(e["latest"], filed)
                e["docIds"].append(doc)
            continue
        missing.append({"docId": doc, "name": who, "filed": filed,
                        "stateDst": r.get("StateDst")})

    return {
        "status": "ok",
        "years": sorted(years),
        "gaPtrFilings": len(ga_ptr),
        "verifiedDocs": verified,
        "wrongState": wrong_state[:LIST_CAP],
        "unverifiedCount": len(unverified),
        "unverified": unverified[:LIST_CAP],
        "missingFilings": sorted(missing, key=lambda x: x["filed"], reverse=True)[:LIST_CAP],
        "missingCount": len(missing),
        "departedRecent": sorted(departed_recent.values(), key=lambda x: x["name"]),
    }


def unavailable(reason):
    return {"status": "unavailable", "reason": reason}
