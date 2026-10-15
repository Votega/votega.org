#!/usr/bin/env python3
"""
Generate federal-member-votes.json for the GA delegation — EVERY roll call of the
current Congress.

Flow:
  1. Senate: the per-session index vote_menu_{congress}_{session}.xml lists every
     vote_number the chamber has held, so two fetches enumerate the whole universe.
     Each number's detail XML then gives the vote.
  2. House: the Clerk publishes no per-year index, so roll{nnn}.xml is walked per
     calendar year until the numbers run out (see the gotcha below).
  3. House XML carries bioguideId directly (`name-id`); Senate LIS ids map through
     the unitedstates/congress-legislators YAML.

Output: assets/data/federal-member-votes.json
  memberVotes keyed by bioguideId — matches the entity page's lookup.

WHY THIS NO LONGER STARTS FROM ENACTED LAWS
-------------------------------------------
This script used to drive off Congress.gov's /v3/law/{congress}, walking each
enacted law's /actions for the roll-call XML URLs those actions referenced. The
universe was therefore "roll calls attached to bills that became law", which by
construction cannot see a bill that died, an amendment, a nomination or any
procedural vote. Measured on 2026-10-14 that was 216 of 1,591 real roll calls —
13.6% — and a House member's party-line denominator was 42 votes. Enumerating the
chambers' own indexes is both complete and cheaper: it needs no Congress.gov API
call at all, so the key and its rate limit are off the critical path entirely.

Congress.gov's beta /house-vote endpoints were considered and rejected: they are
House-only AND legislation-associated, so they do not widen the frame, and
Congress.gov has never carried Senate roll calls.

⚠ A MISSING HOUSE ROLL IS AN HTTP 200, NOT A 404
A roll number that does not exist returns 200 with the body
  <xml>Error sanitizing file "roll700.xml". Please try again.</xml>
so a walk-until-404 loop never terminates and ingests that error body as a vote.
Termination is decided on CONTENT (`looks_like_house_vote`), and because the XML
declaration alone is 38 bytes, the sniff reads well past it before looking for the
rollcall-vote element. A single absent number is also not the end of the year, so
the walk stops only after MISS_STREAK consecutive absences.

INCREMENTAL BY DEFAULT
A full build is ~1,591 fetches (~8 min at XML_DELAY). A normal run reuses every
roll call already in the committed file and fetches only the ones absent from it,
so the weekly workflow costs a few dozen requests and its commit is empty on a
quiet week. Key order is preserved and new keys append, so a no-op run is
byte-identical. `--full-refresh` re-fetches everything.

Usage:
  python scripts/generate_federal_votes_data.py [OUT] [MEMBERS]
  python scripts/generate_federal_votes_data.py --full-refresh
"""

import argparse
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
import yaml
from datetime import date, datetime, timezone

from lib.atomic_io import write_json_atomic
from lib.http import fetch_bytes
from lib.congress_session import current_congress, congress_years

LEGISLATORS_BASE = "https://raw.githubusercontent.com/unitedstates/congress-legislators/main"
HOUSE_ROLL_BASE  = "https://clerk.house.gov/evs"
SENATE_BASE      = "https://www.senate.gov/legislative/LIS"

#: Derived from today's date, not pinned here - see lib/congress_session.py.
CURRENT_CONGRESS = current_congress()
XML_DELAY = 0.3   # Static XML files from Clerk/Senate (no rate limit)

#: Consecutive absent roll numbers that end a House year's walk. One gap is not
#: the end of the year (the Clerk has published non-contiguous numbers), so a
#: single miss must not stop the walk; five in a row is unambiguous.
MISS_STREAK = 5

#: Backstop so a server that answers every probe with something vote-shaped
#: cannot spin forever. The busiest modern House year is ~700 roll calls.
MAX_ROLLS_PER_YEAR = 1200

# Normalize House and Senate vote text to consistent labels
VOTE_MAP = {
    "Yea": "Yea", "Yes": "Yea", "Aye": "Yea",
    "Nay": "Nay", "No": "Nay",
    "Not Voting": "Not Voting", "Present": "Not Voting",
    "Absent": "Absent", "Excused": "Absent",
}

