#!/usr/bin/env python3
"""build_legislative_races.names_match: the incumbent-detection name rule.

The fallback that links a seat's sitting member to a candidate compared the last
whitespace-separated word of each name, so the ballot's "Alvin Payton Jr" never
matched the roster's "Alvin Payton" (HD 177) and his candidate record carried no
existingMemberId. What must hold:

  * a generational suffix or honorific on either side does not break the match;
  * a different surname, or a different first name and initial, still does not match;
  * a suffix is not mistaken for a surname when it is the only token left.

Run: python scripts/test_names_match.py        (no network, no repo writes)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_legislative_races as B  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


check("Jr on the ballot name", B.names_match("Alvin Payton Jr", "Alvin Payton"), True)
check("Jr on the roster name", B.names_match("Alvin Payton", "Alvin Payton Jr"), True)
check("Jr. with a period", B.names_match("Alvin Payton, Jr.", "Alvin Payton"), True)
check("III", B.names_match("Thomas Smith III", "Tom Smith"), True)
check("honorific", B.names_match("Dr. Jasmine Clark", "Jasmine Clark"), True)
check("parenthetical tag", B.names_match("Jon Ossoff (I)", "Jon Ossoff"), True)
check("plain match unchanged", B.names_match("Elsie Cason Napier", "Elsie Napier"), True)
check("different surname", B.names_match("Alvin Payton Jr", "Alvin Paton"), False)
check("different first name", B.names_match("Bruce Payton", "Alvin Payton"), False)
check("suffix only is not a name", B.names_match("Jr", "Alvin Payton"), False)
check("empty", B.names_match("", "Alvin Payton"), False)

if failures:
    print(f"\n{len(failures)} failed")
    sys.exit(1)
print("\nall passed")
