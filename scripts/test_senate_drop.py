#!/usr/bin/env python3
"""Invariants of the hand-saved Senate XML path (lib/senate_drop.py).

senate.gov refuses automated clients, so a person saves roll-call XML into
scripts/data/senate-xml/ and both Senate generators read it first. What must hold:

  * Precedence is dropped XML > senate.gov HTTP > Voteview, in every combination.
  * A dropped file is the official record: it replaces a provisional Voteview row
    and never lands in `senateRollsFromVoteview`.
  * An official record already held is immutable - a dropped file for it is ignored.
  * A mis-saved file (challenge page, wrong roll call, not XML) is refused, not trusted.
  * An absent or empty drop directory changes nothing.
  * A dropped roll call Voteview has not published yet is still recorded.

Run: python scripts/test_senate_drop.py        (no network, no repo writes)
"""
import contextlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import senate_drop as D  # noqa: E402
from lib import voteview  # noqa: E402
import generate_federal_votes_data as G  # noqa: E402
import generate_vp_tie_votes as VP  # noqa: E402

failures = []
CONGRESS = G.CURRENT_CONGRESS


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def roll_xml(session, number, tie_breaker=None, yeas=51, nays=49, congress=CONGRESS):
    tb = (f"<tie_breaker><by_whom>Vance</by_whom>"
          f"<tie_breaker_vote>{tie_breaker}</tie_breaker_vote></tie_breaker>") if tie_breaker else ""
    return (f"""<?xml version="1.0" encoding="UTF-8"?>
<roll_call_vote><congress>{congress}</congress><session>{session}</session>
<congress_year>2026</congress_year><vote_number>{number}</vote_number>
<vote_date>November 3, 2026,  06:00 PM</vote_date>
<question>On the Nomination</question><vote_result>Confirmed</vote_result>
<vote_result_text>Nomination Confirmed ({yeas}-{nays})</vote_result_text>
<vote_title>Test nominee</vote_title>
<count><yeas>{yeas}</yeas><nays>{nays}</nays></count>{tb}
<members><member><last_name>Ossoff</last_name><party>D</party><state>GA</state>
<vote_cast>Nay</vote_cast><lis_member_id>S414</lis_member_id></member></members>
</roll_call_vote>""").encode()


def put(directory, session, number, raw):
    (Path(directory) / D.filename(CONGRESS, session, number)).write_bytes(raw)


quiet = lambda: contextlib.redirect_stderr(io.StringIO())  # noqa: E731

# ---- resolver --------------------------------------------------------------
print("resolver")
with tempfile.TemporaryDirectory() as tmp:
    check("missing directory -> no rolls", D.dropped_rolls(CONGRESS, Path(tmp) / "nope"), [])
    check("empty directory -> no rolls", D.dropped_rolls(CONGRESS, tmp), [])
    put(tmp, 2, 257, roll_xml(2, 257))
    put(tmp, 2, 258, roll_xml(2, 258))
    check("valid files listed in order", D.dropped_rolls(CONGRESS, tmp), [(2, 257), (2, 258)])
    check("read_roll returns bytes", D.read_roll(CONGRESS, 2, 257, tmp) is not None, True)

    put(tmp, 2, 259, b"<html><body>challenge</body></html>")
    put(tmp, 2, 260, roll_xml(2, 999))                      # saved under the wrong number
    put(tmp, 2, 261, roll_xml(1, 261))                      # wrong session
    (Path(tmp) / "vote_menu_119_2.xml").write_bytes(roll_xml(2, 1))   # index: never read
    (Path(tmp) / "notes.txt").write_text("hi")
    (Path(tmp) / f"vote_{CONGRESS - 1}_2_00001.xml").write_bytes(roll_xml(2, 1, congress=CONGRESS - 1))
    with quiet():
        found = D.dropped_rolls(CONGRESS, tmp)
    check("html / wrong-number / wrong-session / index / other congress refused",
          found, [(2, 257), (2, 258)])
    check("official_url is the vote's XML",
          D.official_url(119, 2, 257).endswith("vote1192/vote_119_2_00257.xml"), True)

