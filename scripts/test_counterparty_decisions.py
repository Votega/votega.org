#!/usr/bin/env python3
"""Invariants of folding the review tool's decision log into the counterparty queue
(lib/counterparty_decisions.py). No network, no third-party deps.
Run: python scripts/test_counterparty_decisions.py"""

import copy
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from lib.counterparty_decisions import apply_decisions  # noqa: E402
import generate_local_counterparties as G  # noqa: E402

failures = []


def check(cond, msg):
    print("  %s  %s" % ("ok  " if cond else "FAIL", msg))
    if not cond:
        failures.append(msg)


def entry(key, name, status="pending", role="vendor"):
    return {"key": key, "status": status, "displayName": name, "role": role,
            "date": "2026-01-01", "reference": "2026-1", "itemName": "Awarded to " + name}


def queue():
    return {
        "acme": entry("acme", "Acme Paving Inc."),
        "advance-auto-parts-tidewater-fleet-supply":
            entry("advance-auto-parts-tidewater-fleet-supply",
                  "Advance Auto Parts, Tidewater Fleet Supply LLC.", role="other"),
        "done": entry("done", "Done LLC", status="approved"),
        "no": entry("no", "No Corp", status="rejected"),
    }


def run(decisions, q=None):
    q = q if q is not None else queue()
    applied, skipped = apply_decisions(q, decisions, G.entity_id, G.normalize)
    return q, applied, skipped


print("approve / reject / edit")
q, a, s = run([{"key": "acme", "action": "approve", "displayName": "Acme Paving", "note": "ok"}])
check(q["acme"]["status"] == "approved" and q["acme"]["displayName"] == "Acme Paving",
      "approve sets status and applies a name fix")
check(q["acme"]["key"] == "acme", "a name fix never changes the key")
q, a, s = run([{"key": "acme", "action": "reject", "note": "not an org"}])
check(q["acme"]["status"] == "rejected" and q["acme"]["reviewNote"] == "not an org",
      "reject records the note")
q, a, s = run([{"key": "acme", "action": "reject"}])
check(q["acme"]["reviewNote"] == "rejected", "reject without a note still records a reason")
q, a, s = run([{"key": "acme", "action": "edit", "displayName": "Acme Paving", "role": "applicant"}])
check(q["acme"]["status"] == "pending" and q["acme"]["role"] == "applicant",
      "edit changes fields and leaves the entry pending")

print("a decision already made is never overwritten")
q, a, s = run([{"key": "done", "action": "reject"}, {"key": "no", "action": "approve"}])
check(q["done"]["status"] == "approved" and q["no"]["status"] == "rejected",
      "approved and rejected entries are untouched")
check(a == [], "nothing reported as applied")

print("idempotent replay")
log = [{"key": "acme", "action": "approve"},
       {"key": "advance-auto-parts-tidewater-fleet-supply", "action": "split",
        "parts": [{"displayName": "Advance Auto Parts"}, {"displayName": "Tidewater Fleet Supply LLC"}]}]
q1, _, _ = run(log)
q2 = copy.deepcopy(q1)
apply_decisions(q2, log, G.entity_id, G.normalize)
check(q1 == q2, "replaying the log yields the same queue")

print("split")
check(q1["advance-auto-parts-tidewater-fleet-supply"]["status"] == "rejected",
      "the original is rejected")
check(q1["advance-auto-parts"]["status"] == "pending" and
      q1["tidewater-fleet-supply"]["status"] == "pending",
      "parts are queued pending, never approved")
p = q1["advance-auto-parts"]
check(p["role"] == "other" and p["reference"] == "2026-1" and p["itemName"].startswith("Awarded"),
      "parts inherit role and agenda context")
q, a, s = run([{"key": "acme", "action": "split", "parts": [{"displayName": "Only One"}]}])
check(q["acme"]["status"] == "pending" and len(s) == 1, "a split needs two parts")
q = queue()
q["acme-b"] = entry("acme-b", "Acme B", status="approved")
q, a, s = run([{"key": "acme", "action": "split",
                "parts": [{"displayName": "Acme B"}, {"displayName": "Acme C"}]}], q)
check(q["acme-b"]["status"] == "approved", "a part whose key exists is never overwritten")
check("acme-c" in q, "the other part is still queued")

print("bad input is reported, not applied")
q, a, s = run([{"key": "missing", "action": "approve"}, {"key": "acme", "action": "bogus"},
               {"key": "acme", "action": "approve", "role": "king"}])
check(len(s) == 3 and q["acme"]["status"] == "pending", "unknown key, action and role are skipped")

print("aka (another name the agenda text states)")


def scs():
    e = entry("scs", "Stearns, Conrad and Schmidt Consulting Inc.")
    e["itemName"] = "Awarded to Stearns, Conrad and Schmidt Consulting Inc., dba SCS Engineers."
    return {"scs": e}


