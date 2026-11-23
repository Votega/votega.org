#!/usr/bin/env python3
"""Pin how the GA bills pipeline behaves across the 2027-01-11 biennium changeover.

The write floor exists to catch a failed sweep; it must not fail the first run of a new
General Assembly (few or no bills filed), and it must still catch a same-session drop.
Four scenarios drive generate_ga_bills_soap.main() end to end against fakes (no network):

  a. normal same-session run                       -> writes
  b. same-session drop below the floor             -> refuses
  c. rollover run with a handful of new bills      -> writes (outgoing biennium frozen)
  d. rollover run with zero bills                  -> writes, stamped; an OUTAGE still refuses

plus the guards around them (no freeze -> refuse), the validator's tier-1 treatment of an
empty file, the slice builder and enricher on a near-empty file, and the rule that
bare-identifier subject files do not leak across bienniums.

Usage: python scripts/test_ga_bills_rollover.py      (exit 0 on success)
"""
import contextlib
import io
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import generate_ga_bills_soap as G  # noqa: E402
import validate_ga_bills as V  # noqa: E402
from lib import ga_bills_rollover as R  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def bill(n, session, lid=None):
    return {"id": f"gga-bill/{session}/{n}", "identifier": f"HB {n}", "chamber": "lower",
            "title": f"Bill {n}", "billUrl": f"https://x/{n}", "session": session,
            "billType": "bill", "subjects": [], "passageVotes": [], "governorAction": None,
            "sponsors": [], "status": "Introduced", "legislationId": lid or 1000 + n}


def doc(bills_by_session, biennium, active, extra_meta=None):
    bills = [bill(i, s) for s, n in bills_by_session.items() for i in range(1, n + 1)]
    meta = {"biennium": biennium, "activeSession": active, "session": active,
            "sessions": [{"id": s, "billCount": n} for s, n in bills_by_session.items()],
            "totalBills": len(bills), "preservedSessions": []}
    meta.update(extra_meta or {})
    return {"metadata": meta, "bills": bills}


class Run:
    """Run G.main() in a scratch dir with a configured world; return (exit, stderr, doc)."""

    def __init__(self, committed, *, sessions, active, biennium, new_bills, frozen_tag=None,
                 index_fails=False):
        self.d = tempfile.mkdtemp(prefix="bills-rollover-")
        self.out = os.path.join(self.d, "assets", "data", "ga-bills.json")
        os.makedirs(os.path.dirname(self.out))
        if committed is not None:
            json.dump(committed, open(self.out, "w", encoding="utf-8"))
        if frozen_tag:
            fp = R.frozen_path(self.d, frozen_tag)
            os.makedirs(os.path.dirname(fp))
            json.dump({"metadata": {"frozen": True, "frozenTag": frozen_tag},
                       "bills": [bill(1, "2025_26")]}, open(fp, "w"))
        self.cfg = dict(sessions=sessions, active=active, biennium=biennium,
                        new_bills=new_bills, index_fails=index_fails)

    def go(self):
        c = self.cfg
        saved = {k: getattr(G, k) for k in ("BIENNIUM", "ACTIVE_SESSION", "REPO_ROOT",
                 "all_session_ids", "preserved_session_ids", "legis_session_id",
                 "session_name", "get_index", "get_detail", "map_bill", "load_roster",
                 "get_titles", "load_subjects", "load_ai_subjects", "REVIEW_CSV_FILE")}
        G.BIENNIUM, G.ACTIVE_SESSION, G.REPO_ROOT = c["biennium"], c["active"], self.d
        G.all_session_ids = lambda: list(c["sessions"])
        G.preserved_session_ids = lambda: [s for s in c["sessions"] if s != c["active"]]
        G.legis_session_id = lambda s: 1
        G.session_name = lambda s: s
        G.get_index = lambda ls: None if c["index_fails"] else list(range(c["new_bills"]))
        G.get_detail = lambda lid: {"lid": lid}
        G.map_bill = lambda detail, sess, roster, titles: bill(detail["lid"] + 1, sess)
        G.load_roster = lambda: {}
        G.get_titles = lambda: {}
        G.load_subjects = lambda: ({}, {})
        G.load_ai_subjects = lambda allowed=None: {}
        G.REVIEW_CSV_FILE = os.path.join(self.d, "review.csv")
        argv, sys.argv = sys.argv, ["gen", self.out, "--delay", "0"]
        err, code = io.StringIO(), 0
        try:
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                G.main()
        except SystemExit as e:
            code = e.code or 0
        finally:
            sys.argv = argv
            for k, v in saved.items():
                setattr(G, k, v)
        written = None
        if code == 0:
            written = json.load(open(self.out, encoding="utf-8"))
        return code, err.getvalue(), written