# ---- federal generator: fallback branch -------------------------------------
print("federal generator (senate.gov unreachable)")


def fake_roll(vv, session, number, bioguides):
    return {"bill_type": None, "bill_number": None, "title": "from voteview",
            "question": "On the Nomination", "date": "2026-11-03", "yea": 50, "nay": 50,
            "result": "Nomination Confirmed", "party_tally": None, "member_votes": {}}


def run_generator(tmp, drop, existing_meta=None, voteview_rolls=()):
    out = Path(tmp) / "out.json"
    if existing_meta is not None:
        out.write_text(json.dumps(existing_meta))
    members = Path(tmp) / "members.json"
    members.write_text(json.dumps({"members": []}))
    saved = (G.build_lis_to_bioguide, G.senate_vote_numbers, G.active_years, G.fetch_raw,
             voteview.load_senate, voteview.senate_roll, D.DROP_DIR, G.time.sleep, sys.argv)
    G.build_lis_to_bioguide = lambda: {"S414": "O000174"}
    G.senate_vote_numbers = lambda c, s: []
    G.active_years = lambda c: []
    G.fetch_raw = lambda url, label="": None
    voteview.load_senate = lambda c: {"rolls": {k: {} for k in voteview_rolls},
                                      "casts": {}, "members": {}}
    voteview.senate_roll = fake_roll
    D.DROP_DIR = Path(drop)
    G.time.sleep = lambda s: None
    sys.argv = ["x", str(out), str(members)]
    try:
        with contextlib.redirect_stdout(io.StringIO()), quiet():
            G.main()
    finally:
        (G.build_lis_to_bioguide, G.senate_vote_numbers, G.active_years, G.fetch_raw,
         voteview.load_senate, voteview.senate_roll, D.DROP_DIR, G.time.sleep, sys.argv) = saved
    return json.loads(out.read_text())


K = lambda s, n: G.senate_key(CONGRESS, s, n)  # noqa: E731
with tempfile.TemporaryDirectory() as tmp:
    drop = Path(tmp) / "drop"
    drop.mkdir()

    held_official = {"votes": {K(2, 256): {"chamber": "Senate", "title": "official old"}},
                     "memberVotes": {}, "metadata": {}}

    out = run_generator(tmp, drop, held_official, voteview_rolls=[(2, 257)])
    meta = out["metadata"]
    check("no drop: Voteview row is provisional (today's behaviour)",
          meta.get("senateRollsFromVoteview"), [K(2, 257)])
    check("no drop: held official record carried untouched",
          out["votes"][K(2, 256)]["title"], "official old")

    put(drop, 2, 257, roll_xml(2, 257))
    out = run_generator(tmp, drop, held_official, voteview_rolls=[(2, 257)])
    meta = out["metadata"]
    check("dropped XML beats Voteview for the same roll call",
          out["votes"][K(2, 257)]["yea"], 51)
    check("dropped XML is never provisional", "senateRollsFromVoteview" in meta, False)
    check("dropped XML carries the GA senator's vote",
          out["memberVotes"].get("O000174"), [{"voteId": K(2, 257), "vote": "Nay"}])

    prov = {"votes": {**held_official["votes"], K(2, 257): {"chamber": "Senate", "title": "from voteview"}},
            "memberVotes": {}, "metadata": {"senateRollsFromVoteview": [K(2, 257)]}}
    out = run_generator(tmp, drop, prov, voteview_rolls=[(2, 257)])
    check("dropped XML replaces a PROVISIONAL row and clears the marker",
          (out["votes"][K(2, 257)]["yea"], "senateRollsFromVoteview" in out["metadata"]),
          (51, False))

    put(drop, 2, 256, roll_xml(2, 256))
    out = run_generator(tmp, drop, held_official, voteview_rolls=[])
    check("official record already held is immutable (dropped file ignored)",
          out["votes"][K(2, 256)]["title"], "official old")

    put(drop, 2, 300, roll_xml(2, 300))
    out = run_generator(tmp, drop, held_official, voteview_rolls=[])
    check("dropped roll call Voteview does not have yet is still recorded",
          K(2, 300) in out["votes"] and "senateRollsFromVoteview" not in out["metadata"], True)

    prov2 = {"votes": {K(2, 258): {"chamber": "Senate", "title": "vv"}}, "memberVotes": {},
             "metadata": {"senateRollsFromVoteview": [K(2, 258)]}}
    out = run_generator(tmp, drop, prov2, voteview_rolls=[(2, 258)])
    check("a roll call with no dropped file stays provisional",
          out["metadata"].get("senateRollsFromVoteview"), [K(2, 258)])

