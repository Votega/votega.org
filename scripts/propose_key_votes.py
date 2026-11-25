#!/usr/bin/env python3
"""Propose Key Votes candidates for the owner to approve — one process for state and federal.

Key Votes stay HAND-CURATED (owner decision, 2026-11-23). This tool never edits a
curated list on its own: it ranks recent final-passage roll calls on mechanical,
documented signals, writes a proposals file and a readable report, and a separate,
explicit `--approve` step appends the owner's picks to the curated list.

    assets/data/curated-ga-bills.json        <- GA General Assembly  ("ga": [...])
    assets/data/curated-federal-bills.json   <- GA congressional delegation ("bills": [...])

Both lists start empty at their rollovers (federal Jan 3, GA Jan 11, 2027) and the Key
Votes tab stays hidden until a list has entries (D15, docs/ga-biennium-rollover-decisions.md).
This tool is how the lists fill up as the 120th Congress and the 2027 session vote.

────────────────────────────────────────────────────────────────────────────────
COMMANDS

  Propose (what a scheduled weekly task runs; read-only against committed data):
      python scripts/propose_key_votes.py --scope both --days 14

  Approve the owner's picks (the ONLY step that writes a curated list):
      python scripts/propose_key_votes.py --approve ga-2027_28-hb12,federal-120-hr44

  Dismiss candidates the owner does not want to see again (recorded in
  _data/key_vote_decisions.json, which is read by every later run):
      python scripts/propose_key_votes.py --dismiss ga-2027_28-hb99 --note "local in effect"

SCHEDULED TASK (weekly) — run the propose command above from a fresh checkout of
`main`, then send the owner the contents of `out/key-vote-proposals/report.md` (the
combined report; the two per-scope files `ga.md` / `federal.md` sit beside it) and
the approve command with the candidate ids they pick. Send nothing but that report:
the tool is read-only, so a quiet week yields a short "no candidates" report and the
task should still send it. Never run `--approve` from the schedule; approval is the
owner's decision. See docs/RECURRING-TASKS.md.

────────────────────────────────────────────────────────────────────────────────
WHAT IS A CANDIDATE

A BILL (or constitutional-amendment resolution) with a final-passage roll call in the
window. For GA a final-passage roll call is what lib/ga_passage.native_is_passage
calls passage, minus the local-calendar batches that pass single-county acts en masse;
ceremonial resolutions are skipped. For federal it is passage, concurrence or
suspend-and-pass on an H.R., S., H.J.Res. or S.J.Res.; simple and concurrent
resolutions, cloture, amendments and nominations are skipped. Per chamber the
operative vote is the latest one (same rule generate_curated_ga_bills.py uses), so a
bill the owner approves lands on the very roll call the page will display.

The window is `--since/--until` (default: the last `--days` 14 days, deliberately
longer than a weekly cadence so one missed run loses nothing). A bill's date is
its latest final vote, or its signing date when later, so a bill passed last month
but signed this week is proposed when it is signed. Bills already in the curated
list and ids in the decisions file are excluded.

SIGNALS AND WEIGHTS (points, max 100). Mechanical and neutral: they measure how a
vote went, never which side was right, and the report lists facts only.

  outcome       max 30   veto 30 (GA: the Governor vetoed; federal: override vote) ·
                         enacted 25 (signed by the Governor / became public law) ·
                         failed on final passage 15 · passed one chamber 5
  bothChambers  10       final-passage votes recorded in both chambers
  margin        20       closeness of the closest chamber vote:
                         20 * max(0, 1 - |yea-nay|/(yea+nay) / 0.4)
  partyLine     25       parties on opposite sides, from the two-party split of
                         yea shares: 25 * clamp((|Dyea% - Ryea%| - 0.5) / 0.5, 0, 1)
  defections    10       members voting against their own party's majority:
                         10 * min(defectors / 10, 1)
  salience      10       the bill is in a statewide-policy category: GA — a subject
                         from SALIENT_GA_SUBJECTS or a general-appropriations title;
                         federal — an appropriations / authorization / budget title.
                         (Reviewed AI subjects reach ga-bills.json through the bills
                         generator, so they are read from there, keyed
                         `<session>|<identifier>` where a key is needed.)

Ties break on later date, then id. A single-chamber vote of a near-empty new
session ranks on the signals that exist; absent data scores zero, never errors.

OUTPUT (gitignored `out/key-vote-proposals/`, not `assets/data/`)
  <scope>.json   proposals, with each signal's points and the exact curated entry
                 --approve would write
  <scope>.md     the readable report; report.md combines the scopes
Why not committed: the proposals are a working file whose useful life is a week; a
committed copy would churn git every run and, under assets/data/, ship to the live
site (and trip the sync workflows) while still unreviewed. `out/` is already ignored.
The file is rebuilt from committed data every run, so nothing is lost by not storing
it. Only the owner's decisions (`_data/key_vote_decisions.json`) are state worth
committing, and `--approve` / `--dismiss` are the only writers of anything tracked.

NOTE on `voteOverride`: docs/TO-DO.md describes a `voteOverride` field, but nothing
in the SOAP-era generator reads it — generate_curated_ga_bills.py always picks the
final vote itself. This tool therefore proposes exactly the roll call the generator
will pick and writes no `voteOverride` (a field nothing reads would only mislead).
The roll numbers are shown in the report so the owner can check them.

Stdlib only. Exit 0 on success (including "no candidates"), 2 on bad input or a
refused approval.
"""

