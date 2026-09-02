#!/usr/bin/env python3
"""Build compact server-render sidecars in _data/rendered/ from assets/data/*.json.

GitHub Pages builds Jekyll in safe mode (no custom plugins), and Liquid can only
read data from _data/ — not the large runtime JSON in assets/data/. This script
runs at deploy time (see .github/workflows/deploy-pages.yml), reading the runtime
JSON and emitting small, page-shaped sidecars so the data pages can server-render
a visible "last updated" date plus a meaningful, crawlable content summary in the
initial HTML. The full interactive tables still load client-side from assets/data.

Sidecars are build artifacts (git-ignored). Each is:
    { "updated": "August 30, 2026", "updatedISO": "2026-08-30",
      "count": <int>, "source": <str|null>, "rows": [ {..capped..} ] }

Pages must guard on presence ({% if site.data.rendered.X %}) so a missing or
skipped sidecar simply falls back to the existing client-rendered behavior.

Run locally before `jekyll serve` to preview the server-rendered blocks:
    python3 scripts/build_render_data.py
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(ROOT, "assets", "data")
OUT_DIR = os.path.join(ROOT, "_data", "rendered")


def _get(obj, dotted, default=None):
    """Fetch a value by dotted path, tolerating missing keys."""
    cur = obj
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return default
    return cur


def _fmt_date(raw):
    """Normalize an ISO date/datetime string to (human, iso-date). Returns (raw, None) on failure."""
    if not raw or not isinstance(raw, str):
        return (raw, None)
    s = raw.strip().replace("Z", "+00:00")
    dt = None
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y"):
            try:
                dt = datetime.strptime(raw.strip()[:10], fmt)
                break
            except ValueError:
                continue
    if dt is None:
        return (raw, None)
    d = dt.date() if isinstance(dt, datetime) else dt
    # Cross-platform day without leading zero.
    human = "%s %d, %d" % (d.strftime("%B"), d.day, d.year)
    return (human, d.isoformat())


def _pick(item, fields):
    """Project selected top-level fields from a dict row (dropping empties keeps sidecars small)."""
    out = {}
    for f in fields:
        v = item.get(f) if isinstance(item, dict) else None
        if v is None or v == "" or v == []:
            continue
        # Trim long free text so the sidecar stays compact; pages don't need full abstracts.
        if isinstance(v, str) and len(v) > 240:
            v = v[:237].rstrip() + "…"
        out[f] = v
    return out


def rows_from_list(data, list_key, fields, cap):
    lst = _get(data, list_key, []) or []
    if not isinstance(lst, list):
        return [], 0
    total = len(lst)
    rows = [_pick(x, fields) for x in lst[:cap]]
    return rows, total


def build_elections(data, cfg):
    """races.json has no per-race office label (it's nested in phases), so summarize
    by level instead of listing races — a crawlable, honest overview for /elections."""
    races = data.get("races", []) or []
    labels = {
        "state": "State legislative", "state-judicial": "State judicial",
        "federal": "Federal", "state-executive": "State executive", "local": "Local",
    }
    counts = {}
    for r in races:
        lvl = r.get("level")
        counts[lvl] = counts.get(lvl, 0) + 1
    order = ["federal", "state-executive", "state", "state-judicial", "local"]
    rows = [{"label": labels.get(k, k or "Other"), "count": counts[k]}
            for k in order if k in counts]
    rows += [{"label": labels.get(k, k), "count": v} for k, v in counts.items() if k not in order]
    human, iso = _fmt_date(_get(data, cfg["date"]))
    return {"updated": human, "updatedISO": iso, "count": len(races),
            "shown": len(rows), "source": None, "rows": rows}


def build_majority(data, cfg):
    """Compute per-chamber party balance from ga-members.json for the majority tracker."""
    members = data.get("members", []) or []
    chambers = {}
    for m in members:
        ch = m.get("chamber")
        if ch in (None, "", "executive"):
            continue
        party = (m.get("party") or "").lower()
        c = chambers.setdefault(ch, {"chamber": ch, "republican": 0, "democratic": 0, "other": 0, "total": 0})
        if party.startswith("rep"):
            c["republican"] += 1
        elif party.startswith("dem"):
            c["democratic"] += 1
        else:
            c["other"] += 1
        c["total"] += 1
    order = ["Senate", "House of Representatives"]
    rows = [chambers[k] for k in order if k in chambers]
    rows += [v for k, v in chambers.items() if k not in order]
    human, iso = _fmt_date(_get(data, cfg["date"]))
    return {"updated": human, "updatedISO": iso, "count": sum(r["total"] for r in rows),
            "shown": len(rows), "source": _get(data, "metadata.source"), "rows": rows}


def make_freshness_builder(extra_srcs, date_paths):
    """Build a rows-less 'data last updated' sidecar for interactive tools that have
    no single list to render. Reports the most recent date across several source files."""
    def _builder(data, cfg):
        best = None  # (iso, human)
        for path, data_obj in [(cfg["src"], data)] + [(s, None) for s in extra_srcs]:
            if data_obj is None:
                full = os.path.join(SRC_DIR, path)
                if not os.path.exists(full):
                    continue
                with open(full, encoding="utf-8") as fh:
                    data_obj = json.load(fh)
            for dp in date_paths:
                human, iso = _fmt_date(_get(data_obj, dp))
                if iso and (best is None or iso > best[0]):
                    best = (iso, human)
                    break
        if best is None:
            return None
        return {"updated": best[1], "updatedISO": best[0], "count": None,
                "shown": 0, "source": None, "rows": []}
    return _builder


def rows_from_bymember_trades(data, list_key, fields, cap):
    """ga-congress-trades stores byMember as a name-keyed dict; flatten to rows sorted by tradeCount."""
    bm = _get(data, list_key, {}) or {}
    if not isinstance(bm, dict):
        return [], 0
    rows = []
    for name, v in bm.items():
        if not isinstance(v, dict):
            continue
        row = {"name": name}
        row.update(_pick(v, fields))
        rows.append(row)
    rows.sort(key=lambda r: r.get("tradeCount", 0), reverse=True)
    total = len(rows)
    return rows[:cap], total


# name -> config. `transform` defaults to rows_from_list.
CONFIG = {
    "ga_executive": {
        "src": "ga-executive.json", "date": "metadata.updatedAt", "list": "officials",
        "fields": ["title", "name", "party", "termNote"], "cap": 25,
    },
    "supreme_court": {
        "src": "supreme-court.json", "date": "metadata.generatedAt", "list": "justices",
        "fields": ["name", "title", "appointedBy", "confirmationDate", "homeState"], "cap": 12,
    },
    "scotus_decisions": {
        "src": "scotus-decisions.json", "date": "metadata.generatedAt", "count": "metadata.count",
        "list": "cases", "fields": ["name", "term", "decidedDate", "winningParty", "decisionType"], "cap": 60,
    },
    "ga_ballot_measures": {
        "src": "ga-ballot-measures.json", "date": "metadata.generatedAt", "list": "measures",
        "fields": ["title", "status", "type", "summary", "subjects"], "cap": 25,
    },
    "ga_party_unity": {
        "src": "ga-party-unity.json", "date": "metadata.generatedAt", "list": "members",
        "fields": ["name", "party", "chamber", "district", "partyUnity", "votedWithParty", "totalRollCalls"],
        "cap": 260,
    },
    "ga_congress_trades": {
        "src": "ga-congress-trades.json", "date": "metadata.generatedAt", "count": "metadata.totalTrades",
        "list": "byMember", "transform": rows_from_bymember_trades,
        "fields": ["party", "chamber", "office", "state", "tradeCount", "purchases", "sales", "lateFilings"],
        "cap": 20,
    },
    "ga_bills": {
        "src": "ga-bills.json", "date": "metadata.generatedAt", "list": "bills",
        "fields": ["identifier", "billType", "chamber", "title", "status", "statusDate"], "cap": 100,
    },
    "ga_executive_orders": {
        "src": "ga-executive-orders-2026.json", "date": "metadata.updatedAt", "count": "metadata.count",
        "list": "orders", "fields": ["date", "number", "title", "category"], "cap": 60,
    },
    "ga_election_calendar": {
        "src": "ga-election-calendar.json", "date": "metadata.generatedAt", "list": "elections",
        "fields": ["name", "type", "date", "earlyVotingStart", "earlyVotingEnd", "registrationDeadline"],
        "cap": 12,
    },
    "elections": {
        "src": "races.json", "date": "updatedAt", "builder": build_elections,
    },
    "ga_majority": {
        "src": "ga-members.json", "date": "metadata.generatedAt", "builder": build_majority,
    },
    # Interactive lookup tools: no list to render, just a "data last updated" signal
    # from the most recent of their underlying sources.
    "find_my_reps": {
        "src": "ga-members.json",
        "builder": make_freshness_builder(
            ["current-members.json"],
            ["metadata.generatedAt", "metadata.updatedAt", "updatedAt"],
        ),
    },
    "sample_ballot": {
        "src": "races.json",
        "builder": make_freshness_builder(
            ["ga-members.json", "current-members.json", "ga-ballot-measures.json", "ga-election-calendar.json"],
            ["updatedAt", "metadata.generatedAt", "metadata.updatedAt"],
        ),
    },
}


def build_one(name, cfg):
    path = os.path.join(SRC_DIR, cfg["src"])
    if not os.path.exists(path):
        print(f"  skip {name}: {cfg['src']} not found", file=sys.stderr)
        return None
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)

    builder = cfg.get("builder")
    if builder is not None:
        return builder(data, cfg)

    transform = cfg.get("transform", rows_from_list)
    rows, total = transform(data, cfg["list"], cfg["fields"], cfg["cap"])
    if "count" in cfg:
        total = _get(data, cfg["count"], total)

    human, iso = _fmt_date(_get(data, cfg["date"]))
    return {
        "updated": human,
        "updatedISO": iso,
        "count": total,
        "shown": len(rows),
        "source": _get(data, "metadata.source"),
        "rows": rows,
    }


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    written = 0
    for name, cfg in CONFIG.items():
        try:
            payload = build_one(name, cfg)
        except Exception as exc:  # never fail the deploy over one bad dataset
            print(f"  skip {name}: {exc}", file=sys.stderr)
            continue
        if payload is None:
            continue
        out_path = os.path.join(OUT_DIR, f"{name}.json")
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
        print(f"  wrote _data/rendered/{name}.json  ({payload['shown']}/{payload['count']} rows, updated {payload['updated']})")
        written += 1
    print(f"build_render_data: {written}/{len(CONFIG)} sidecars written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
