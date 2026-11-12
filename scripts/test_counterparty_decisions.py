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

print()
if failures:
    print("%d FAILED" % len(failures))
    sys.exit(1)
print("all ok")