import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.atomic_io import write_json_atomic  # noqa: E402
from lib.ga_passage import LOCAL_CALENDAR, native_is_passage, normalize_bill  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "assets", "data")
OUT_DIR = os.path.join(ROOT, "out", "key-vote-proposals")
DECISIONS_FILE = os.path.join(ROOT, "_data", "key_vote_decisions.json")

WEIGHTS = {
    "outcome": 30,
    "bothChambers": 10,
    "margin": 20,
    "partyLine": 25,
    "defections": 10,
    "salience": 10,
}

#: Statewide-policy categories in the canonical GA subject taxonomy (as in
#: ga-bills.json). A neutral list of whole policy areas, not of positions.
SALIENT_GA_SUBJECTS = {
    "REVENUE AND TAXATION", "EDUCATION", "HEALTH", "ELECTIONS",
    "CRIMES AND OFFENSES (CRIMINAL CODE)", "CRIMINAL PROCEDURE", "SOCIAL SERVICES",
    "LABOR AND INDUSTRIAL RELATIONS", "MENTAL HEALTH", "MINORS", "INSURANCE",
    "RETIREMENT AND PENSIONS", "PUBLIC UTILITIES AND TRANSPORTATION", "COURTS",
    "LAW ENFORCEMENT OFFICERS AND AGENCIES", "CONSERVATION AND NATURAL RESOURCES",
    "HIGHWAYS, BRIDGES, AND FERRIES", "DOMESTIC RELATIONS", "FOOD, DRUGS, AND COSMETICS",
}
LOCAL_GA_SUBJECTS = {"Local / Municipal", "LOCAL GOVERNMENT"}
GA_APPROPRIATIONS = re.compile(r"appropriation", re.IGNORECASE)
FED_SALIENT_TITLE = re.compile(
    r"appropriation|continuing|authorization|reconciliation|budget|national defense", re.IGNORECASE)

GA_BILL_TYPES = re.compile(r"^(HB|SB)\b", re.IGNORECASE)
FED_BILL_TYPES = ("hr", "s", "hjres", "sjres")
FED_FINAL_MOTION = re.compile(
    r"^(on passage|passage|on motion to suspend the rules and (pass|agree|concur)|"
    r"on motion to concur in the senate amendment|on the (joint )?resolution$)", re.IGNORECASE)
FED_OVERRIDE = re.compile(r"objections of the president", re.IGNORECASE)