# Pretty bill type labels for display
TYPE_LABEL = {
    "hr": "H.R.", "s": "S.",
    "hjres": "H.J.Res.", "sjres": "S.J.Res.",
    "hconres": "H.Con.Res.", "sconres": "S.Con.Res.",
    "hres": "H.Res.", "sres": "S.Res.",
}

# Congress.gov URL slug per bill type
TYPE_SLUG = {
    "hr": "house-bill", "s": "senate-bill",
    "hjres": "house-joint-resolution", "sjres": "senate-joint-resolution",
    "hconres": "house-concurrent-resolution", "sconres": "senate-concurrent-resolution",
    "hres": "house-resolution", "sres": "senate-resolution",
}

#: Placeholders the Senate record uses where a field is genuinely empty. Carrying
#: them through would publish "No short title on file" as a bill title.
SENATE_NULL_TEXT = {
    "no short title on file",
    "no statement of purpose on file.",
    "no statement of purpose on file",
}


def fetch_raw(url, label=""):
    """Fetch raw bytes from URL. Returns None on 404 or error.

    A 404 here is an expected, uninteresting outcome (a roll-call file that
    does not exist), so it stays unlogged via quiet_statuses. Everything else
    follows the shared 429/5xx retry policy.
    """
    return fetch_bytes(url, label=label or url[:80], quiet_statuses=(404,))


def sitting_ga_bioguides(members_file):
    """Set of bioguideIds for the current GA delegation, from current-members.json.
    Used to tell a benign stale vote record (a member who left mid-Congress but
    whose recorded votes remain) apart from a real drop — a *sitting* member with
    no votes. See CODEBASE-REVIEW-2026-08-18.md finding 5.5."""
    try:
        with open(members_file, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None  # unknown -> skip the check rather than emit a wrong count
    return {
        m["bioguideId"] for m in data.get("members", [])
        if m.get("state") == "Georgia" and m.get("bioguideId")
    }


def build_lis_to_bioguide():
    """Return {lis_id: bioguideId} from congress-legislators YAML (senators only)."""
    raw = fetch_raw(f"{LEGISLATORS_BASE}/legislators-current.yaml", "legislators-current.yaml")
    if not raw:
        print("  Warning: could not fetch legislators YAML — Senate LIS mapping will be empty")
        return {}
    legislators = yaml.safe_load(raw.decode("utf-8")) or []
    index = {}
    for leg in legislators:
        ids = leg.get("id", {})
        lis = ids.get("lis")
        bioguide = ids.get("bioguide")
        if lis and bioguide:
            index[str(lis)] = bioguide
    print(f"  LIS→bioguide map: {len(index)} entries")
    return index


# ---------------------------------------------------------------------------
# Bill identification
#
# The enacted-bills driver handed each roll call its bill label, URL and title.
# With the chambers' own indexes driving instead, all three come out of the vote
# XML — and for a motion to adjourn, a quorum call or a Senate nomination there is
# no bill at all, so `bill`/`billUrl` are None (never "", per CLAUDE.md) and every
# consumer has to render a bill-less row.
# ---------------------------------------------------------------------------

def normalize_type(raw):
    """Collapse any of the record's bill-type spellings to a TYPE_SLUG key.

    The two chambers write the same thing three ways: the House's <legis-num> uses
    spaces ("H R 6938", "H CON RES 14"), the Senate's <document_type> uses periods
    ("H.R.", "S.J.Res."), and TYPE_SLUG keys are bare ("hr", "sconres"). Returns
    None for anything that is not a measure — "QUORUM", "PN" (a nomination), "".
    """
    key = re.sub(r"[^a-z]", "", str(raw or "").lower())
    return key if key in TYPE_SLUG else None


def split_measure(raw):
    """'H R 6938' / 'S.Con.Res. 33' -> ('hr', '6938') / ('sconres', '33').

    Returns (None, None) when the string names no measure, which is the normal
    outcome for a quorum call or a nomination rather than an error.
    """
    text = str(raw or "").strip()
    if not text:
        return None, None
    m = re.search(r"(\d+)\s*$", text)
    if not m:
        return None, None
    bill_type = normalize_type(text[:m.start()])
    return (bill_type, m.group(1)) if bill_type else (None, None)


def bill_fields(bill_type, bill_number):
    """(label, url) for a measure, or (None, None) for a bill-less vote."""
    if not bill_type or not bill_number:
        return None, None
    prefix = TYPE_LABEL.get(bill_type, bill_type.upper())
    slug = TYPE_SLUG.get(bill_type, bill_type)
    return (f"{prefix} {bill_number}",
            f"https://www.congress.gov/bill/{CURRENT_CONGRESS}th-congress/{slug}/{bill_number}")


def clean_text(raw):
    """Collapse whitespace; None for an empty value or a Senate 'none on file'
    placeholder. Optional fields are null, never "" (CLAUDE.md)."""
    text = re.sub(r"\s+", " ", str(raw or "")).strip()
    if not text or text.lower() in SENATE_NULL_TEXT:
        return None
    return text


MONTH_MAP = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04",
    "may": "05", "jun": "06", "jul": "07", "aug": "08",
    "sep": "09", "oct": "10", "nov": "11", "dec": "12",
}