q, a, s = run([{"key": "scs", "action": "approve", "aka": ["SCS Engineers"], "note": "dba in text"}], scs())
check(q["scs"]["status"] == "approved" and q["scs"]["aka"] == ["SCS Engineers"], "an aka stated in the text is recorded")
q, a, s = run([{"key": "scs", "action": "approve", "aka": ["SCS Engineers"]}], scs())
check(q["scs"]["status"] == "pending" and len(s) == 1, "an aka without a note is refused")
q, a, s = run([{"key": "scs", "action": "approve", "aka": ["Made Up Name"], "note": "n"}], scs())
check(q["scs"]["status"] == "pending" and "aka" not in q["scs"], "an aka not in the agenda text is refused")
q, a, s = run([{"key": "scs", "action": "reject", "aka": ["SCS Engineers"], "note": "n"}], scs())
check(q["scs"]["status"] == "pending", "an aka only goes with approve or edit")
q, a, s = run([{"key": "scs", "action": "approve", "aka": []}], scs())
check(q["scs"]["status"] == "approved" and "aka" not in q["scs"], "no aka is the default and needs no note")
q = scs()
q, a, s = run([{"key": "scs", "action": "edit", "aka": ["SCS Engineers"], "note": "one"},
               {"key": "scs", "action": "edit", "aka": ["SCS Engineers"], "note": "again"}], q)
check(q["scs"]["aka"] == ["SCS Engineers"] and q["scs"]["status"] == "pending",
      "repeating an aka does not duplicate it, and edit leaves the entry pending")

print("revise (the only way to change a decided entry)")
q, a, s = run([{"key": "done", "action": "revise", "from": "approved", "status": "rejected", "note": "wrong org"}])
check(q["done"]["status"] == "rejected" and q["done"]["reviewNote"] == "wrong org", "revise moves an approved entry to rejected")
q, a, s = run([{"key": "no", "action": "revise", "from": "rejected", "status": "pending", "note": "reopen"}])
check(q["no"]["status"] == "pending", "revise can reopen a rejected entry")
q, a, s = run([{"key": "done", "action": "revise", "from": "approved", "displayName": "Done", "note": "shorter"}])
check(q["done"]["status"] == "approved" and q["done"]["displayName"] == "Done",
      "revise without a status fixes the name and leaves the status")
q, a, s = run([{"key": "done", "action": "revise", "from": "approved", "status": "rejected"}])
check(q["done"]["status"] == "approved" and len(s) == 1, "a revise needs a note")
q, a, s = run([{"key": "done", "action": "revise", "status": "rejected", "note": "n"}])
check(q["done"]["status"] == "approved" and len(s) == 1, "a revise must say what it expects to find")
q, a, s = run([{"key": "done", "action": "revise", "from": "rejected", "status": "pending", "note": "n"}])
check(q["done"]["status"] == "approved" and len(s) == 1, "a revise against the wrong status is reported, not applied")
q, a, s = run([{"key": "acme", "action": "revise", "from": "pending", "status": "approved", "note": "n"}])
check(q["acme"]["status"] == "approved", "a revise also works on a pending entry")

print("revise replays converge")
chain = [{"key": "done", "action": "revise", "from": "approved", "status": "rejected", "note": "a"},
         {"key": "done", "action": "revise", "from": "rejected", "status": "approved", "note": "b"},
         {"key": "done", "action": "revise", "from": "approved", "status": "rejected", "note": "c"}]
q1, a1, s1 = run(chain)
q2 = copy.deepcopy(q1)
_, a2, s2 = apply_decisions(q2, chain, G.entity_id, G.normalize) + (None,)
check(q1 == q2 and q1["done"]["status"] == "rejected", "a chain of revises ends in the last state and replays to it")
log = [{"key": "acme", "action": "approve"},
       {"key": "acme", "action": "revise", "from": "approved", "status": "rejected", "note": "changed my mind"}]
q1, _, _ = run(log)
q2 = copy.deepcopy(q1)
apply_decisions(q2, log, G.entity_id, G.normalize)
check(q1["acme"]["status"] == "rejected" and q1 == q2, "approve then revise replays to rejected")

print("revise and aka")
q, a, s = run([{"key": "scs", "action": "revise", "from": "approved", "aka": ["Made Up"], "note": "n"}],
              {"scs": dict(scs()["scs"], status="approved")})
check(len(s) == 1 and "aka" not in q["scs"], "a revise aka must also be stated in the agenda text")
q, a, s = run([{"key": "scs", "action": "revise", "from": "approved", "aka": ["SCS Engineers"], "note": "dba in text"}],
              {"scs": dict(scs()["scs"], status="approved")})
check(q["scs"]["aka"] == ["SCS Engineers"] and q["scs"]["status"] == "approved", "a revise can add a stated aka to an approved entry")

print()
if failures:
    print("%d FAILED" % len(failures))
    sys.exit(1)
print("all ok")