FED_LABEL = {"hr": "H.R.", "s": "S.", "hjres": "H.J.Res.", "sjres": "S.J.Res."}
FED_SLUG = {"hr": "house-bill", "s": "senate-bill",
            "hjres": "house-joint-resolution", "sjres": "senate-joint-resolution"}


# ───────────────────────────────────────────────────────────────── helpers

def load_json(path, default=None):
    """Parsed JSON, or `default` when the file is absent/unreadable — a near-empty
    new-session data set must produce an empty report, never a traceback."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def slug(text):
    return re.sub(r"[^a-z0-9_]+", "", (text or "").lower())


def ordinal(n):
    n = int(n)
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def pct(a, b):
    return f"{100 * a / b:.0f}%" if b else "n/a"


def margin_share(yea, nay):
    total = (yea or 0) + (nay or 0)
    return abs((yea or 0) - (nay or 0)) / total if total else None


# ───────────────────────────────────────────────────────────────── signals

def split_facts(d_yea, d_nay, r_yea, r_nay, d_other=0, r_other=0):
    """Party split facts and the two party signals' raw values."""
    out = {"D": {"yea": d_yea, "nay": d_nay, "other": d_other},
           "R": {"yea": r_yea, "nay": r_nay, "other": r_other}}
    d_tot, r_tot = d_yea + d_nay, r_yea + r_nay
    gap = None
    if d_tot >= 5 and r_tot >= 5:
        gap = abs(d_yea / d_tot - r_yea / r_tot)
    defectors = min(d_yea, d_nay) + min(r_yea, r_nay)
    return out, gap, defectors


def score_signals(votes, outcome_kind, both, salient, salient_detail):
    """[(name, points, detail)] for one candidate. `votes` are the per-chamber final
    votes, each with yea/nay/party/gap/defectors."""
    sig = []

    pts = {"veto": 30, "enacted": 25, "failed": 15, "passed": 5}.get(outcome_kind, 0)
    label = {"veto": "vetoed / override vote", "enacted": "enacted",
             "failed": "failed on final passage", "passed": "passed one chamber"}.get(outcome_kind, "none")
    sig.append(("outcome", pts, label))

    sig.append(("bothChambers", WEIGHTS["bothChambers"] if both else 0,
                "final votes in both chambers" if both else "one chamber only"))

    closest = None
    for v in votes:
        m = margin_share(v["yea"], v["nay"])
        if m is not None and (closest is None or m < closest[0]):
            closest = (m, v)
    if closest:
        m, v = closest
        sig.append(("margin", round(WEIGHTS["margin"] * clamp(1 - m / 0.4), 1),
                    f"{v['chamber']} {v['yea']}–{v['nay']} (margin {m * 100:.0f}% of votes cast)"))
    else:
        sig.append(("margin", 0, "no yea/nay count"))

    gaps = [(v["gap"], v) for v in votes if v.get("gap") is not None]
    if gaps:
        g, v = max(gaps, key=lambda t: t[0])
        sig.append(("partyLine", round(WEIGHTS["partyLine"] * clamp((g - 0.5) / 0.5), 1),
                    f"{v['chamber']}: Democrats {pct(v['party']['D']['yea'], v['party']['D']['yea'] + v['party']['D']['nay'])} yea, "
                    f"Republicans {pct(v['party']['R']['yea'], v['party']['R']['yea'] + v['party']['R']['nay'])} yea"))
    else:
        sig.append(("partyLine", 0, "no two-party split recorded"))

    defs = [(v["defectors"], v) for v in votes if v.get("defectors") is not None]
    if defs:
        n, v = max(defs, key=lambda t: t[0])
        sig.append(("defections", round(WEIGHTS["defections"] * min(n / 10, 1), 1),
                    f"{n} voted against their party's majority ({v['chamber']})"))
    else:
        sig.append(("defections", 0, "no party data"))

    sig.append(("salience", WEIGHTS["salience"] if salient else 0, salient_detail))
    return sig


# ───────────────────────────────────────────────────────────────── GA