def normalize_date(raw):
    """Normalize various date formats to YYYY-MM-DD."""
    if not raw:
        return ""
    # "16-Jan-2025" (House <action-date>)
    m = re.match(r"(\d{1,2})-([A-Za-z]+)-(\d{4})", raw)
    if m:
        mon = MONTH_MAP.get(m.group(2).lower(), "00")
        return f"{m.group(3)}-{mon}-{int(m.group(1)):02d}"
    # "January 21, 2025" / "April 23, 2026,  01:51 AM" (Senate <vote_date>)
    m = re.search(r"([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})", raw)
    if m:
        mon = MONTH_MAP.get(m.group(1).lower()[:3], "00")
        return f"{m.group(3)}-{mon}-{int(m.group(2)):02d}"
    # Already ISO or partial ISO — return as-is (truncate to date portion)
    return raw[:10]


# ---------------------------------------------------------------------------
# Parsers — unchanged in how they read the two XML formats, the party totals and
# the member join. What changed is that each now derives its own bill identity
# from the XML instead of being handed one by the enacted-bills driver.
# ---------------------------------------------------------------------------

#: Result vocabulary shared by both chambers. One implementation, because the two
#: parsers had drifted: the House branch tested only for "pass", so every
#: "Agreed to" / "Adopted" roll call was published as a FAILURE - H.Res. 1014 of
#: 2026 (427-0, Agreed to) rendered as "Failed". The enacted-law frame hid this,
#: because an amendment or a resolution vote almost never reached it.
#:
#: Negations are tested FIRST and on purpose: "Decision of Chair Not Sustained"
#: contains "sustained", so a pass-first test reads the chair being OVERRULED as
#: the chair being upheld - the exact inversion, on the exact votes where it is
#: most load-bearing.
FAIL_FIRST = ("not sustained", "not agreed", "not well taken", "not passed",
              "not adopted", "not confirmed", "not approved")
PASS_WORDS = ("pass", "agreed", "adopted", "confirmed", "approved",
              "sustained", "well taken")
FAIL_WORDS = ("fail", "reject", "defeat", "lost", "overruled", "tabled")

UNKNOWN_RESULTS = {}


def pass_fail(result_text):
    """'Pass'/'Fail' from a chamber's own result wording.

    Some roll calls answer a question that is neither: the election of a Speaker
    records the winner's NAME as its result. Rather than assert a pass or a
    failure there, the chamber's own wording is carried through unchanged (the UI
    already falls back to printing `result` verbatim) and the run reports it, so a
    new kind of result shows up as a line in the log instead of being silently
    published as a defeat.
    """
    text = (result_text or "").strip()
    low = text.lower()
    if any(w in low for w in FAIL_FIRST):
        return "Fail"
    if any(w in low for w in PASS_WORDS):
        return "Pass"
    if any(w in low for w in FAIL_WORDS):
        return "Fail"
    UNKNOWN_RESULTS[text or "(empty)"] = UNKNOWN_RESULTS.get(text or "(empty)", 0) + 1
    return text or "Unknown"


def looks_like_house_vote(xml_bytes):
    """True only for a real Clerk roll-call document.

    A nonexistent roll number answers 200 with
    `<xml>Error sanitizing file "roll700.xml". Please try again.</xml>`, so status
    cannot be the signal. The XML declaration alone is 38 bytes and the error body
    is 65, so the sniff deliberately reads a few KB rather than peeking at the head.
    """
    if not xml_bytes or len(xml_bytes) < 200:
        return False
    head = xml_bytes[:4096]
    if b"Error sanitizing" in head:
        return False
    return b"<rollcall-vote" in head


