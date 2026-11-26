#!/usr/bin/env python3
"""Cross-check published GA roll-call results against legis.ga.gov's status history.

A result is derived from the tally (lib/ga_vote_rules.py). This asks the official
record instead: for each roll call near a threshold, GetLegislationDetail's
StatusHistory lists what the chamber recorded that day ("House Third Reading Lost",
"Senate Passed/Adopted", "House Conference Committee Report Adopted", ...). A Pass the
chamber recorded as lost, or a Fail it recorded as passed, is a DISAGREEMENT.

Matching is by bill, chamber and day. When a chamber took several roll calls on one
bill that day (a lost vote, a reconsideration, a re-vote), the published votes and the
official outcomes are paired in time order if their counts agree; otherwise the group
is reported as AMBIGUOUS. A roll call with no same-day outcome in the history is
UNVERIFIED. Neither fails the run; disagreements do (exit 1) unless --warn-only.

Which roll calls: those whose yeas are within --margin of a majority of seats (91 / 29),
and those short of two-thirds (120 / 38, + margin) on a resolution or a bill titled
like a property-tax exemption; every roll call with --all.
One GetLegislationDetail call per distinct bill checked.

Accepts any file whose `votes` is the published votes map (ga-member-votes.json,
sessions/<biennium>/votes.json, an --archive file) or a ga-bills.json (`bills[]` with
passageVotes).

Usage:
  python scripts/check_ga_vote_status.py FILE.json [--margin 10] [--all]
         [--session 2025_26] [--warn-only] [--report OUT.json]
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.atomic_io import write_json_atomic  # noqa: E402
from lib.ga_vote_results import legislation_id, two_thirds_candidate_ids  # noqa: E402
from lib.ga_vote_rules import chamber_key, official_exception, required_yeas  # noqa: E402

#: Outcome events in a status description. "Lost" covers "Third Reading Lost",
#: "Conference Committee Lost" and "Lost Reconsidered" (lost again on reconsideration).
#: \bAgreed\b does not match "Disagreed", which records a motion, not an outcome.
_LOST_RE = re.compile(r"\bLost\b", re.IGNORECASE)
_PASSED_RE = re.compile(r"Passed/Adopted|\bAgreed\b|Report Adopted|\bAdopted\b", re.IGNORECASE)
_NEUTRAL_RE = re.compile(r"Committee Favorably|Committee Appointed|Notice to Reconsider",
                         re.IGNORECASE)


def outcome_of(description):
    """'pass' / 'fail' / None for one StatusListing description."""
    d = description or ""
    if _NEUTRAL_RE.search(d):
        return None
    if _LOST_RE.search(d):
        return "fail"
    if _PASSED_RE.search(d):
        return "pass"
    return None


def status_chamber(description):
    d = (description or "").strip().lower()
    return "lower" if d.startswith("house") else "upper" if d.startswith("senate") else None


def official_outcomes(history, chamber, day):
    """[(datetime-string, 'pass'|'fail', description)] the chamber recorded on `day`."""
    out = []
    for row in history or []:
        if not (row.get("date") or "").startswith(day):
            continue
        if status_chamber(row.get("description")) != chamber:
            continue
        o = outcome_of(row.get("description"))
        if o:
            out.append((row["date"], o, row["description"]))
    return sorted(out)


def _minutes(t):
    try:
        dt = datetime.strptime((t or "").strip(), "%I:%M %p")
        return dt.hour * 60 + dt.minute
    except ValueError:
        return None


def pair_outcomes(items, official, slack=2):
    """Pair same-day roll calls (sorted by time) with the chamber's official outcomes.

    Equal counts pair in order. The clerk can log several outcomes together after the
    votes (2017 SB 1: roll calls at 10:39 and 10:42 PM, "Third Reading Lost" and "Lost
    Reconsidered" at 22:44 and 22:45), so times alone would misplace them.
    Otherwise, with times on every roll call, each outcome belongs to the latest roll
    call taken at or before it (`slack` minutes for clock skew), and only the first
    outcome after a roll call counts. A roll call no outcome follows is returned as
    unmatched: a chamber can lose a concurrence vote without logging "Lost" and then
    pass a re-vote (2017 HB 125 at 27-14, then 32-15). An outcome no published roll call
    precedes came from a vote the passage classifier did not keep.
    Without times and with unequal counts: (None, items), ambiguous.
    Returns (pairs [((vid, vote), outcome)], unmatched [(vid, vote)])."""
    if len(official) == len(items):
        return [(it, o[1]) for it, o in zip(items, official)], []
    times = [_minutes(v.get("time")) for _, v in items]
    if all(t is not None for t in times):
        matched = {}
        for stamp, outcome, _desc in official:
            try:
                at = int(stamp[11:13]) * 60 + int(stamp[14:16])
            except ValueError:
                continue
            before = [i for i, t in enumerate(times) if t <= at + slack]
            if before and before[-1] not in matched:
                matched[before[-1]] = outcome
        return ([(items[i], o) for i, o in sorted(matched.items())],
                [it for i, it in enumerate(items) if i not in matched])
    return None, items


def load_votes(doc):
    """{voteId: vote} from a votes file, or synthesised from ga-bills.json bills."""
    if isinstance(doc.get("votes"), dict):
        return doc["votes"]
    out = {}
    for b in doc.get("bills") or []:
        for i, pv in enumerate(b.get("passageVotes") or []):
            out["%s#%d" % (b.get("legislationId"), i)] = {
                "bill": b.get("identifier"), "billUrl": b.get("billUrl"),
                "session": b.get("session"), "chamber": pv.get("chamber"),
                "date": pv.get("date"), "motionText": pv.get("motionText"),
                "yea": pv.get("yea"), "nay": pv.get("nay"),
                "result": (pv.get("result") or "").capitalize(),
                "_abstract": b.get("abstract"), "_billType": b.get("billType")}
    return out


def maybe_two_thirds(v):
    """True when `v` is on a resolution or a bill titled like a property-tax exemption
    (the same filter the abstract lookup uses)."""
    return bool(two_thirds_candidate_ids({"v": v}))


def is_candidate(v, margin):
    yea = v.get("yea")
    if yea is None or chamber_key(v.get("chamber")) is None:
        return False
    majority = required_yeas(v["chamber"], False, v.get("motionText"))
    if majority is not None and abs(yea - majority) <= margin:
        return True
    # Whether a bill needs two-thirds depends on an abstract this file may not carry, so
    # any roll call short of two-thirds (+ margin) on a resolution or a bill whose title
    # reads like a property-tax exemption is checked.
    two_thirds = required_yeas(v["chamber"], True, v.get("motionText"))
    return (two_thirds is not None and yea < two_thirds + margin
            and maybe_two_thirds(v))


def check(votes, fetch, margin=10, check_all=False, session=None, log=print):
    """Compare published results with the status history. Returns a report dict."""
    picked = {vid: v for vid, v in votes.items()
              if (session is None or v.get("session") == session)
              and (check_all or is_candidate(v, margin))}
    def key_of(v):
        lid = legislation_id(v)
        return None if lid is None else (lid, chamber_key(v.get("chamber")),
                                         (v.get("date") or "")[:10])
    # A picked roll call brings every roll call on that bill, chamber and day with it:
    # pairing by time needs the whole day, close or not.
    keys = {key_of(v) for v in picked.values()} - {None}
    groups = {}
    for vid, v in votes.items():
        k = key_of(v)
        if k in keys:
            groups.setdefault(k, []).append((vid, v))

    records, failed_fetch = {}, []
    for lid in sorted({k[0] for k in groups}):
        rec = fetch(lid)
        if rec is None:
            failed_fetch.append(lid)
        records[lid] = rec

    report = {"checked": 0, "agree": 0, "disagree": [], "ambiguous": [], "unverified": [],
              "officialExceptions": [], "fetchFailed": failed_fetch}
    for (lid, chamber, day), items in sorted(groups.items(), key=lambda kv: kv[0][2]):
        rec = records.get(lid)
        if rec is None:
            continue
        items.sort(key=lambda it: (_minutes(it[1].get("time")) or 0,
                                   it[1].get("rollNumber") or 0, it[0]))
        official = official_outcomes(rec.get("statusHistory"), chamber, day)
        report["checked"] += len(items)

        def row(vid, v, want=None, why=None):
            r = {"voteId": vid, "bill": v.get("bill"), "session": v.get("session"),
                 "chamber": chamber, "date": day, "time": v.get("time"),
                 "motionText": v.get("motionText"), "yea": v.get("yea"),
                 "nay": v.get("nay"), "published": v.get("result"),
                 "official": [o[2] for o in official]}
            if want:
                r["officialResult"] = want
            if why:
                r["note"] = why
            return r

        for vid, v in items:
            pinned = official_exception(lid, chamber, day, v.get("yea"), v.get("nay"))
            if pinned:
                report["officialExceptions"].append(row(vid, v, why=pinned[1]))
        if not official:
            report["unverified"].extend(row(vid, v) for vid, v in items)
            continue
        pairs, unmatched = pair_outcomes(items, official)
        if pairs is None:
            report["ambiguous"].extend(row(vid, v) for vid, v in items)
            continue
        report["unverified"].extend(row(vid, v) for vid, v in unmatched)
        for (vid, v), want in pairs:
            if (v.get("result") or "").lower() == want:
                report["agree"] += 1
            else:
                report["disagree"].append(row(vid, v, want))

    log("Checked %d roll calls on %d bills: %d agree, %d DISAGREE, %d ambiguous, "
        "%d unverified, %d pinned exceptions%s"
        % (report["checked"], len(records), report["agree"], len(report["disagree"]),
           len(report["ambiguous"]), len(report["unverified"]),
           len(report["officialExceptions"]),
           (", %d lookups FAILED" % len(failed_fetch)) if failed_fetch else ""))
    for label in ("disagree", "ambiguous"):
        for r in report[label]:
            log("  %s %s %s %s %s %s %s-%s published %s; official: %s"
                % (label.upper(), r["session"], r["date"], r["bill"], r["chamber"],
                   r["voteId"], r["yea"], r["nay"], r["published"], "; ".join(r["official"])))
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("file")
    ap.add_argument("--margin", type=int, default=10,
                    help="check roll calls whose yeas are within this many of the required "
                         "yeas (default %(default)s)")
    ap.add_argument("--all", action="store_true", help="check every roll call")
    ap.add_argument("--session", default=None, help="only this session tag")
    ap.add_argument("--warn-only", action="store_true",
                    help="report disagreements as warnings and exit 0")
    ap.add_argument("--report", default=None, help="write the full report as JSON")
    args = ap.parse_args(argv)

    with open(args.file, encoding="utf-8") as fh:
        doc = json.load(fh)
    from lib.ga_soap import get_legislation_record
    report = check(load_votes(doc), get_legislation_record, args.margin, args.all,
                   args.session)
    if args.report:
        write_json_atomic(args.report, report, indent=2)
    if report["fetchFailed"]:
        print("::warning::%d legis.ga.gov lookups failed; those bills were not checked"
              % len(report["fetchFailed"]))
    if report["disagree"]:
        msg = ("%d published result(s) disagree with legis.ga.gov's status history; see "
               "above. Fix the rule in lib/ga_vote_rules.py, or pin an officially-passed "
               "roll call in OFFICIAL_PASSED." % len(report["disagree"]))
        if args.warn_only:
            print("::warning::" + msg)
            return 0
        print("ERROR: " + msg, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