def ga_final_vote_key(v):
    """Same ordering as generate_curated_ga_bills.select_final_vote."""
    passed = str(v.get("result") or "").lower().startswith("pass")
    return (v.get("rollNumber") or 0, v.get("date") or "", v.get("time") or "", 1 if passed else 0)


def ga_is_final(meta):
    motion = meta.get("motionText") or ""
    if not native_is_passage(motion) or LOCAL_CALENDAR.search(motion):
        return False
    ident = meta.get("bill") or ""
    if GA_BILL_TYPES.match(ident):
        return True
    # A resolution counts only when it proposes a constitutional amendment.
    return bool(re.search(r"constitutional amendment", motion + " " + (meta.get("title") or ""), re.IGNORECASE))


def ga_vote_facts(meta, vid):
    pt = meta.get("partyTally") or {}
    d, r = pt.get("Democratic") or {}, pt.get("Republican") or {}
    party, gap, defectors = split_facts(d.get("yea", 0), d.get("nay", 0), r.get("yea", 0), r.get("nay", 0))
    chamber = "Senate" if meta.get("chamber") == "Senate" else "House"
    return {
        "chamber": chamber, "voteId": vid, "date": meta.get("date"),
        "rollNumber": meta.get("rollNumber"), "motion": meta.get("motionText"),
        "result": "Pass" if str(meta.get("result") or "").lower().startswith("pass") else "Fail",
        "yea": meta.get("yea") or 0, "nay": meta.get("nay") or 0,
        "party": party, "gap": gap, "defectors": defectors,
        "url": meta.get("billUrl"),
    }


def build_ga(data_dir, since, until, excluded_keys, dismissed):
    idx = load_json(os.path.join(data_dir, "ga-votes-index.json"), {}) or {}
    bills = {(b.get("session"), normalize_bill(b.get("identifier"))): b
             for b in (load_json(os.path.join(data_dir, "ga-bills.json"), {}) or {}).get("bills", [])}
    votes = idx.get("votes") or {}

    by_bill = {}
    for vid, meta in votes.items():
        if ga_is_final(meta):
            by_bill.setdefault((meta.get("session"), normalize_bill(meta.get("bill"))), []).append((vid, meta))

    latest_vote = max((m.get("date") or "" for m in votes.values()), default=None)
    out = []
    for (session, norm), rows in by_bill.items():
        if (session, norm) in excluded_keys:
            continue
        bill = bills.get((session, norm)) or {}
        subjects = bill.get("subjects") or []
        if subjects and set(subjects) <= LOCAL_GA_SUBJECTS:
            continue
        chosen = {}
        for vid, meta in rows:
            ch = "Senate" if meta.get("chamber") == "Senate" else "House"
            if ch not in chosen or ga_final_vote_key(meta) > ga_final_vote_key(chosen[ch][1]):
                chosen[ch] = (vid, meta)
        facts = [ga_vote_facts(m, vid) for vid, m in chosen.values()]
        facts.sort(key=lambda f: (f["date"] or "", f["chamber"]))
        status = bill.get("status") or ""
        status_date = (bill.get("statusDate") or "")[:10] or None
        signed = bool(re.search(r"signed by governor", status, re.IGNORECASE))
        vetoed = bool(re.search(r"veto", status, re.IGNORECASE))
        failed = any(f["result"] == "Fail" for f in facts)
        kind = "veto" if vetoed else "enacted" if signed else "failed" if failed else "passed"
        event = max([f["date"] or "" for f in facts] + [status_date if (signed or vetoed) and status_date else ""])
        if not event or event < since or event > until:
            continue
        ident = bill.get("identifier") or facts[0] and (chosen[next(iter(chosen))][1].get("bill"))
        title = bill.get("title") or chosen[next(iter(chosen))][1].get("title") or ""
        cid = f"ga-{session}-{slug(ident)}"
        if cid in dismissed:
            continue
        subj_hit = sorted(set(subjects) & SALIENT_GA_SUBJECTS)
        approp = bool(GA_APPROPRIATIONS.search(title))
        salient = bool(subj_hit) or approp
        detail = ("; ".join(subj_hit) if subj_hit else "general appropriations" if approp
                  else ("subjects: " + ", ".join(subjects)) if subjects else "no subject data")
        signals = score_signals(facts, kind, len(facts) == 2 and not failed, salient, detail)
        url = bill.get("billUrl") or next((f["url"] for f in facts if f["url"]), None)
        out.append({
            "id": cid, "scope": "ga", "identifier": ident, "session": session,
            "title": title, "subjects": subjects, "billUrl": url,
            "status": status or None, "eventDate": event,
            "outcome": kind, "votes": facts,
            "signals": [{"name": n, "points": p, "detail": d} for n, p, d in signals],
            "score": round(sum(p for _, p, _ in signals), 1),
            "curatedEntry": {"_name": ga_short_name(title), "session": session, "identifier": ident},
        })
    return out, latest_vote