SAME = dict(sessions={"2025_26": "r", "2026_ss": "s"}, active="2026_ss", biennium="2025-2026")


def scenarios():
    # (a) normal same-session run: committed ~5,600 bills, active session re-fetched.
    big = doc({"2025_26": 5500, "2026_ss": 120}, "2025-2026", "2026_ss")
    code, err, out = Run(big, new_bills=125, **SAME).go()
    check("(a) normal same-session run writes", code, 0)
    check("(a) ...and carries the closed session forward", out["metadata"]["totalBills"], 5625)
    check("(a) ...with no rollover stamp", "rollover" in out["metadata"], False)

    # (b) same-session drop below the floor must fail, in both regimes.
    #  b1: preserved layer present but total still under 100 is impossible; use no
    #  preserved layer (full file shrinks): committed 5,620 -> a 40-bill write.
    solo = dict(sessions={"2026_ss": "s"}, active="2026_ss", biennium="2025-2026")
    big_solo = doc({"2026_ss": 5620}, "2025-2026", "2026_ss")
    code, err, _ = Run(big_solo, new_bills=40, **solo).go()
    check("(b) same-session drop below 100 refuses", code, 1)
    check("(b) ...says why", "refusing to write" in err, True)
    #  b2: a young file (under the floor) may grow but may not shrink.
    young = doc({"2026_ss": 8}, "2025-2026", "2026_ss")
    code, _, _ = Run(young, new_bills=5, **solo).go()
    check("(b) a young file shrinking 8 -> 5 refuses", code, 1)
    code, _, out = Run(young, new_bills=40, **solo).go()
    check("(b) a young file growing 8 -> 40 writes", code, 0)
    #  b3: an empty first-ever write with no committed file is still refused.
    code, _, _ = Run(None, new_bills=3, **solo).go()
    check("(b) no committed file, 3 bills refuses", code, 1)

    # (c) rollover with a handful of 2027 bills.
    old = doc({"2025_26": 5500, "2026_ss": 120}, "2025-2026", "2026_ss")
    new = dict(sessions={"2027_28": "r"}, active="2027_28", biennium="2027-2028")
    code, err, out = Run(old, new_bills=4, frozen_tag="2025_26", **new).go()
    check("(c) rollover with 4 bills writes", code, 0)
    check("(c) ...only the new session, nothing preserved",
          (out["metadata"]["totalBills"], out["metadata"]["preservedSessions"]), (4, []))
    check("(c) ...stamped as a rollover", out["metadata"]["rollover"]["from"], "2025-2026")
    check("(c) ...and the validator accepts it", V.tier1(out), [])
    code, err, _ = Run(old, new_bills=4, frozen_tag=None, **new).go()
    check("(c) rollover WITHOUT a freeze refuses", code, 1)
    check("(c) ...and names the freeze step", "freeze_ga_bills.py" in err, True)

    # (d) rollover with zero bills: PASSES (stamped), an outage does NOT.
    code, err, out = Run(old, new_bills=0, frozen_tag="2025_26", **new).go()
    check("(d) rollover with zero bills writes", code, 0)
    check("(d) ...empty and stamped", (out["bills"], "rollover" in out["metadata"]), ([], True))
    check("(d) ...and the validator accepts it", V.tier1(out), [])
    unstamped = json.loads(json.dumps(out))
    del unstamped["metadata"]["rollover"]
    check("(d) the same empty file WITHOUT the stamp is tier-1 rejected",
          bool(V.tier1(unstamped)), True)
    code, err, _ = Run(old, new_bills=0, frozen_tag="2025_26", index_fails=True, **new).go()
    check("(d) a SOAP outage at rollover refuses (not read as an empty session)", code, 1)
    check("(d) ...naming the outage", "outage" in err, True)
    # the next run is same-session against the empty committed file; stamp carries, bills grow
    code, _, out2 = Run(out, new_bills=0, **new).go()
    check("(d) a second still-empty run writes and keeps the stamp",
          (code, "rollover" in (out2 or {}).get("metadata", {})), (0, True))
    code, _, out3 = Run(out, new_bills=30, **new).go()
    check("(d) then 30 bills writes", code, 0)
    check("(d) ...under-100 file keeps the stamp", "rollover" in out3["metadata"], True)


