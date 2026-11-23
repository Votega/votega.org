#!/usr/bin/env python3
"""The 119th -> 120th (and every later) Congress changeover, as a recognised event.

`generate_current_members_data.py` used to exit 1 whenever more than 25 members were
flagged as no longer serving. Inside a Congress that is the right answer (a flag or the
API changed; Congress did not empty out). On the day a new Congress is seated it is wrong:
a normal turnover retires 40-70 members, so the first run of the 120th would fail until a
person intervened, and the only way to intervene was to remove the guard. This module is
the deliberate path instead, in the spirit of the GA bills rollover (lib/ga_bills_rollover):

  * the changeover is DETECTED, not asked for: the committed roster's Congress number
    (metadata.congress; before that field existed, the sponsorship index's) is older than
    lib.congress_session says is sitting;
  * it is never silent: the output carries `metadata.rollover`, and the validator refuses a
    changed Congress without it (and a large drop without it);
  * it trades the blunt ">25" for sanity checks that mean something at a turnover;
  * it refuses until the outgoing Congress has a FINAL freeze in
    Votega/ga-federal-legislators (sessions/<slug>/freeze.json), because the daily publish
    replaces data/ in place (CLAUDE.md, "A finished Congress is frozen ...").

Pure functions; the only I/O is the injectable `fetch` for the freeze check.
"""

import json
import os
import urllib.error
import urllib.request
from datetime import date

from lib.congress_session import congress_ordinal, congress_years

GA_HOUSE_SEATS = 14
GA_SENATE_SEATS = 2

#: A seated Congress has 435 + 100 + 6 delegates/commissioner (validate_current_members
#: SEATS_MAX is 541). At a turnover the roster must look like a Congress, not a fragment.
#: Scoped to a turnover on purpose: inside a Congress vacancies are a fact (tier 2).
TURNOVER_MIN_MEMBERS = 500
TURNOVER_MAX_MEMBERS = 541

#: Share of members whose latest term begins in the new Congress's first year. Congress.gov
#: records one term per Congress, so once the new Congress is listed essentially every
#: sitting member has one (re-elected or not). The raw list still carries the outgoing
#: Congress's leavers (their terms end in the new year, so they pass the endYear filter
#: until the detail lookup flags them), hence the lower bar before enrichment.
RAW_NEW_TERM_SHARE_MIN = 0.75
SITTING_NEW_TERM_SHARE_MIN = 0.9

#: How long a run may hold on the old roster waiting for Congress.gov to list the new
#: Congress. Past this the hold is a failure, so a wrong signal cannot hide behind exit 0.
HOLD_GRACE_DAYS = 7

FREEZE_RAW = ("https://raw.githubusercontent.com/Votega/ga-federal-legislators/main/"
              "sessions/{slug}/{name}")

ENV_FREEZE_CONFIRMED = "FEDERAL_FREEZE_CONFIRMED"
ENV_ACCEPT_TURNOVER = "FEDERAL_ACCEPT_TURNOVER"
ENV_GA_VACANT = "FEDERAL_GA_VACANT"

IN_CONGRESS, TURNOVER, REGRESSION, UNKNOWN = "in-congress", "turnover", "regression", "unknown"


def _terms(m):
    return (m.get("terms") or {}).get("item") or []


def chamber_of(m):
    t = _terms(m)
    return t[-1].get("chamber") if t else None


def committed_congress(roster_doc, index_doc=None):
    """The Congress the committed roster describes, or None when it cannot be told.

    `metadata.congress` is stamped by every run from now on; the committed file predates
    it, so fall back to the sponsorship index the same run wrote (always a Congress).
    """
    for doc in (roster_doc, index_doc):
        c = ((doc or {}).get("metadata") or {}).get("congress")
        if isinstance(c, int) and c > 0:
            return c
    return None


def opened_congress(old_roster, old_index, new_roster, new_index=None):
    """True when `new_roster` is a stamped turnover that opens a newer Congress than `old_*`.

    The roster workflow asks this of its staged files against HEAD, to dispatch the votes
    run once a turnover has landed. All three conditions are needed: a known baseline, a
    higher Congress, and the rollover stamp (an unstamped change of Congress is refused by
    the validator anyway, so it never gets this far).
    """
    was = committed_congress(old_roster, old_index)
    now = committed_congress(new_roster, new_index)
    stamped = bool(((new_roster or {}).get("metadata") or {}).get("rollover"))
    return bool(was and now and now > was and stamped)