def parse_house_vote(xml_bytes, year):
    """
    Parse Clerk of House roll call XML.
    Returns (vote_meta, {bioguideId: vote_label}) for GA members only.
    bioguideId is in the name-id attribute; state="GA" filters to GA delegation.
    """
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        print(f"  XML parse error: {e}")
        return None, {}

    meta = root.find(".//vote-metadata")
    if meta is None:
        return None, {}

    def txt(tag):
        el = meta.find(tag)
        return (el.text or "").strip() if el is not None else ""

    action_date = txt("action-date")
    question    = txt("vote-question")
    result_text = txt("vote-result")

    # <legis-num> is the measure the vote concerns — including on an amendment
    # vote, where it names the underlying bill. It is "QUORUM" (or empty) for the
    # non-legislative roll calls the old enacted-law frame could never surface.
    bill_type, bill_number = split_measure(txt("legis-num"))
    bill_label, bill_page  = bill_fields(bill_type, bill_number)

    yea = nay = 0
    for totals in root.findall(".//totals-by-vote"):
        for child in totals:
            t = (child.tag or "").lower().replace("-", "_")
            try:
                val = int(child.text or 0)
            except (ValueError, TypeError):
                continue
            if t in ("yea_total", "yes_total", "aye_total"):
                yea += val
            elif t in ("nay_total", "no_total"):
                nay += val

    # Whole-chamber party breakdown, straight from the Clerk's <totals-by-party>
    # blocks (Republican / Democratic / Independent). "other" folds present +
    # not-voting so the Yea/Nay/other shape matches the GA member page.
    party_tally = {}
    for tbp in root.findall(".//totals-by-party"):
        party = (tbp.findtext("party") or "").strip()
        if not party:
            continue
        def _pint(tag, node=tbp):
            try:
                return int(node.findtext(tag) or 0)
            except (ValueError, TypeError):
                return 0
        party_tally[party] = {
            "yea":   _pint("yea-total"),
            "nay":   _pint("nay-total"),
            "other": _pint("present-total") + _pint("not-voting-total"),
        }

    vote_meta = {
        "bill":       bill_label,
        "billUrl":    bill_page,
        "billType":   bill_type,
        "billNumber": bill_number,
        "title":      clean_text(txt("vote-desc")),
        "motionText": question,
        "date":       normalize_date(action_date),
        "yea":        yea,
        "nay":        nay,
        "chamber":    "House",
        "session":    1 if year == congress_years(CURRENT_CONGRESS)[0] else 2,
        "rollNumber": int(txt("rollcall-num") or 0) or None,
        "result":     pass_fail(result_text),
        "resultText": clean_text(result_text),
        "partyTally": party_tally or None,
    }

    ga_votes = {}
    for rv in root.findall(".//recorded-vote"):
        leg = rv.find("legislator")
        if leg is None:
            continue
        if (leg.get("state") or "").upper() != "GA":
            continue
        bioguide  = (leg.get("name-id") or "").strip()
        v_el      = rv.find("vote")
        vote_text = (v_el.text or "").strip() if v_el is not None else ""
        label     = VOTE_MAP.get(vote_text, vote_text or "Other")
        if bioguide:
            ga_votes[bioguide] = label

    return vote_meta, ga_votes


