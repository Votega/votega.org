#!/usr/bin/env python3
"""Invariants of lib/congress_session.py: which Congress is sitting, derived from the date.

A new Congress convenes on 3 January of an odd year (20th Amendment, s.2); on 1-2 January
the outgoing one still holds the seats. Four federal generators read this, so an off-by-one
at the boundary fetches the wrong Congress and the run still looks clean.

Run: python scripts/test_congress_session.py   (no network, no repo writes)
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import congress_session as cs  # noqa: E402


def test_known_congresses():
    assert cs.congress_for_date(date(2025, 6, 1)) == 119
    assert cs.congress_for_date(date(2026, 10, 26)) == 119
    assert cs.congress_for_date(date(2023, 6, 1)) == 118
    assert cs.congress_for_date(date(1789, 6, 1)) == 1


def test_boundary_1_2_january_belong_to_the_outgoing_congress():
    # 119th: 3 Jan 2025 - 2 Jan 2027. 120th: from 3 Jan 2027.
    assert cs.congress_for_date(date(2025, 1, 2)) == 118
    assert cs.congress_for_date(date(2025, 1, 3)) == 119
    assert cs.congress_for_date(date(2026, 12, 31)) == 119
    assert cs.congress_for_date(date(2027, 1, 1)) == 119
    assert cs.congress_for_date(date(2027, 1, 2)) == 119
    assert cs.congress_for_date(date(2027, 1, 3)) == 120
    # Even-year January (mid-Congress) is unaffected: 120th continues past 1 Jan 2028.
    assert cs.congress_for_date(date(2028, 1, 1)) == 120
    assert cs.congress_for_date(date(2028, 1, 3)) == 120


def test_years_and_ordinals():
    assert cs.congress_years(119) == (2025, 2026)
    assert cs.congress_years(120) == (2027, 2028)
    for n, want in ((1, "1st"), (2, "2nd"), (3, "3rd"), (11, "11th"), (12, "12th"),
                    (13, "13th"), (21, "21st"), (111, "111th"), (112, "112th"), (113, "113th"),
                    (119, "119th"), (120, "120th"), (121, "121st"), (122, "122nd"),
                    (123, "123rd"), (124, "124th")):
        assert cs.congress_ordinal(n) == want, (n, cs.congress_ordinal(n))


def test_ordinal_or_unknown():
    assert cs.ordinal_or_unknown(121) == "121st"
    assert cs.ordinal_or_unknown(None) == "?"
    assert cs.ordinal_or_unknown("bad") == "bad"


def test_bill_urls_after_the_120th():
    from lib.federal_sponsorship import bill_url
    import generate_federal_votes_data as votes
    import generate_presidential_laws as laws
    import validate_presidential_laws as vlaws  # noqa: F401  (must import cleanly)
    for n, slug in ((119, "119th"), (121, "121st"), (122, "122nd"), (123, "123rd")):
        want = f"https://www.congress.gov/bill/{slug}-congress/house-bill/1"
        assert bill_url(n, "HR", "1") == want, bill_url(n, "HR", "1")
        for mod, call in ((votes, lambda: votes.bill_fields("hr", "1")[1]),
                          (laws, lambda: laws.build_congress_url("hr", "1"))):
            saved, mod.CURRENT_CONGRESS = mod.CURRENT_CONGRESS, n
            try:
                assert call() == want, (mod.__name__, call())
            finally:
                mod.CURRENT_CONGRESS = saved


def test_no_hardcoded_th_suffix():
    """A computed Congress number followed by a literal "th" is wrong from the 121st on."""
    import re
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bad = re.compile(r"\}th(?:-congress| Congress|\b(?=[\"'`.]))")
    ordinal_helper = re.compile(r"return `\$\{n\}th`|f\"\{n\}th\"")
    found = []
    for top, exts in (("scripts", (".py",)), ("_includes", (".html",)),
                      ("assets/scripts", (".js",)), ("mcp/src", (".ts",))):
        for folder, _dirs, files in os.walk(os.path.join(root, top)):
            if "archive" in folder.replace(os.sep, "/").split("/"):
                continue
            for name in files:
                if not name.endswith(exts) or name.startswith("test_"):
                    continue
                path = os.path.join(folder, name)
                with open(path, encoding="utf-8") as f:
                    for i, line in enumerate(f, 1):
                        if bad.search(line) and not ordinal_helper.search(line):
                            found.append(f"{os.path.relpath(path, root)}:{i}: {line.strip()[:90]}")
    assert not found, "use congress_ordinal()/ordinal():\n" + "\n".join(found)


def test_env_override_and_refusals():
    saved = os.environ.get("CONGRESS")
    try:
        os.environ["CONGRESS"] = "118"
        assert cs.current_congress() == 118
        os.environ["CONGRESS"] = "  "
        assert cs.current_congress() == cs.congress_for_date()
        for bad in ("abc", "0", str(cs.congress_for_date() + 2)):
            os.environ["CONGRESS"] = bad
            try:
                cs.current_congress()
            except ValueError:
                continue
            raise AssertionError(f"CONGRESS={bad!r} should have been refused")
    finally:
        if saved is None:
            os.environ.pop("CONGRESS", None)
        else:
            os.environ["CONGRESS"] = saved


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok  ", name)
            except Exception as e:  # noqa: BLE001
                fails += 1
                print("FAIL", name, "->", e)
    sys.exit(1 if fails else 0)