def classify_run(committed, current):
    """in-congress | turnover | regression | unknown (no committed Congress to compare)."""
    if committed is None:
        return UNKNOWN
    if committed < current:
        return TURNOVER
    if committed > current:
        return REGRESSION
    return IN_CONGRESS


def new_term_share(members, congress):
    """Fraction of `members` whose latest term starts in the Congress's first year."""
    if not members:
        return 0.0
    first = congress_years(congress)[0]
    n = 0
    for m in members:
        t = _terms(m)
        sy = t[-1].get("startYear") if t else None
        if isinstance(sy, int) and sy >= first:
            n += 1
    return n / len(members)


def convened_on(congress):
    """3 January of the Congress's first year."""
    return date(congress_years(congress)[0], 1, 3)


def _today():
    return date.today()


def hold_expired(congress, today=None):
    """True once the new Congress has been sitting longer than HOLD_GRACE_DAYS."""
    today = today or _today()
    return (today - convened_on(congress)).days > HOLD_GRACE_DAYS


# ── sanity checks ───────────────────────────────────────────────────────────────

def parse_ga_vacant(text):
    """'GA-1,GA-13,GA-S' -> ({1, 13}, 1). House districts by number; GA-S = one Senate seat.

    Raises ValueError on anything else: a typo here must not quietly excuse a missing seat.
    """
    houses, senate = set(), 0
    for tok in [t.strip().upper() for t in (text or "").split(",") if t.strip()]:
        if tok == "GA-S":
            senate += 1
        elif tok.startswith("GA-") and tok[3:].isdigit() and 1 <= int(tok[3:]) <= GA_HOUSE_SEATS:
            houses.add(int(tok[3:]))
        else:
            raise ValueError(f"unrecognised vacant-seat token {tok!r}; use GA-<1..14> or GA-S")
    if senate > GA_SENATE_SEATS:
        raise ValueError("more than two Georgia Senate seats declared vacant")
    return houses, senate


def turnover_errors(members, congress, vacant=""):
    """What must hold of a roster that opens a Congress. Empty list = acceptable.

    Georgia: 2 senators and 14 House seats, each either filled or named in `vacant`
    ('GA-7,GA-S'); a seat that is filled but declared vacant is also an error, so a stale
    declaration cannot excuse a real gap later. Nationwide: a plausible count, no duplicate
    ids, and nearly everyone carrying a term in the new Congress.
    """
    errors = []
    n = len(members)
    if not TURNOVER_MIN_MEMBERS <= n <= TURNOVER_MAX_MEMBERS:
        errors.append(f"{n} members is outside the plausible {TURNOVER_MIN_MEMBERS}-"
                      f"{TURNOVER_MAX_MEMBERS} for a seated Congress")
    ids = [m.get("bioguideId") for m in members]
    if len(set(ids)) != len(ids):
        errors.append("duplicate bioguideId(s) in the roster")
    share = new_term_share(members, congress)
    if share < SITTING_NEW_TERM_SHARE_MIN:
        errors.append(f"only {share:.0%} of members carry a term in the "
                      f"{congress_ordinal(congress)} Congress (need "
                      f"{SITTING_NEW_TERM_SHARE_MIN:.0%}); the new Congress is not fully listed")

    try:
        vac_houses, vac_senate = parse_ga_vacant(vacant)
    except ValueError as exc:
        return errors + [str(exc)]
    ga = [m for m in members if m.get("state") == "Georgia"]
    senators = [m for m in ga if chamber_of(m) == "Senate"]
    house = [m for m in ga if chamber_of(m) == "House of Representatives"]
    if len(senators) + vac_senate != GA_SENATE_SEATS:
        errors.append(f"Georgia has {len(senators)} senator(s) with {vac_senate} declared "
                      f"vacant; expected {GA_SENATE_SEATS} seats accounted for")
    districts = [m.get("district") for m in house]
    if len(set(districts)) != len(districts):
        errors.append(f"two Georgia House members share a district: {sorted(districts, key=str)}")
    held = {d for d in districts if isinstance(d, int)}
    if len(held) != len(districts):
        errors.append("a Georgia House member has no numeric district")
    stray = sorted(d for d in held if not 1 <= d <= GA_HOUSE_SEATS)
    if stray:
        errors.append(f"Georgia House district(s) outside 1-{GA_HOUSE_SEATS}: {stray}")
    missing = set(range(1, GA_HOUSE_SEATS + 1)) - held
    if missing != vac_houses:
        errors.append(f"Georgia House seats with no member: {sorted(missing)}; declared "
                      f"vacant: {sorted(vac_houses)} — they must match")
    return errors