def pure_cases():
    check("biennium -> tag", R.biennium_to_tag("2025-2026"), "2025_26")
    check("bad biennium -> None", R.biennium_to_tag("2025-2027"), None)
    check("same biennium is not a changeover",
          R.detect_changeover({"biennium": "2025-2026"}, "2025-2026"), None)
    check("a file with no biennium is not evidence",
          R.detect_changeover({}, "2027-2028"), None)
    check("different biennium is a changeover",
          R.detect_changeover({"biennium": "2025-2026"}, "2027-2028"),
          {"from": "2025-2026", "to": "2027-2028"})
    check("a special session inside the biennium is not a changeover",
          R.detect_changeover({"biennium": "2025-2026", "sessions": [{"id": "2025_26"}]},
                              "2025-2026"), None)


def downstream_cases():
    import build_sponsorship_slices as S
    import enrich_bills_with_party_votes  # noqa: F401  (import must not fail)
    rolled = doc({"2027_28": 3}, "2027-2028", "2027_28",
                 {"rollover": {"from": "2025-2026", "to": "2027-2028", "at": "x"}})
    empty = doc({"2027_28": 0}, "2027-2028", "2027_28", {"rollover": rolled["metadata"]["rollover"]})
    d = tempfile.mkdtemp(prefix="slices-")
    for label, payload, want in (("3 bills", rolled, 0), ("0 bills + stamp", empty, 0)):
        S.DATA_DIR = d
        S.BILLS_FILE = os.path.join(d, "ga-bills.json")
        S.MEMBERS_FILE = os.path.join(d, "none.json")
        S.INDEX_OUT = os.path.join(d, "idx.json")
        S.SLICES_DIR = os.path.join(d, "sl")
        json.dump(payload, open(S.BILLS_FILE, "w"))
        with contextlib.redirect_stdout(io.StringIO()):
            rc = S.main()
        check(f"slice builder on a rollover file ({label})", rc, want)
    bare = json.loads(json.dumps(empty))
    del bare["metadata"]["rollover"]
    json.dump(bare, open(S.BILLS_FILE, "w"))
    with contextlib.redirect_stdout(io.StringIO()):
        rc = S.main()
    check("slice builder still refuses an empty file WITHOUT the stamp", rc, 1)


def subject_scoping_cases():
    base, over = {"HB 1": ["Old"]}, {"HB 2": ["Manual"]}
    for sess, want1, want2 in (("2025_26", ["Old"], ["Manual"]), ("2026_ss", ["Old"], ["Manual"]),
                               ("2027_28", ["Fallback"], ["Fallback"])):
        b1 = {"identifier": "HB 1", "session": sess, "subjects": ["Fallback"]}
        b2 = {"identifier": "HB 2", "session": sess, "subjects": ["Fallback"]}
        G.apply_subjects(b1, base, over)
        G.apply_subjects(b2, base, over)
        check(f"subject snapshot/overrides scoped to the 2025-26 biennium ({sess})",
              (b1["subjects"], b2["subjects"]), (want1, want2))


if __name__ == "__main__":
    pure_cases()
    scenarios()
    downstream_cases()
    subject_scoping_cases()
    print()
    if failures:
        print(f"{len(failures)} FAILED: {failures}")
        sys.exit(1)
    print("all passed")
