#!/usr/bin/env python3
"""Report which local-officials rosters are due for re-verification.

Officials are hand-curated with no upstream API (see LOCAL-GOVERNMENT-IA.md), so
unlike the weekly meetings scrape they never refresh themselves. This turns
"remember to re-check after an election" into a dated worklist: it reads
_data/local_officials.yml and flags

  - members whose `next_election` year has already passed (the seat may have
    turned over — re-verify the whole roster),
  - a global staleness note when meta.last_reviewed is older than --max-age-days, and
  - EXECUTIVE-ORDER SIGNALS: the governor fills county-commission vacancies by
    order and calls special elections by writ, mid-term, which no election-results
    source can see. We scan the committed ga-executive-orders-*.json for EOs that
    name a curated county + a commission office + vacancy/election language and are
    dated after that roster's last review — each is a "this seat may have changed"
    nudge with the EO as its primary source. (This is exactly how we'd have caught
    Newton D3: elected Nov 2024, then a March-2025 EO appointed a replacement.)

It prints a Markdown report to stdout and never fails the build (it is a nudge,
not a gate). The scheduled report-stale-officials workflow feeds that report into
a GitHub issue; run it locally any time with no arguments.

Usage:
    python scripts/report_stale_officials.py [--max-age-days 365] [--no-eo]
"""

import argparse
import glob
import json
import re
import sys
from datetime import date, datetime

import yaml

DATA_PATH = "_data/local_officials.yml"
EO_GLOB = "assets/data/ga-executive-orders-*.json"

# An EO is a roster-change signal when its title names <County> County, a
# commission office, AND vacancy/election language. Requiring all three keeps out
# the noise (routine county mentions, the many state-board appointments, and the
# legislative "District N seat in the Georgia House" writs that carry no county).
# Match the ACTUAL office, not the standalone word "commission" — otherwise
# "Appointing the Review Commission to examine the indictment of <a Court Clerk>"
# false-matches. Requiring commissioner / board of commissioners / commission
# chair / chairman keeps the county-commission signals (including indictment
# EOs that name a commissioner or chairman) and drops the Court-Clerk noise.
_EO_OFFICE = re.compile(r"commissioner|board of comm|commission chair|chairman|chairwoman", re.I)
_EO_SIGNAL = re.compile(
    r"vacancy in the office of|writ of election|special election|"
    r"proclamation of election|appoint",
    re.I,
)


