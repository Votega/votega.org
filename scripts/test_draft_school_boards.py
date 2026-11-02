#!/usr/bin/env python3
"""Invariants of the school-board drafter's pure logic. No network, no deps.

draft_school_boards.py reaches the Secretary of State's API only inside
draft_county() and list_counties(); classification, city routing, seat ordering
and YAML emission are pure, and this suite drives those. scripts/test_*.py run in
CI with no pip packages and no network, so nothing here fetches anything.

What is pinned, and why:
  * BOTH REAL OFFICE SHAPES CLASSIFY. The SoS uses "County BOE - District 2"
    (Cobb, Jackson, Newton, Whitfield) and "Board of Education - District 4"
    (Thomas). Missing either silently drops a whole county's board.
  * A BOARD-ADJACENT BALLOT QUESTION IS NOT A SEAT. An ESPLOST referendum or a
    superintendent contest matches the word "school"/"board of education" but
    must never become a roster row.
  * NO SUPERINTENDENT, EVER, and no role above Board Member. Superintendents are
    hired by the board, not elected; a chair is chosen by the board from among
    its members, not elected as chair by voters. Inferring either from results
    would assert something the election did not decide.
  * A CITY CONTEST ROUTES TO ITS CITY SYSTEM, not the county's. Putting Marietta's
    board on Cobb County's roster would be wrong about who governs whom.
  * PARTISANSHIP IS CONCLUDED IN ONE DIRECTION ONLY. A party label proves a
    partisan ballot; its absence does not prove nonpartisan, because an unopposed
    candidate with no recorded party looks identical. So absence yields a
    suggestion the curator must confirm, never `partisan: false`.
  * A SUB-50% LEADER IS FLAGGED. Georgia's majority rule sends it to a runoff the
    portal does not carry, so it is not the winner.

Run: python scripts/test_draft_school_boards.py
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
# generate_local_officials imports only the standard library at module level.
import draft_school_boards as D  # noqa: E402

failures = []


def check(cond, msg):
    print('  %s  %s' % ('ok  ' if cond else 'FAIL', msg))
    if not cond:
        failures.append(msg)


print('Both real office shapes classify')
for office, seat in (
        ("County BOE - District 2", "District 2"),
        ("Board of Education - District 4", "District 4"),
        ("County BOE - District 7", "District 7"),
        ("Board of Education, Post 3", "Post 3"),
        ("County BOE - At Large", "At-Large"),
        ("Board of Education At-Large", "At-Large")):
    got = D.classify(office)
    check(got == ("Board Member", seat),
          '%r -> %r' % (office, (got or (None, None))[1]))
check(D.classify("County BOE - District 2")[0] == "Board Member",
      'every drafted role is Board Member — a chair is chosen BY the board, not '
      'elected as chair by voters')

print('\nBoard-adjacent ballot questions are not seats')
for office in ("School Superintendent",
               "Board of Education ESPLOST Referendum",
               "School District Sales Tax Question",
               "County BOE Bond Referendum",
               "Charter School Amendment"):
    check(D.classify(office) is None, '%r is not a seat' % office)
check(D.classify("County Commission - District 2") is None,
      'a commission seat is not a board seat (that is the other drafter)')
check(D.classify("") is None and D.classify(None) is None,
      'empty input classifies as nothing rather than raising')

print('\nAn unlabelled board contest is kept, not dropped')
got = D.classify("County BOE")
check(got and got[0] == 'Board Member' and got[1] == 'County BOE',
      'a recognised board contest with no district/post falls back to the '
      'verbatim office as the seat, so a human can fix it: %r' % (got,))

print('\nCity contests route to the city system')
cobb_cities = [{"id": "781", "name": "Marietta City", "counties": ["cobb"]}]
check((D.city_district_for("Marietta City BOE - District 1", cobb_cities) or {})
      .get("id") == "781",
      'a Marietta contest routes to Marietta City Schools, not Cobb County')
check(D.city_district_for("County BOE - District 1", cobb_cities) is None,
      'a County BOE contest routes to the county system')
decatur = [{"id": "773", "name": "City Schools of Decatur", "counties": ["dekalb"]}]
check((D.city_district_for("City Schools of Decatur BOE - District 2", decatur) or {})
      .get("id") == "773",
      '"City Schools of Decatur" is matched despite the inverted name')
check(D.city_district_for("County BOE - District 2", decatur) is None,
      'and DeKalb County BOE still routes to the county')
check(D.city_district_for("County BOE - District 2", None) is None,
      'a county with no city systems routes everything to the county')

print('\nSeat ordering')
seats = ["District 10", "At-Large", "District 2", "Post 1"]
check([s for s in sorted(seats, key=D._seat_key)]
      == ["Post 1", "District 2", "District 10", "At-Large"],
      'numeric seats sort numerically (2 before 10) and unnumbered ones last: %r'
      % sorted(seats, key=D._seat_key))

print('\nThe three alias counties are explicit, not guessed')
check(set(D._COUNTY_ALIASES) == {"chatham", "spalding", "upson"},
      'the county systems whose NAME omits their county are aliased by id')
check(D._COUNTY_ALIASES["chatham"] == "625"
      and D._COUNTY_ALIASES["spalding"] == "726"
      and D._COUNTY_ALIASES["upson"] == "745",
      'Savannah-Chatham 625, Griffin-Spalding 726, Thomaston-Upson 745')

print('\nEmission: what a curator sees')
district = {"id": "707", "name": "Newton County"}
partisan_bucket = {
    "partisan": True, "evidence": "2 of 2 candidates carry a party label",
    "members": [{"name": "Eddie Johnson", "role": "Board Member",
                 "seat": "District 2", "party": "Democratic",
                 "last_elected": 2024, "_share": 0.99,
                 "source": "https://example/api", "_office": "County BOE - District 2"}],
}
out = D.emit(district, partisan_bucket)
check("partisan: true" in out and "carry a party label" in out,
      'a partisan district emits `partisan: true` WITH its evidence')
check("role: Board Member" in out and "party: Democratic" in out,
      'the member carries its role and real party')
check("term_end:" in out and "no machine source" in out,
      'term_end / next_election are emitted blank with the reason')
check("# SoS office: County BOE - District 2" in out,
      'the verbatim SoS office label is kept as provenance')

unlabelled = {
    "partisan": None, "evidence": "no candidate carried a party label (1 seat(s))",
    "members": [{"name": "A B", "role": "Board Member", "seat": "District 1",
                 "party": None, "last_elected": 2024, "_share": 0.9,
                 "source": "https://example/api", "_office": "County BOE - District 1",
                 "_no_party_label": True}],
}
out2 = D.emit(district, unlabelled)
check("# partisan: false" in out2,
      'with no labels, `partisan: false` is COMMENTED OUT — a suggestion, never '
      'asserted, because an unopposed candidate with no party looks the same')
check("partisan: false" not in out2.replace("# partisan: false", ""),
      'and it is not emitted live anywhere else in the block')
check("# party:" in out2 and "Nonpartisan" in out2,
      'the party line is commented with the instruction to set Nonpartisan if the '
      'district really is nonpartisan')

runoff = {
    "partisan": True, "evidence": "1 of 3 candidates carry a party label",
    "members": [{"name": "C D", "role": "Board Member", "seat": "District 3",
                 "party": "Republican", "last_elected": 2024, "_share": 0.41,
                 "source": "https://example/api", "_office": "County BOE - District 3",
                 "_needs_runoff_check": True}],
}
out3 = D.emit(runoff and district, runoff)
check("UNDER 50" in out3 and "runoff" in out3.lower(),
      'a sub-50% leader is flagged in the emitted YAML, not silently drafted as '
      'the winner')
check("41.0%" in out3, 'and the actual share is shown')

print('\nNothing emitted is a Superintendent')
check("Superintendent" not in out and "Superintendent" not in out2
      and "Superintendent" not in out3,
      'no emitted block mentions Superintendent — they are hired, not elected')

print('\nThe emitted YAML is valid YAML at the right indentation')
try:
    import yaml as _y
except ImportError:
    _y = None
if _y is None:
    check(True, '(skipped: pyyaml unavailable, which is the CI case)')
else:
    doc = _y.safe_load("countyDistricts:\n  - id: \"707\"\n    name: Newton County\n"
                       "    type: county\n    countyFips: \"13217\"\n"
                       + "\n".join(l for l in out.splitlines()
                                   if not l.strip().startswith('# ---')))
    e = doc["countyDistricts"][0]
    check(e.get("partisan") is True and len(e.get("members") or []) == 1,
          'it parses back with the partisan flag and the member attached')
    check(e["members"][0]["party"] == "Democratic"
          and e["members"][0]["seat"] == "District 2",
          'and the member round-trips intact')

if failures:
    print('\n%d check(s) FAILED' % len(failures))
    sys.exit(1)
print('\nAll school-board drafter invariants hold.')
