#!/usr/bin/env python3
"""Assert build_general_placeholder.py will not overwrite real results with zeros.

The ballot preview is a zero-vote derivation of races.json, rebuilt daily and on
every races.json push by refresh-general-placeholder.yml. Once polls close and
real counts are loaded into the same file, rebuilding it would revert the page
to "Awaiting Results" and commit that.

The guard for this used to live only inside the --check branch, while the
workflow's first step ran the writer with NO flags — so the write was
unguarded, and the --check in the following step then passed because the file
it was handed had already been zeroed. counted_votes() is now read once and
gates both paths; these checks pin that.

Usage:
  python scripts/test_general_placeholder_guard.py

Exits 0 on success, 1 on any failure.
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_general_placeholder as B  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def sections(total, votes):
    """One section holding one contest with the given tallies."""
    return [{"id": "statewide", "label": "S", "races": [{
        "office": "Governor",
        "contests": [{"party": "rep", "totalVotes": total,
                      "candidates": [{"name": "A", "votes": votes, "incumbent": False}]}],
    }]}]


def write(path, data):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, separators=(",", ":"))


def cases():
    with tempfile.TemporaryDirectory() as tmp:
        missing = os.path.join(tmp, "absent.json")
        check("a file that does not exist reads as None, not 0",
              B.counted_votes(missing), None)

        placeholder = os.path.join(tmp, "placeholder.json")
        write(placeholder, sections(0, 0))
        check("a zero-vote placeholder counts 0",
              B.counted_votes(placeholder), 0)

        real = os.path.join(tmp, "real.json")
        write(real, sections(1234, 1234))
        # max(total, sum of candidates) per contest, so a contest is never
        # counted twice when both the total row and the candidate rows are set.
        check("real results are counted once, not doubled",
              B.counted_votes(real), 1234)

        # The distinction the write path gates on: None and 0 both mean "safe to
        # write", any positive count means "refuse". A falsy-vs-None mix-up here
        # is exactly how the original bug read as correct.
        check("None is not mistaken for votes", bool(B.counted_votes(missing)), False)
        check("0 is not mistaken for votes", bool(B.counted_votes(placeholder)), False)
        check("a positive count is truthy", bool(B.counted_votes(real)), True)

        # A contest total of 0 with a stray candidate tally still counts as real,
        # so a partially-loaded CSV is never silently overwritten.
        partial = os.path.join(tmp, "partial.json")
        write(partial, sections(0, 7))
        check("a candidate tally alone is enough to refuse",
              bool(B.counted_votes(partial)), True)


def workflow_cases():
    """Real results must skip the placeholder-only steps, and nothing else."""
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "output")
        old = os.environ.get("GITHUB_OUTPUT")
        try:
            os.environ["GITHUB_OUTPUT"] = out
            B.signal_results_loaded()
        finally:
            if old is None:
                os.environ.pop("GITHUB_OUTPUT", None)
            else:
                os.environ["GITHUB_OUTPUT"] = old
        with open(out, encoding="utf-8") as fh:
            check("a refusal sets results_loaded", fh.read(), "results_loaded=true\n")

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".github",
                        "workflows", "refresh-general-placeholder.yml")
    with open(path, encoding="utf-8") as fh:
        steps = fh.read().split("      - name: ")[1:]
    gated = [s.split("\n", 1)[0] for s in steps
             if "\n        if: steps.generate.outputs.results_loaded != 'true'\n" in s]
    check("only the placeholder-only steps are skipped", gated,
          ["Validate the rebuild", "Commit and push the refreshed preview",
           "Report what changed"])


if __name__ == "__main__":
    print("counted_votes guard:")
    cases()
    print("workflow gating:")
    workflow_cases()
    if failures:
        print(f"\n{len(failures)} failure(s)")
        sys.exit(1)
    print("\nAll checks passed.")