def senate_measure(root):
    """(bill_type, bill_number, title) for a Senate roll call.

    Three shapes, and only the first is a bill:
      <document> S. / H.R. / S.J.Res. ...  -> the measure itself
      <document> S.Amdt. ...               -> an amendment; the clickable measure
                                              is <amendment_to_document_number>,
                                              which is how the House records an
                                              amendment vote too (legis-num names
                                              the underlying bill)
      <document> PN ...                    -> a nomination: no bill exists
    """
    doc = root.find("./document")
    doc_type = doc.findtext("document_type") if doc is not None else ""
    bill_type = normalize_type(doc_type)
    bill_number = clean_text(doc.findtext("document_number")) if doc is not None else None

    title = None
    if doc is not None:
        title = (clean_text(doc.findtext("document_short_title"))
                 or clean_text(doc.findtext("document_title")))

    if bill_type and bill_number:
        return bill_type, bill_number, title

    # Amendment: carry the underlying measure, and the amendment's own purpose as
    # the title (the amendment number itself is already in the question text).
    amdt = root.find("./amendment")
    if amdt is not None and clean_text(amdt.findtext("amendment_number")):
        a_type, a_num = split_measure(amdt.findtext("amendment_to_document_number"))
        a_title = (clean_text(amdt.findtext("amendment_to_document_short_title"))
                   or clean_text(amdt.findtext("amendment_purpose")))
        return a_type, a_num, title or a_title

    # Nomination or anything else with no measure: no bill, but the record still
    # has a subject worth printing (the nominee line).
    return None, None, title or clean_text(root.findtext("vote_document_text"))


def parse_senate_vote(xml_bytes, lis_to_bioguide):
    """
    Parse Senate.gov roll call XML.
    Returns (vote_meta, {bioguideId: vote_label}) for GA senators only.
    Uses lis_to_bioguide map to convert LIS member IDs.
    """
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        print(f"  XML parse error: {e}")
        return None, {}

    def txt(path):
        el = root.find(path)
        return (el.text or "").strip() if el is not None else ""

    question  = txt(".//question")
    result    = txt(".//vote_result")
    vote_date = txt(".//vote_date")
    yea       = int(txt(".//count/yeas") or 0)   # Senate XML nests these under <count>
    nay       = int(txt(".//count/nays") or 0)

    bill_type, bill_number, title = senate_measure(root)
    bill_label, bill_page = bill_fields(bill_type, bill_number)

    # Senate XML has no party totals, so tally every member's vote by party.
    # Party letters (D/R/I/ID) map to the same names the House XML and the GA
    # member page use.
    PARTY_NAME = {"D": "Democratic", "R": "Republican", "I": "Independent", "ID": "Independent"}
    party_tally = {}
    for member in root.findall(".//member"):
        pletter = (member.findtext("party") or "").strip().upper()
        pname   = PARTY_NAME.get(pletter, pletter or "Other")
        label   = VOTE_MAP.get((member.findtext("vote_cast") or "").strip(), "Other")
        bucket  = party_tally.setdefault(pname, {"yea": 0, "nay": 0, "other": 0})
        if label == "Yea":
            bucket["yea"] += 1
        elif label == "Nay":
            bucket["nay"] += 1
        else:
            bucket["other"] += 1

    vote_meta = {
        "bill":       bill_label,
        "billUrl":    bill_page,
        "billType":   bill_type,
        "billNumber": bill_number,
        "title":      title,
        "motionText": question,
        "date":       normalize_date(vote_date),
        "yea":        yea,
        "nay":        nay,
        "chamber":    "Senate",
        "session":    int(txt("./session") or 0) or None,
        "rollNumber": int(txt("./vote_number") or 0) or None,
        # "Nomination Confirmed" and "Cloture Motion Agreed to" are both passes;
        # "Amendment Rejected" is not. See pass_fail().
        "result":     pass_fail(result),
        "resultText": clean_text(result),
        "partyTally": party_tally or None,
    }

    ga_votes = {}
    for member in root.findall(".//member"):
        state = (member.findtext("state") or "").strip().upper()
        if state != "GA":
            continue
        lis_id    = (member.findtext("lis_member_id") or "").strip()
        vote_cast = (member.findtext("vote_cast") or "").strip()
        label     = VOTE_MAP.get(vote_cast, vote_cast or "Other")
        bioguide  = lis_to_bioguide.get(lis_id)
        if bioguide:
            ga_votes[bioguide] = label
        elif lis_id:
            print(f"    Warning: no bioguide for GA senator LIS ID {lis_id}")

    return vote_meta, ga_votes


# ---------------------------------------------------------------------------
# Enumerating the universe
# ---------------------------------------------------------------------------