def ga_short_name(title):
    head = (title or "").split(";")[0].strip()
    return head or title


# ───────────────────────────────────────────────────────────────── federal

def fed_vote_url(vote_id):
    m = re.match(r"^H(\d{4})_(\d+)$", vote_id)
    if m:
        return f"https://clerk.house.gov/evs/{m.group(1)}/roll{int(m.group(2)):03d}.xml"
    m = re.match(r"^S(\d+)_(\d)_(\d+)$", vote_id)
    if m:
        c, s, n = m.groups()
        return (f"https://www.senate.gov/legislative/LIS/roll_call_votes/vote{c}{s}/"
                f"vote_{c}_{s}_{int(n):05d}.htm")
    return None


def fed_bill_url(congress, btype, number):
    return f"https://www.congress.gov/bill/{ordinal(congress)}-congress/{FED_SLUG[btype]}/{number}"


def fed_roll_key(vote_id):
    nums = re.findall(r"\d+", vote_id)
    return int(nums[-1]) if nums else 0


def build_federal(data_dir, since, until, excluded, dismissed):
    idx = load_json(os.path.join(data_dir, "federal-votes-index.json"), {}) or {}
    meta = idx.get("metadata") or {}
    congress = meta.get("congress")
    vote_ids, rows, motions = idx.get("voteIds") or [], idx.get("rows") or [], idx.get("motions") or []
    laws = {}
    pl = load_json(os.path.join(data_dir, "presidential-laws.json"), {}) or {}
    if not congress or (pl.get("metadata") or {}).get("congress") == congress:
        for law in pl.get("laws") or []:
            laws[normalize_bill(law.get("billLabel"))] = law

    by_bill = {}
    latest_vote = None
    for vid, r in zip(vote_ids, rows):
        # Leading run only: build_federal_votes_slices.py appends fields at the end.
        chamber, vdate, btype, number, title, midx, res, yea, nay, tally = r[:10]
        latest_vote = max(latest_vote or "", vdate or "") or None
        if btype not in FED_BILL_TYPES:
            continue
        motion = motions[midx] if isinstance(midx, int) and midx < len(motions) else ""
        if not FED_FINAL_MOTION.search(motion) and not FED_OVERRIDE.search(motion):
            continue
        by_bill.setdefault((btype, str(number)), []).append((vid, r, motion))

    out = []
    for (btype, number), rows_ in by_bill.items():
        label = f"{FED_LABEL[btype]} {number}"
        norm = normalize_bill(label)
        if (congress, norm) in excluded:
            continue
        chosen = {}
        for vid, r, motion in rows_:
            ch = "Senate" if r[0] == "S" else "House"
            if ch not in chosen or (r[1], fed_roll_key(vid)) > (chosen[ch][1][1], fed_roll_key(chosen[ch][0])):
                chosen[ch] = (vid, r, motion)
        if any(vid in excluded for vid, _, _ in chosen.values()):
            continue
        facts = []
        for ch, (vid, r, motion) in chosen.items():
            t = r[9] or [0, 0, 0, 0, 0, 0]
            party, gap, defectors = split_facts(t[0], t[1], t[3], t[4], t[2], t[5])
            facts.append({
                "chamber": ch, "voteId": vid, "date": r[1], "rollNumber": fed_roll_key(vid),
                "motion": motion, "result": "Pass" if r[6] == "P" else "Fail",
                "yea": r[7] or 0, "nay": r[8] or 0, "party": party, "gap": gap,
                "defectors": defectors, "url": fed_vote_url(vid),
            })
        facts.sort(key=lambda f: (f["date"] or "", f["chamber"]))
        law = laws.get(norm)
        override = any(FED_OVERRIDE.search(f["motion"] or "") for f in facts)
        failed = any(f["result"] == "Fail" for f in facts)
        kind = "veto" if override else "enacted" if law else "failed" if failed else "passed"
        sign_date = (law or {}).get("signingDate")
        event = max([f["date"] or "" for f in facts] + [sign_date or ""])
        if not event or event < since or event > until:
            continue
        title = rows_[-1][1][4] or ""
        cid = f"federal-{congress}-{slug(label)}"
        if cid in dismissed:
            continue
        salient = bool(FED_SALIENT_TITLE.search(title) or FED_SALIENT_TITLE.search((law or {}).get("title") or ""))
        detail = "appropriations / authorization / budget title" if salient else "no salience marker in the title"
        signals = score_signals(facts, kind, len(facts) == 2 and not failed, salient, detail)
        curated_title = (law or {}).get("title") or title
        out.append({
            "id": cid, "scope": "federal", "identifier": label, "session": congress,
            "title": curated_title, "subjects": [], "billUrl": fed_bill_url(congress, btype, number),
            "status": (law or {}).get("actionText"), "eventDate": event,
            "outcome": kind, "votes": facts,
            "signals": [{"name": n, "points": p, "detail": d} for n, p, d in signals],
            "score": round(sum(p for _, p, _ in signals), 1),
            "curatedEntry": {
                "bill": label, "title": curated_title,
                # Official title only: the owner replaces it with plain English at approval.
                "summary": curated_title,
                "billUrl": fed_bill_url(congress, btype, number), "congress": congress,
                "voteIds": {f["chamber"]: f["voteId"] for f in facts},
            },
        })
    return out, latest_vote, congress