def rollover_stamp(prev, congress, departed, previous_count, count, share, vacant, freeze):
    """The marker the validator demands before it will accept a changed Congress."""
    return {
        "from": prev, "to": congress,
        "departed": departed, "previousCount": previous_count, "count": count,
        "newTermShare": round(share, 4),
        "gaVacant": sorted(t.strip().upper() for t in (vacant or "").split(",") if t.strip()),
        "freeze": freeze,
    }


# ── the freeze gate ─────────────────────────────────────────────────────────────

def _http_json(url):
    """Parsed JSON, or None for a 404. Anything else (network, 5xx, bad JSON) raises."""
    req = urllib.request.Request(url, headers={"User-Agent": "votega-turnover-guard"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def freeze_problems(prev_congress, roster_doc=None, fetch=None):
    """Why the outgoing Congress is not safely frozen yet; an empty list means it is.

    Requires sessions/<slug>/freeze.json with kind 'final' for that Congress. With
    `roster_doc` (the committed outgoing roster) it also requires the frozen delegation to
    be the same people, so a final freeze taken before a late roster change is caught. The
    comparison is on Georgia bioguide ids, not timestamps: the roster is regenerated daily
    and a timestamp would refuse a freeze that lost nothing.
    """
    fetch = fetch or _http_json
    slug = congress_ordinal(prev_congress)
    where = f"Votega/ga-federal-legislators sessions/{slug}/"
    try:
        manifest = fetch(FREEZE_RAW.format(slug=slug, name="freeze.json"))
    except Exception as exc:  # noqa: BLE001 - any failure to read means "cannot confirm"
        return [f"could not read {where}freeze.json ({exc}); cannot confirm the {slug} "
                f"Congress is frozen"]
    if not manifest:
        return [f"{where}freeze.json is not published: run freeze-federal-delegation with "
                f"final=true for {slug} first"]
    problems = []
    if manifest.get("kind") != "final":
        problems.append(f"the {slug} freeze is {manifest.get('kind')!r}, not 'final'")
    if manifest.get("congress") != prev_congress:
        problems.append(f"the freeze describes Congress {manifest.get('congress')}, "
                        f"not {prev_congress}")
    if roster_doc is not None and not problems:
        try:
            frozen = fetch(FREEZE_RAW.format(slug=slug, name="members.json")) or {}
        except Exception as exc:  # noqa: BLE001
            return [f"could not read {where}members.json ({exc})"]
        want = {m.get("bioguideId") for m in (roster_doc.get("members") or [])
                if m.get("state") == "Georgia"}
        got = {m.get("bioguideId") for m in (frozen.get("members") or [])}
        if want != got:
            problems.append(f"the final freeze's delegation differs from the committed "
                            f"roster (only in roster: {sorted(want - got)}; only in "
                            f"freeze: {sorted(got - want)}): it is stale, re-run the final "
                            f"freeze with overwrite=true")
    return problems


def freeze_confirmed():
    """The operator's explicit statement that the freeze exists and this check cannot see it."""
    return os.environ.get(ENV_FREEZE_CONFIRMED, "").strip().lower() in ("1", "true", "yes")


def accept_turnover():
    """Skip the 'is the new Congress listed yet' signal (never the sanity checks)."""
    return os.environ.get(ENV_ACCEPT_TURNOVER, "").strip().lower() in ("1", "true", "yes")


# ── decisions the generator acts on (pure, so the five scenarios are testable) ──

#: Inside a Congress, more than this many members flagged departed means the flag or the
#: API changed, not that Congress emptied out. Unchanged from the original guard.
MAX_DEPARTED_IN_CONGRESS = 25


def early_window(raw_members, congress, today=None, accept=False):
    """What a turnover run does when Congress.gov may not list the new Congress yet.

    Returns ('proceed' | 'hold' | 'fail', message).

    The date-derived Congress number flips at 00:00 UTC on 3 January, about 11 hours before
    the new Congress convenes, so for part of a day (and, if Congress.gov lags, for days)
    the run wants the 120th while the API still lists the 119th. Building then would publish
    the outgoing members under the new Congress's number, or a half-seated roster. So:

      * new Congress listed (enough members carry a term in it): proceed;
      * not listed, inside HOLD_GRACE_DAYS of the convening: HOLD. Write nothing, exit 0.
        Exit 0 and not 1 because this is the expected state for a few hours, and a red run
        every morning would train people to ignore red runs. Nothing is lost: the committed
        119th roster stays published and the next daily run tries again;
      * not listed after the grace period: FAIL, because by then it is a broken signal or a
        broken upstream and someone has to look. ACCEPT_TURNOVER overrides the signal.
    """
    share = new_term_share(raw_members, congress)
    if accept or share >= RAW_NEW_TERM_SHARE_MIN:
        return "proceed", f"{share:.0%} of listed members carry a {congress_ordinal(congress)} term"
    slug = congress_ordinal(congress)
    msg = (f"Congress.gov does not list the {slug} Congress yet ({share:.0%} of "
           f"{len(raw_members)} listed members carry a term in it; need "
           f"{RAW_NEW_TERM_SHARE_MIN:.0%})")
    if hold_expired(congress, today):
        return "fail", (msg + f", and it convened more than {HOLD_GRACE_DAYS} days ago. "
                        f"Either Congress.gov is behind or this signal is wrong; look, then "
                        f"re-run with accept_turnover if the roster really is the {slug}.")
    return "hold", (msg + ". Keeping the committed roster and exiting 0; the next daily run "
                    "will retry.")


def departure_verdict(kind, departed):
    """(ok, message) for the count of members flagged no longer serving."""
    if kind == TURNOVER:
        return True, (f"{departed} members left with the outgoing Congress; allowed at a "
                      f"turnover (sanity checks apply instead)")
    if departed > MAX_DEPARTED_IN_CONGRESS:
        return False, (f"{departed} members flagged as departed within one Congress — "
                       f"implausible (more than {MAX_DEPARTED_IN_CONGRESS}). Not committing.")
    return True, f"{departed} departed"


def validate_stamp(roster_doc, index_doc, old_roster_doc, old_index_doc=None):
    """Tier-1 turnover rules for the validator. Empty list = acceptable.

    A changed Congress needs the stamp (and the stamp must agree with the file); an unchanged
    Congress must not lose more than MAX_DEPARTED_IN_CONGRESS members at once.
    """
    errors = []
    meta = (roster_doc or {}).get("metadata") or {}
    stamp = meta.get("rollover")
    now = committed_congress(roster_doc, index_doc)
    was = committed_congress(old_roster_doc, old_index_doc) if old_roster_doc else None

    if stamp is not None:
        if stamp.get("to") != meta.get("congress"):
            errors.append(f"rollover stamp says it opens Congress {stamp.get('to')} but "
                          f"metadata.congress is {meta.get('congress')}")
        if index_doc is not None and ((index_doc.get("metadata") or {}).get("congress")
                                      != stamp.get("to")):
            errors.append("the sponsorship index is not for the Congress the rollover stamp opens")
        members = (roster_doc or {}).get("members") or []
        try:
            errors += [f"rollover: {e}" for e in
                       turnover_errors(members, stamp.get("to") or 0,
                                       ",".join(stamp.get("gaVacant") or []))]
        except (TypeError, ValueError, KeyError) as exc:
            errors.append(f"rollover stamp is malformed: {exc}")
        if not (stamp.get("freeze") or {}).get("kind") and not (stamp.get("freeze") or {}).get("confirmed"):
            errors.append("rollover stamp records neither a final freeze nor an explicit "
                          "freeze_confirmed")
        return errors

    if was is not None and now is not None and now != was:
        errors.append(f"Congress changed from {was} to {now} with no metadata.rollover "
                      f"stamp; a changeover is only accepted through the turnover path")
    if old_roster_doc and now == was:
        old_ids = {m.get("bioguideId") for m in (old_roster_doc.get("members") or [])}
        new_ids = {m.get("bioguideId") for m in ((roster_doc or {}).get("members") or [])}
        gone = len(old_ids - new_ids)
        if gone > MAX_DEPARTED_IN_CONGRESS:
            errors.append(f"{gone} members disappeared within one Congress with no rollover "
                          f"stamp (limit {MAX_DEPARTED_IN_CONGRESS})")
    return errors