def senate_vote_numbers(congress, session):
    """Every vote_number the Senate held in this session, from its own index.

    The per-session menu is the complete list, so one fetch replaces any probing.
    Returns [] for a session that has not begun (the menu 404s), which is the
    normal state of session 2 during the first year.
    """
    url = f"{SENATE_BASE}/roll_call_lists/vote_menu_{congress}_{session}.xml"
    raw = fetch_raw(url, f"vote_menu_{congress}_{session}.xml")
    if not raw:
        print(f"  Senate session {session}: no index (not yet in session?)")
        return []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        print(f"  Senate session {session}: index did not parse ({exc})", file=sys.stderr)
        return []
    numbers = []
    for vote in root.findall("./votes/vote"):
        raw_num = (vote.findtext("vote_number") or "").strip()
        if raw_num.isdigit():
            numbers.append(int(raw_num))
    numbers.sort()
    print(f"  Senate session {session}: {len(numbers)} roll calls indexed "
          f"(highest {numbers[-1] if numbers else 0})")
    return numbers


def senate_vote_url(congress, session, number):
    return (f"{SENATE_BASE}/roll_call_votes/vote{congress}{session}"
            f"/vote_{congress}_{session}_{number:05d}.xml")


def house_roll_url(year, number):
    return f"{HOUSE_ROLL_BASE}/{year}/roll{number:03d}.xml"


def senate_key(congress, session, number):
    return f"S{congress}_{session}_{number:05d}"


def house_key(year, number):
    return f"H{year}_{number:04d}"