# ───────────────────────────────────────────────────────────────── ranking + output

def rank(cands, limit):
    cands.sort(key=lambda c: (-c["score"], _neg(c["eventDate"]), c["id"]))
    for i, c in enumerate(cands, 1):
        c["rank"] = i
    return cands[:limit] if limit else cands


def _neg(s):
    """Sort key making later ISO dates come first inside an ascending sort."""
    return tuple(-ord(ch) for ch in (s or ""))


def vote_line(v):
    p = v["party"]
    split = (f"D {p['D']['yea']}–{p['D']['nay']}, R {p['R']['yea']}–{p['R']['nay']}"
             if (p["D"]["yea"] + p["D"]["nay"] + p["R"]["yea"] + p["R"]["nay"]) else "party split not recorded")
    m = margin_share(v["yea"], v["nay"])
    margin = f"margin {abs(v['yea'] - v['nay'])} ({m * 100:.0f}% of votes cast)" if m is not None else "no count"
    roll = f", roll call {v['rollNumber']}" if v.get("rollNumber") else ""
    link = f" — [official record]({v['url']})" if v.get("url") else ""
    return (f"{v['chamber']} {v['date']}: {v['motion']}{roll} — {v['result']} {v['yea']}–{v['nay']}, "
            f"{margin}; {split}{link}")


