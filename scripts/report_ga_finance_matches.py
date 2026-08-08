#!/usr/bin/env python3
"""
Report GA state candidates whose campaign finance filing can't be matched automatically.

Run this after `generate_ga_campaign_finance.py` (or any time races.json changes) to
get a review queue. Nothing here calls an API — it re-runs the same join the site does
and reports what it couldn't resolve on its own.

The matcher deliberately refuses to guess: it scopes candidates to their seat, requires
the surname to match, and requires the first name to corroborate. Anything left
ambiguous is reported here for a human decision rather than resolved by picking one,
because attributing one candidate's fundraising to another is the failure mode this
whole join is built to avoid.

Resolve cases by adding entries to assets/data/ga-campaign-finance-overrides.json —
the script prints paste-ready stubs. Mirrors findFiler() in candidate.html.

Usage:
  python scripts/report_ga_finance_matches.py [--all]   # --all also lists likely non-filers
"""

import json
import os
import re
import sys

FINANCE_FILE   = "assets/data/ga-campaign-finance.json"
RACES_FILE     = "assets/data/races.json"
OVERRIDES_FILE = "assets/data/ga-campaign-finance-overrides.json"

CHAMBER_MAP = {
    'Georgia House of Representatives': 'House of Representatives',
    'Georgia State Senate':             'Senate',
}

# Statewide races have no district to scope by, so they join on office instead.
# races.json and PeachFile disagree on three labels, hence the explicit map.
OFFICE_MAP = {
    'Governor':                             'Governor',
    'Lieutenant Governor':                  'Lieutenant Governor',
    'Secretary of State':                   'Secretary of State',
    'Attorney General':                     'Attorney General',
    'Commissioner of Agriculture':          'Commissioner of Agriculture',
    'Insurance & Fire Safety Commissioner': 'Commissioner of Insurance',
    'Labor Commissioner':                   'Commissioner of Labor',
    'State School Superintendent':          'State School Superintendent',
    'Public Service Commissioner':          'Public Service Commissioner',
}

SUFFIXES = r'\b(jr|sr|ii|iii|iv|dr|mr|mrs|ms|esq)\.?\b'


def toks(s):
    s = (s or '').lower()
    s = re.sub(SUFFIXES, '', s)
    # Apostrophes are intra-word, not separators: replacing them with a space turned
    # O'Steen into ["o","steen"], which then failed to match a ballot spelling it
    # "Osteen". Drop them so both sides normalise to the same single token.
    s = s.replace("'", "").replace("’", "")
    s = re.sub(r'[^a-z\s]', ' ', s)
    return [t for t in s.split() if t]


def nicknames(s):
    """Quoted nicknames, e.g. Michael "Mike" Thurmond -> ['mike']."""
    return [m.lower() for m in re.findall(r'["“\']([A-Za-z]+)["”\']', s or '')]


def first_name_ok(cand_firsts, filer_firsts):
    """Compatible given names: exact, prefix (>=3 chars), or initial."""
    for a in cand_firsts:
        for b in filer_firsts:
            if a == b:
                return True
            if len(a) >= 3 and len(b) >= 3 and (a.startswith(b) or b.startswith(a)):
                return True
            if len(a) == 1 and b.startswith(a):
                return True
            if len(b) == 1 and a.startswith(b):
                return True
    return False


def candidate_pool(chamber, district, by_seat, by_office, filers):
    """Filer ids to consider for a candidate: their seat, or their statewide office.

    Public Service Commissioner is the one statewide office with districts, so it is
    narrowed by district when the filers carry one — otherwise every PSC candidate
    would collide with every other.
    """
    ch = CHAMBER_MAP.get(chamber)
    if ch and district is not None:
        return by_seat.get(f"{ch}-{district}", [])
    office = OFFICE_MAP.get(chamber)
    if not office:
        return []
    ids = by_office.get(office, [])
    if district is not None:
        scoped = [i for i in ids if str(filers[i].get('district') or '') == str(district)]
        if scoped:
            return scoped
    return ids


def find_filers(name, chamber, district, filers, by_seat, by_office=None):
    """Filers in the candidate's seat that plausibly are this candidate. Mirrors the JS.

    Seat + surname is the match; the given name is only a tiebreaker.

    Requiring the given name to agree up front looked safer but wasn't: across 233
    seats only 6 have two filers sharing a surname, and only one of those is genuinely
    two different people (Clark, House 100). Meanwhile the ballot routinely carries a
    name the filing doesn't — Bill/William, Beth/Elizabeth, Chuck/Charles, or a middle
    name in common use — so a given-name gate rejected ~52 correct matches to prevent
    a single wrong one that the ambiguity check already catches.

    Returning more than one hit means "ambiguous"; the caller shows no figures and the
    case goes to the review report rather than being guessed at.
    """
    pool = candidate_pool(chamber, district, by_seat, by_office or {}, filers)
    if not pool:
        return []
    cand = toks(name)
    nicks = nicknames(name)

    surname_hits = []
    for fid in pool:
        f = filers.get(fid) or {}
        fl = toks(f.get('lastName'))
        if not fl or len(fl) > len(cand):
            continue
        if cand[-len(fl):] != fl:          # surname, handles multi-word ("Rivera Holmes")
            continue
        surname_hits.append(fid)
    surname_hits = list(dict.fromkeys(surname_hits))

    if len(surname_hits) <= 1:
        return surname_hits

    # Two filers share this surname in this seat — try the given name to separate them.
    narrowed = []
    for fid in surname_hits:
        f = filers[fid]
        fl = toks(f.get('lastName'))
        ff = toks(f.get('firstName'))
        cand_firsts = cand[:-len(fl)] + nicks
        if cand_firsts and ff and first_name_ok(cand_firsts, ff):
            narrowed.append(fid)
    # Only accept the tiebreak if it resolves to exactly one; otherwise stay ambiguous.
    return narrowed if len(narrowed) == 1 else surname_hits