# ---- VP tie-break generator -------------------------------------------------
print("VP tie-break generator (senate.gov unreachable)")


def run_vp(tmp, drop, committed, vv_ties=()):
    out = Path(tmp) / "vp.json"
    out.write_text(json.dumps(committed))
    saved = (VP.get_tied_votes_from_list, VP.voteview_tie_breaks, D.DROP_DIR, VP.OUTPUT_FILE)
    VP.get_tied_votes_from_list = lambda c, s: None
    VP.voteview_tie_breaks = lambda c, known: [
        v for v in (dict(voteNumber=n, session=s, date="2026-11-03", question="inferred")
                    for s, n in vv_ties) if (v["session"], v["voteNumber"]) not in known]
    D.DROP_DIR = Path(drop)
    VP.OUTPUT_FILE = str(out)
    try:
        with contextlib.redirect_stdout(io.StringIO()), quiet():
            VP.main()
    finally:
        VP.get_tied_votes_from_list, VP.voteview_tie_breaks, D.DROP_DIR, VP.OUTPUT_FILE = saved
    return json.loads(out.read_text())


with tempfile.TemporaryDirectory() as tmp:
    drop = Path(tmp) / "drop"
    drop.mkdir()
    base = {"metadata": {"congress": CONGRESS}, "votes": []}

    out = run_vp(tmp, drop, base, vv_ties=[(2, "00257")])
    check("no drop: Voteview inference is used (today's behaviour)",
          [v["voteNumber"] for v in out["votes"]], ["00257"])

    put(drop, 2, 257, roll_xml(2, 257, tie_breaker="Nay", yeas=50, nays=50))
    out = run_vp(tmp, drop, base, vv_ties=[(2, "00257")])
    check("official XML supplies a VP Nay Voteview cannot see",
          [(v["voteNumber"], v["vpVote"]) for v in out["votes"]], [("00257", "Nay")])
    check("official tie-break is not marked as from Voteview",
          "votesFromVoteview" in out["metadata"], False)

    put(drop, 2, 258, roll_xml(2, 258, yeas=50, nays=50))   # tied, VP did not vote
    out = run_vp(tmp, drop, base, vv_ties=[(2, "00258")])
    check("official XML with no <tie_breaker> overrides Voteview's inferred tie-break",
          [v for v in out["votes"] if v["voteNumber"] == "00258"], [])

    inferred = {"metadata": {"congress": CONGRESS, "votesFromVoteview": ["2-00257"]},
                "votes": [{"voteNumber": "00257", "session": 2, "date": "2026-11-03",
                           "question": "inferred", "vpVote": "Yea"}]}
    out = run_vp(tmp, drop, inferred, vv_ties=[(2, "00257")])
    check("official XML replaces a previously inferred row",
          [(v["voteNumber"], v["vpVote"]) for v in out["votes"]], [("00257", "Nay")])

if failures:
    print(f"\n{len(failures)} FAILED: {failures}")
    sys.exit(1)
print("\nall ok")
