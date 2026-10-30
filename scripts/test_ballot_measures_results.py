#!/usr/bin/env python3
"""Statewide ballot questions must reach the results page, not be dropped.

Three constitutional amendments are certified for 3 November 2026. Until this
was wired up, build_results_json.classify() returned None for them — they fell
in with the county party straw polls under "party questions etc. — skip" — so
on election night every office on the page would have filled in while three
questions the same voter just decided reported nothing at all.

The office names here are the Secretary of State's own, read off the certified
2024 general export rather than guessed: "Proposed Constitutional Amendment 1"
and "Statewide Referendum Question A", each carrying Yes/No ballot options and,
unhelpfully, contestType "Candidate" — so the office name is the only thing
that can be keyed on, and these pin it.

Usage:
  python scripts/test_ballot_measures_results.py

Exits 0 on success, 1 on any failure.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_results_json as R  # noqa: E402
import build_general_placeholder as P  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def cases():
    # Exactly as the SoS writes them.
    for office in ("Proposed Constitutional Amendment 1",
                   "Proposed Constitutional Amendment 2",
                   "Statewide Referendum Question A"):
        check(f"{office!r} is a ballot question", R.classify(office), "measures")

    # Case must not matter: classify() lowercases, and the export's casing is
    # not a contract.
    check("casing does not decide it",
          R.classify("PROPOSED CONSTITUTIONAL AMENDMENT 1"), "measures")

    # The things that must NOT become ballot questions. County party straw polls
    # are the reason the catch-all `return None` exists.
    for office in ("Democratic Party Question 1", "Republican Party Question 2",
                   "US Senate", "State House of Representatives - District 70",
                   "Judge - Superior Court - Atlanta Circuit (Eaton)",
                   "District Attorney - Atlantic Judicial Circuit"):
        check(f"{office!r} is not a ballot question",
              R.classify(office) == "measures", False)

    # A question reaching the builder must land in its own section, with the
    # Yes/No options intact.
    contests = {
        "1": {"office_name": "Proposed Constitutional Amendment 1", "party": "np",
              "totalVotes": 300,
              "candidates": [{"name": "Yes", "votes": 200, "incumbent": False},
                             {"name": "No", "votes": 100, "incumbent": False}]},
    }
    sections = {s["id"]: s for s in R.build_sections(contests)}
    check("the section exists", "measures" in sections, True)
    check("the question is in it",
          [r["office"] for r in sections["measures"]["races"]],
          ["Proposed Constitutional Amendment 1"])
    check("Yes and No both survive",
          [c["name"] for c in sections["measures"]["races"][0]["contests"][0]["candidates"]],
          ["Yes", "No"])
    check("it did not also land somewhere else",
          sum(len(s["races"]) for k, s in sections.items() if k != "measures"), 0)

    # The pre-election preview lists the certified measures and only those.
    measures = P.measure_races()
    check("the preview lists the certified measures", len(measures), 3)
    check("every preview question is a zero-vote Yes/No",
          sorted({c["name"] for m in measures for con in m["contests"]
                  for c in con["candidates"]}), ["No", "Yes"])
    check("the preview carries no votes",
          sum(c["votes"] for m in measures for con in m["contests"]
              for c in con["candidates"]), 0)
    # "not-on-ballot" is a real lifecycle value in that file and must not show.
    check("a measure that is not on the ballot is left out",
          any("Disabled Veteran" in m["office"] or "Surviving Spouses" in m["office"]
              for m in measures), False)


if __name__ == "__main__":
    print("ballot questions on the results page:")
    cases()
    if failures:
        print(f"\n{len(failures)} failure(s)")
        sys.exit(1)
    print("\nAll checks passed.")