def load():
    with open(DATA_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def parse_reviewed(meta):
    raw = (meta or {}).get("last_reviewed")
    if raw in (None, ""):
        return None
    if isinstance(raw, date):
        return raw
    try:
        return datetime.strptime(str(raw), "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_iso(raw):
    try:
        return datetime.strptime(str(raw)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def load_eo_orders():
    """Flatten all committed ga-executive-orders-*.json into {date,number,title,url}.
    Local files only — no network, safe to run in CI."""
    orders = []
    for f in sorted(glob.glob(EO_GLOB)):
        try:
            with open(f, encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        for o in (doc.get("orders") or []):
            title = (o.get("title") or "").strip()
            if title:
                orders.append({
                    "date": _parse_iso(o.get("date")),
                    "number": o.get("number"),
                    "title": title,
                    "url": o.get("url") or o.get("archiveUrl"),
                })
    return orders


def county_name_of(juris):
    """The bare county name for matching ('DeKalb', 'Newton')."""
    c = juris.get("county")
    if c:
        return str(c).strip()
    return re.sub(r"\s+County$", "", juris.get("name") or "").strip()


def eo_signals_for(juris, orders, since):
    """EOs that name this county + a commission office + vacancy/election language,
    dated strictly after `since` (already-reviewed EOs are assumed incorporated),
    newest first. Only counties — the governor does not appoint city officials."""
    if juris.get("type") != "county":
        return []
    cname = county_name_of(juris)
    if not cname:
        return []
    cpat = re.compile(rf"\b{re.escape(cname)}\s+county\b", re.I)
    hits = []
    for o in orders:
        t = o["title"]
        if not (cpat.search(t) and _EO_OFFICE.search(t) and _EO_SIGNAL.search(t)):
            continue
        if since and o["date"] and o["date"] <= since:
            continue
        hits.append(o)
    hits.sort(key=lambda o: o["date"] or date.min, reverse=True)
    return hits


def build_report(data, max_age_days, eo_orders=None, eo_since=None):
    today = date.today()
    jurisdictions = data.get("jurisdictions") or []

    stale_rosters = []  # (juris, [members past next_election])
    for j in jurisdictions:
        if not isinstance(j, dict):
            continue
        past = [
            m for m in (j.get("members") or [])
            if isinstance(m, dict)
            and isinstance(m.get("next_election"), int)
            and m["next_election"] < today.year
        ]
        if past:
            stale_rosters.append((j, past))

    reviewed = parse_reviewed(data.get("meta"))

    # EO signals — cutoff defaults to last_reviewed; if never reviewed, look back
    # ~2 years so a fresh repo still surfaces recent orders instead of the archive.
    eo_by_juris = []
    if eo_orders:
        cutoff = eo_since if eo_since is not None else (reviewed or date(today.year - 2, 1, 1))
        for j in jurisdictions:
            if not isinstance(j, dict):
                continue
            eos = eo_signals_for(j, eo_orders, cutoff)
            if eos:
                eo_by_juris.append((j, eos))

    lines = []
    if reviewed is None:
        lines.append("- (!) `meta.last_reviewed` is not set — set it after your next review.")
    elif (today - reviewed).days > max_age_days:
        lines.append(f"- (!) Whole roster last reviewed **{reviewed.isoformat()}** "
                     f"({(today - reviewed).days} days ago, over the {max_age_days}-day threshold).")

    if not stale_rosters and not eo_by_juris and not lines:
        return f"OK — no local-officials rosters are due for re-verification (checked {today.isoformat()})."

    out = [f"### Local officials due for re-verification — {today.isoformat()}", ""]
    out += lines
    if stale_rosters:
        out.append("")
        out.append("#### Past next_election")
        for j, past in stale_rosters:
            out.append(f"**{j.get('name', j.get('id'))} (`{j.get('id')}`) — /local/{j.get('id')}/**")
            for m in past:
                src = m.get("source") or ""
                src_md = f" — [source]({src})" if src else " — (!) no source on file"
                out.append(f"- {m.get('role', '?')}: **{m.get('name') or 'Name TBD'}** "
                           f"({m.get('seat', '')}) — next election was "
                           f"{m['next_election']}, now past{src_md}")
            out.append("")
    if eo_by_juris:
        out.append("")
        out.append("#### Executive-order signals (a governor's order may have changed a seat)")
        out.append("_Vacancy appointments / special-election writs the results data can't see. "
                   "Confirm whether each is already reflected in the roster; if it changed a seat, "
                   "update it and cite the EO as the source._")
        out.append("")
        for j, eos in eo_by_juris:
            out.append(f"**{j.get('name', j.get('id'))} (`{j.get('id')}`) — /local/{j.get('id')}/**")
            for o in eos:
                d = o["date"].isoformat() if o["date"] else "?"
                link = f"[EO {o['number']}]({o['url']})" if o.get("url") else f"EO {o['number']}"
                out.append(f"- {d} — {link}: {o['title']}")
            out.append("")
    out.append("After confirming each seat against its primary source, update "
               "`_data/local_officials.yml` and bump `meta.last_reviewed`.")
    return "\n".join(out).rstrip() + "\n"


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # EO titles carry non-cp1252 chars
    except (AttributeError, ValueError):
        pass

    ap = argparse.ArgumentParser()
    ap.add_argument("--max-age-days", type=int, default=365)
    ap.add_argument("--no-eo", action="store_true", help="skip the executive-order scan")
    ap.add_argument("--eo-since", help="EO cutoff date YYYY-MM-DD (default: meta.last_reviewed)")
    args = ap.parse_args()

    try:
        data = load()
    except FileNotFoundError:
        print(f"{DATA_PATH} not found", file=sys.stderr)
        return 0

    eo_orders = None if args.no_eo else load_eo_orders()
    eo_since = _parse_iso(args.eo_since) if args.eo_since else None
    print(build_report(data, args.max_age_days, eo_orders=eo_orders, eo_since=eo_since))
    return 0


if __name__ == "__main__":
    sys.exit(main())