def render_report(scope_label, doc):
    meta = doc["metadata"]
    lines = [f"## {scope_label}", "",
             f"Window {meta['window']['since']} to {meta['window']['until']} · "
             f"{meta['candidateCount']} candidate(s), showing {len(doc['proposals'])}. "
             f"Latest roll call in the data: {meta['latestRollCall'] or 'none yet'}.", ""]
    if not doc["proposals"]:
        lines += ["No candidates in this window. (A new session or Congress with no final-passage "
                  "votes yet, or everything is already curated or dismissed.)", ""]
        return "\n".join(lines)
    for c in doc["proposals"]:
        lines += [f"### {c['rank']}. {c['identifier']} — {c['title']}",
                  f"`{c['id']}` · score {c['score']} · event date {c['eventDate']} · "
                  f"outcome: {c['outcome']}" + (f" · status: {c['status']}" if c.get("status") else "")]
        if c.get("billUrl"):
            lines.append(f"Bill: {c['billUrl']}")
        lines.append("")
        lines += [f"- {vote_line(v)}" for v in c["votes"]]
        why = "; ".join(f"{s['name']} {s['points']} ({s['detail']})" for s in c["signals"] if s["points"])
        lines += ["", f"Why it ranks: {why or 'no signal scored'}.", ""]
    ids = ",".join(c["id"] for c in doc["proposals"][:3])
    lines += [f"To accept: `python scripts/propose_key_votes.py --approve {ids}`", ""]
    return "\n".join(lines)