def main():
    show_all = '--all' in sys.argv

    cf = json.load(open(FINANCE_FILE, encoding='utf-8'))
    filers, by_seat, by_office = cf['filers'], cf['bySeat'], cf.get('byOffice', {})
    races = json.load(open(RACES_FILE, encoding='utf-8'))['races']

    overrides = {}
    if os.path.exists(OVERRIDES_FILE):
        overrides = {k: v for k, v in json.load(open(OVERRIDES_FILE, encoding='utf-8')).items()
                     if not k.startswith('_')}

    # Surname index across the whole state, used only to tell "probably hasn't filed"
    # from "filed, but our join missed it" — never to match.
    by_surname = {}
    for fid, f in filers.items():
        key = ''.join(toks(f.get('lastName')))
        if key:
            by_surname.setdefault(key, []).append(fid)

    seen = set()
    ambiguous, unmatched_same_seat, unmatched_similar, unmatched_none, resolved = [], [], [], [], 0

    for r in races:
        if r.get('level') not in ('state', 'state-executive'):
            continue
        for phase in (r.get('phases') or {}).values():
            for ballot in (phase.get('ballots') or {}).values():
                for c in ballot:
                    cid = c.get('id') or c.get('memberId')
                    name = c.get('name')
                    if not cid or not name or cid in seen:
                        continue
                    seen.add(cid)

                    if cid in overrides:
                        resolved += 1
                        continue

                    hits = find_filers(name, r.get('chamber'), r.get('district'), filers, by_seat, by_office)
                    if len(hits) == 1:
                        continue
                    if len(hits) > 1:
                        ambiguous.append((cid, name, r['id'], hits))
                        continue

                    # Split "surname matches someone in this candidate's OWN seat" from
                    # "surname matches someone elsewhere in the state". The first is
                    # usually the same person under a legal name the ballot doesn't use
                    # (Bill/William, Beth/Elizabeth, or a middle name in common use).
                    # The second is usually an unrelated person who happens to share a
                    # surname. Reviewing them as one undifferentiated list buries the
                    # handful that matter under dozens that don't.
                    surname = ''.join(toks(name)[-1:])
                    elsewhere = list(by_surname.get(surname, []))
                    seat_ids = set(candidate_pool(r.get('chamber'), r.get('district'),
                                                  by_seat, by_office, filers))
                    same_seat = [i for i in elsewhere if i in seat_ids]
                    if same_seat:
                        unmatched_same_seat.append((cid, name, r['id'], same_seat))
                    elif elsewhere:
                        unmatched_similar.append((cid, name, r['id'], elsewhere))
                    else:
                        unmatched_none.append((cid, name, r['id'], []))

    total = len(seen)
    print(f"GA state candidates on race ballots: {total}")
    unresolved = len(ambiguous) + len(unmatched_same_seat) + len(unmatched_similar) + len(unmatched_none)
    print(f"  matched automatically : {total - unresolved - resolved}")
    print(f"  resolved by override  : {resolved}")
    print(f"  AMBIGUOUS (review)                    : {len(ambiguous)}")
    print(f"  surname matches in THIS seat (review)  : {len(unmatched_same_seat)}")
    print(f"  surname only matches another seat (low): {len(unmatched_similar)}")
    print(f"  no similar filer (likely hasn't filed) : {len(unmatched_none)}")

    if ambiguous:
        print("\n" + "=" * 72)
        print("AMBIGUOUS — more than one filing matches. No figures are shown until resolved.")
        print("=" * 72)
        for cid, name, rid, hits in ambiguous:
            print(f"\n  {name}  ({rid})")
            for fid in hits:
                f = filers[fid]
                print(f"    filerEntityId {fid:<8} {f['filerName']:<28} "
                      f"raised={f.get('totalRaised')} spent={f.get('totalSpent')} "
                      f"cycle={f.get('electionCycle')}")

    if unmatched_similar:
        print("\n" + "=" * 72)
        print("UNMATCHED, but a filer with that surname exists elsewhere in the state.")
        print("Usually a different person; occasionally a candidate filed under another seat.")
        print("=" * 72)
        for cid, name, rid, elsewhere in unmatched_similar:
            others = ", ".join(
                f"{filers[i]['filerName']} ({filers[i]['office']}"
                + (f" d{filers[i]['district']}" if filers[i].get('district') else '') + ")"
                for i in elsewhere[:3])
            print(f"  {name:<30} ({rid:<20}) -> {others}")

    if show_all and unmatched_none:
        print("\n" + "=" * 72)
        print("UNMATCHED, no filer with that surname anywhere — almost certainly hasn't filed.")
        print("=" * 72)
        for cid, name, rid, _ in unmatched_none:
            print(f"  {name:<30} ({rid})")
    elif unmatched_none:
        print(f"\n({len(unmatched_none)} candidates with no similarly-named filer are hidden; "
              f"re-run with --all to list them.)")

    if ambiguous or unmatched_same_seat:
        print("\n" + "=" * 72)
        print(f"Paste-ready stubs for {OVERRIDES_FILE}")
        print("=" * 72)
        stub = {}
        for cid, name, rid, hits in ambiguous:
            stub[cid] = {"filerEntityId": hits[0], "_name": name, "_race": rid,
                         "_note": "REVIEW: pick the correct filerEntityId from the options above"}
        for cid, name, rid, hits in unmatched_same_seat:
            stub[cid] = {"filerEntityId": hits[0], "_name": name, "_race": rid,
                         "_note": "REVIEW: same seat, different given name — confirm it is the same person"}
        print(json.dumps(stub, indent=2))


if __name__ == '__main__':
    main()
