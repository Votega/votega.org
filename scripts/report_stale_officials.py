#!/usr/bin/env python3
"""Report which local-officials rosters are due for re-verification.

Officials are hand-curated with no upstream API (see LOCAL-GOVERNMENT-IA.md), so
unlike the weekly meetings scrape they never refresh themselves. This turns
"remember to re-check after an election" into a dated worklist: it reads
_data/local_officials.yml and flags

  - members whose `next_election` year has already passed (the seat may have
    turned over — re-verify the whole roster), and
  - a global staleness note when meta.last_reviewed is older than --max-age-days.

It prints a Markdown report to stdout and never fails the build (it is a nudge,
not a gate). The scheduled report-stale-officials workflow feeds that report into
a GitHub issue; run it locally any time with no arguments.

Usage:
    python scripts/report_stale_officials.py [--max-age-days 365]
"""

import argparse
import sys
from datetime import date, datetime

import yaml

DATA_PATH = "_data/local_officials.yml"


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


def build_report(data, max_age_days):
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

    lines = []
    reviewed = parse_reviewed(data.get("meta"))
    if reviewed is None:
        lines.append("- ⚠️ `meta.last_reviewed` is not set — set it after your next review.")
    elif (today - reviewed).days > max_age_days:
        lines.append(f"- ⚠️ Whole roster last reviewed **{reviewed.isoformat()}** "
                     f"({(today - reviewed).days} days ago, over the {max_age_days}-day threshold).")

    if not stale_rosters and not lines:
        return f"✅ No local-officials rosters are due for re-verification (checked {today.isoformat()})."

    out = [f"### Local officials due for re-verification — {today.isoformat()}", ""]
    out += lines
    if stale_rosters:
        out.append("")
        for j, past in stale_rosters:
            out.append(f"#### {j.get('name', j.get('id'))} (`{j.get('id')}`) — /local/{j.get('id')}/")
            for m in past:
                src = m.get("source") or ""
                src_md = f" — [source]({src})" if src else " — ⚠️ no source on file"
                out.append(f"- {m.get('role', '?')}: **{m.get('name') or 'Name TBD'}** "
                           f"({m.get('seat', '')}) — next election was "
                           f"{m['next_election']}, now past{src_md}")
            out.append("")
    out.append("After confirming each seat against its primary source, update "
               "`_data/local_officials.yml` and bump `meta.last_reviewed`.")
    return "\n".join(out).rstrip() + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-age-days", type=int, default=365)
    args = ap.parse_args()

    try:
        data = load()
    except FileNotFoundError:
        print(f"{DATA_PATH} not found", file=sys.stderr)
        return 0

    print(build_report(data, args.max_age_days))
    return 0


if __name__ == "__main__":
    sys.exit(main())