def run_propose(args):
    today = date.fromisoformat(args.today) if args.today else date.today()
    until = args.until or today.isoformat()
    since = args.since or (date.fromisoformat(until) - timedelta(days=args.days)).isoformat()
    decisions = load_json(args.decisions, {}) or {}
    dismissed = set((decisions.get("dismissed") or {}).keys())
    scopes = ["ga", "federal"] if args.scope == "both" else [args.scope]
    os.makedirs(args.out_dir, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    sections, summary = [], []

    for scope in scopes:
        if scope == "ga":
            cur = load_json(args.curated_ga, {}) or {}
            excluded = {(e.get("session"), normalize_bill(e.get("identifier"))) for e in cur.get("ga") or []}
            cands, latest = build_ga(args.data_dir, since, until, excluded, dismissed)
            label = "Georgia General Assembly (curated-ga-bills.json)"
        else:
            cur = load_json(args.curated_federal, {}) or {}
            excluded = set()
            for b in cur.get("bills") or []:
                excluded.add((b.get("congress"), normalize_bill(b.get("bill"))))
                excluded.update((b.get("voteIds") or {}).values())
            cands, latest, _ = build_federal(args.data_dir, since, until, excluded, dismissed)
            label = "Georgia congressional delegation (curated-federal-bills.json)"
        total = len(cands)
        proposals = rank(cands, args.limit)
        doc = {"metadata": {"scope": scope, "generatedAt": stamp, "window": {"since": since, "until": until},
                            "candidateCount": total, "latestRollCall": latest,
                            "weights": WEIGHTS, "writes": "never the curated list; see --approve"},
               "proposals": proposals}
        write_json_atomic(os.path.join(args.out_dir, f"{scope}.json"), doc, indent=2)
        md = render_report(label, doc)
        with open(os.path.join(args.out_dir, f"{scope}.md"), "w", encoding="utf-8") as f:
            f.write(f"# Key Votes proposals — {label}\n\n" + md + "\n")
        sections.append(md)
        summary.append(f"{scope}: {len(proposals)} of {total}")
    with open(os.path.join(args.out_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write("# Key Votes proposals\n\nMechanical ranking from the official roll calls; the facts "
                "(margin, party split, action) are listed without judgment. Nothing is added to a "
                "curated list until you approve it.\n\n" + "\n".join(sections) + "\n")
    print("Key Votes proposals — " + "; ".join(summary))
    print(f"report: {os.path.join(args.out_dir, 'report.md')}")
    return 0


# ───────────────────────────────────────────────────────────────── approve / dismiss

def curated_spec(scope, path):
    if scope == "ga":
        return "ga", (lambda e: (e.get("session"), normalize_bill(e.get("identifier"))))
    return "bills", (lambda e: (e.get("congress"), normalize_bill(e.get("bill"))))


def run_approve(args):
    wanted = [s.strip() for s in args.approve.split(",") if s.strip()]
    if not wanted:
        print("--approve needs at least one candidate id", file=sys.stderr)
        return 2
    by_scope = {}
    for cid in wanted:
        scope = "ga" if cid.startswith("ga-") else "federal" if cid.startswith("federal-") else None
        if scope is None:
            print(f"unrecognized id {cid!r} (expected ga-... or federal-...)", file=sys.stderr)
            return 2
        by_scope.setdefault(scope, []).append(cid)
    if len(set(wanted)) != len(wanted):
        print("the same id was listed twice", file=sys.stderr)
        return 2

    plan = {}
    for scope, ids in by_scope.items():
        proposals = (load_json(os.path.join(args.out_dir, f"{scope}.json"), {}) or {}).get("proposals")
        if proposals is None:
            print(f"no proposals file for {scope}; run the propose step first", file=sys.stderr)
            return 2
        known = {p["id"]: p for p in proposals}
        path = args.curated_ga if scope == "ga" else args.curated_federal
        curated = load_json(path, None)
        if curated is None:
            curated = {"_note": "Curated Key Votes. Proposals come from scripts/propose_key_votes.py; "
                                "entries are added only with the owner's approval."}
        listkey, keyfn = curated_spec(scope, path)
        existing = curated.get(listkey) or []
        taken = {keyfn(e) for e in existing}
        taken_votes = {v for e in existing for v in (e.get("voteIds") or {}).values()}
        add = []
        for cid in ids:
            if cid not in known:
                print(f"{cid}: not in the current proposals (older than the window, or already "
                      f"curated/dismissed); re-run the propose step", file=sys.stderr)
                return 2
            entry = known[cid]["curatedEntry"]
            if keyfn(entry) in taken or taken_votes & set((entry.get("voteIds") or {}).values()):
                print(f"{cid}: already in {os.path.basename(path)}; refusing duplicate", file=sys.stderr)
                return 2
            add.append(entry)
        curated[listkey] = existing + add
        plan[scope] = (path, curated, add)

    for scope, (path, curated, add) in plan.items():
        write_json_atomic(path, curated, indent=2)
        print(f"{scope}: added {len(add)} to {os.path.relpath(path, ROOT)}")
        if scope == "federal":
            print("  Replace each new `summary` (the official title) with a plain-English one.")
    return 0


def run_dismiss(args):
    ids = [s.strip() for s in args.dismiss.split(",") if s.strip()]
    doc = load_json(args.decisions, None) or {}
    dismissed = doc.setdefault("dismissed", {})
    stamp = date.fromisoformat(args.today).isoformat() if args.today else date.today().isoformat()
    for cid in ids:
        dismissed[cid] = {"at": stamp, "note": args.note or None}
    write_json_atomic(args.decisions, doc, indent=2)
    print(f"dismissed {len(ids)} candidate(s) in {os.path.relpath(args.decisions, ROOT)}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--scope", choices=["ga", "federal", "both"], default="both")
    ap.add_argument("--days", type=int, default=14, help="window length when --since is not given")
    ap.add_argument("--since")
    ap.add_argument("--until")
    ap.add_argument("--limit", type=int, default=15, help="proposals per scope (0 = all)")
    ap.add_argument("--approve", help="comma-separated candidate ids to add to the curated list")
    ap.add_argument("--dismiss", help="comma-separated candidate ids to stop proposing")
    ap.add_argument("--note")
    ap.add_argument("--data-dir", default=DATA_DIR)
    ap.add_argument("--out-dir", default=OUT_DIR)
    ap.add_argument("--curated-ga")
    ap.add_argument("--curated-federal")
    ap.add_argument("--decisions", default=DECISIONS_FILE)
    ap.add_argument("--today", help="override today's date (tests)")
    args = ap.parse_args(argv)
    args.curated_ga = args.curated_ga or os.path.join(args.data_dir, "curated-ga-bills.json")
    args.curated_federal = args.curated_federal or os.path.join(args.data_dir, "curated-federal-bills.json")
    if args.approve:
        return run_approve(args)
    if args.dismiss:
        return run_dismiss(args)
    return run_propose(args)


if __name__ == "__main__":
    sys.exit(main())