def active_years(congress):
    """The congress's calendar years that have actually started."""
    this_year = date.today().year
    return [y for y in congress_years(congress) if y <= this_year]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("output", nargs="?", default="assets/data/federal-member-votes.json")
    ap.add_argument("members", nargs="?", default="assets/data/current-members.json")
    ap.add_argument("--full-refresh", action="store_true",
                    help="re-fetch every roll call instead of reusing the committed "
                         "file's records (slow: ~1,600 fetches)")
    args = ap.parse_args()

    out_file, members_file = args.output, args.members

    # Reuse layer. A roll call is immutable once the chamber has published it, so
    # anything already in the committed file is taken as-is and never re-fetched.
    existing_votes, existing_member_votes = {}, {}
    if not args.full_refresh:
        try:
            with open(out_file, encoding="utf-8") as fh:
                prev = json.load(fh)
            existing_votes = prev.get("votes") or {}
            existing_member_votes = prev.get("memberVotes") or {}
            print(f"Reusing {len(existing_votes)} roll calls already in {out_file}")
        except (OSError, ValueError):
            print(f"No reusable {out_file} — building from scratch")

    print("\nBuilding LIS→bioguide senator ID map from congress-legislators...")
    lis_to_bioguide = build_lis_to_bioguide()

    # The member's vote on a REUSED roll call lives in the existing memberVotes,
    # so invert it once: voteId -> {bioguide: label}.
    reusable_ga = {}
    for bioguide, entries in existing_member_votes.items():
        for entry in entries or []:
            vote_id = entry.get("voteId")
            if vote_id in existing_votes:
                reusable_ga.setdefault(vote_id, {})[bioguide] = entry.get("vote")

    votes_meta   = {}
    member_votes = {}
    fetched = reused = 0

    def record(vote_key, vote_meta, ga_votes):
        votes_meta[vote_key] = vote_meta
        for bioguide, vote_label in ga_votes.items():
            member_votes.setdefault(bioguide, []).append({
                "voteId": vote_key,
                "vote":   vote_label,
            })

    # -- Senate: two index fetches enumerate the whole universe ---------------
    print(f"\nSenate roll calls, {CURRENT_CONGRESS}th Congress...")
    for session in (1, 2):
        for number in senate_vote_numbers(CURRENT_CONGRESS, session):
            vote_key = senate_key(CURRENT_CONGRESS, session, number)
            if vote_key in existing_votes:
                record(vote_key, existing_votes[vote_key], reusable_ga.get(vote_key, {}))
                reused += 1
                continue
            time.sleep(XML_DELAY)
            raw = fetch_raw(senate_vote_url(CURRENT_CONGRESS, session, number), vote_key)
            if not raw:
                print(f"    {vote_key}: detail XML unavailable — skipped")
                continue
            vote_meta, ga_votes = parse_senate_vote(raw, lis_to_bioguide)
            if not vote_meta:
                continue
            record(vote_key, vote_meta, ga_votes)
            fetched += 1
            if fetched % 50 == 0:
                print(f"    {fetched} fetched · {reused} reused · {len(votes_meta)} total")

    # -- House: no index, so walk the roll numbers per calendar year ----------
    print(f"\nHouse roll calls, {CURRENT_CONGRESS}th Congress...")
    for year in active_years(CURRENT_CONGRESS):
        misses = 0
        found = 0
        number = 0
        while number < MAX_ROLLS_PER_YEAR and misses < MISS_STREAK:
            number += 1
            vote_key = house_key(year, number)
            if vote_key in existing_votes:
                record(vote_key, existing_votes[vote_key], reusable_ga.get(vote_key, {}))
                reused += 1
                found += 1
                misses = 0
                continue
            time.sleep(XML_DELAY)
            raw = fetch_raw(house_roll_url(year, number), vote_key)
            # Content, not status: an absent roll answers 200 with an error body.
            if not looks_like_house_vote(raw):
                misses += 1
                continue
            misses = 0
            vote_meta, ga_votes = parse_house_vote(raw, year)
            if not vote_meta:
                continue
            record(vote_key, vote_meta, ga_votes)
            found += 1
            fetched += 1
            if fetched % 50 == 0:
                print(f"    {fetched} fetched · {reused} reused · {len(votes_meta)} total")
        if number >= MAX_ROLLS_PER_YEAR:
            print(f"  WARNING: {year} hit the {MAX_ROLLS_PER_YEAR}-roll backstop — "
                  "the walk may be truncated", file=sys.stderr)
        print(f"  {year}: {found} roll calls (walk stopped after "
              f"{misses} consecutive absences at roll {number})")

    # Reconcile vote records against the sitting delegation so a real drop is
    # visible in metadata rather than blending into the benign stale case.
    with_votes = set(member_votes)
    sitting = sitting_ga_bioguides(members_file)
    vote_stats = {}
    if sitting is not None:
        sitting_with_votes = sitting & with_votes
        stale = with_votes - sitting          # departed members, votes linger
        missing = sitting - with_votes        # sitting members with NO votes = a real drop
        vote_stats = {
            "sittingDelegation":       len(sitting),
            "sittingMembersWithVotes": len(sitting_with_votes),
            "staleVoteRecords":        len(stale),
        }
        if missing:
            print(f"  WARNING: {len(missing)} sitting GA member(s) have no vote records: "
                  f"{sorted(missing)}", file=sys.stderr)
            vote_stats["sittingMembersMissingVotes"] = sorted(missing)

    by_chamber = {}
    bill_less = 0
    for meta in votes_meta.values():
        by_chamber[meta.get("chamber") or "?"] = by_chamber.get(meta.get("chamber") or "?", 0) + 1
        if not meta.get("bill"):
            bill_less += 1

    output = {
        "metadata": {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "congress":    CURRENT_CONGRESS,
            "sessionName": f"{CURRENT_CONGRESS}th Congress",
            "source":      "Clerk of the House + Senate.gov roll-call XML",
            "scope":       "every recorded roll call of the Congress, including "
                           "failed measures, amendments, procedural motions and "
                           "Senate nominations",
            "totalVotes":  len(votes_meta),
            "houseVotes":  by_chamber.get("House", 0),
            "senateVotes": by_chamber.get("Senate", 0),
            "billLessVotes": bill_less,
            "memberCount": len(member_votes),
            "updateMode":  "full" if args.full_refresh else "incremental",
            "rollCallsFetchedThisRun": fetched,
            **vote_stats,
        },
        "votes":       votes_meta,
        "memberVotes": member_votes,
    }

    write_json_atomic(out_file, output, separators=(",", ":"))

    if UNKNOWN_RESULTS:
        print("  NOTE: result wording outside the pass/fail vocabulary, carried through verbatim: "
              + ", ".join(f"{k!r}x{v}" for k, v in sorted(UNKNOWN_RESULTS.items())),
              file=sys.stderr)

    size_kb = os.path.getsize(out_file) // 1024
    print(f"\nDone. {len(votes_meta)} votes "
          f"({by_chamber.get('House', 0)} House / {by_chamber.get('Senate', 0)} Senate, "
          f"{bill_less} with no associated measure) · "
          f"{len(member_votes)} GA members · {fetched} fetched, {reused} reused · "
          f"{size_kb} KB → {out_file}")


if __name__ == "__main__":
    main()
