#!/usr/bin/env python3
"""The roster producer's ledger: beside its output, saved only after every refusal.
main() needs the SOAP service, so the ordering is pinned on the source. Stdlib only."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import generate_ga_members_soap as G  # noqa: E402
from lib import ga_ledger as L  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


check("ledger beside output", G.ledger_path_for("/x/y/out.json"),
      os.path.join(os.path.abspath("/x/y"), "ga-legislator-ledger.json"))
check("LEDGER_PATH absolute", os.path.isabs(L.LEDGER_PATH), True)
check("LEDGER_PATH ends in the data file", L.LEDGER_PATH.replace("\\", "/").endswith("assets/data/ga-legislator-ledger.json"), True)
check("LEDGER_PATH independent of cwd", os.path.dirname(L.LEDGER_PATH),
      os.path.join(L.REPO_ROOT, "assets", "data"))

src = open(G.__file__, encoding="utf-8").read()
save = src.index("LEDGER.save_ledger(")
check("save follows every refusal", all(src.rfind(m, 0, save) > src.index("def main") and
      src.index(m) < save for m in ("roster is short", "unexpected party value(s)")), True)
check("save immediately precedes roster write",
      src[save:].split("\n")[1].strip().startswith("write_json_atomic(output_file"), True)
check("exactly one save", src.count("LEDGER.save_ledger("), 1)

print("\nFAILED: " + ", ".join(failures) if failures else "\nAll checks passed.")
sys.exit(1 if failures else 0)
