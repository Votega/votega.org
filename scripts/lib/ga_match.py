#!/usr/bin/env python3
"""Match a Georgia candidate or legislator to their PeachFile campaign finance filing.

Extracted from report_ga_finance_matches.py so the review report and
build_id_crosswalk.py run *identical* logic. Two copies of a name matcher drift,
and when this one drifts it attributes one candidate's fundraising to another —
the exact failure the matcher is built to avoid.

The remaining fork is assets/scripts/campaign-finance.js, which re-runs this join
in the browser for candidates. See build_id_crosswalk.py for why that copy still
exists and what would retire it.

Match rule: scope to the seat (or statewide office), require the surname, use the
given name only as a tiebreaker. More than one hit means ambiguous — callers must
show nothing and send the case to review rather than picking one.

    from lib.ga_match import find_filers, CHAMBER_TO_PEACHFILE
"""

import re

#: races.json / ga-members.json chamber label -> the label PeachFile's bySeat uses.
#: ga-members.json already stores the short form, races.json the long one; both map
#: to the same PeachFile key, so callers can pass either.
CHAMBER_TO_PEACHFILE = {
    'Georgia House of Representatives': 'House of Representatives',
    'Georgia State Senate':             'Senate',
    'House of Representatives':         'House of Representatives',
    'Senate':                           'Senate',
}

# Backwards-compatible alias for the name report_ga_finance_matches.py used.
CHAMBER_MAP = CHAMBER_TO_PEACHFILE

#: Statewide races have no district to scope by, so they join on office instead.
#: races.json and PeachFile disagree on three labels, hence the explicit map.
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

#: ga-members.json stores statewide executives in this file too, under
#: chamber "executive" with a raw-enum title. Map those titles onto OFFICE_MAP
#: keys so an executive can be scoped by office like any statewide candidate.
EXECUTIVE_TITLE_TO_OFFICE = {
    'Governor':          'Governor',
    'Lt_Governor':       'Lieutenant Governor',
    'Secretary Of State': 'Secretary of State',
    'Attorney General':  'Attorney General',
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
    ch = CHAMBER_TO_PEACHFILE.get(chamber)
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


def member_scope(member):
    """(chamber, district) to match a ga-members.json row on.

    Legislators scope by chamber+district. The four statewide executives that share
    this file (chamber "executive") have no district, so they scope by office via
    their raw-enum title — without this they would silently resolve to no filer.
    """
    chamber = member.get('chamber')
    if chamber in ('Senate', 'House of Representatives'):
        return chamber, member.get('district')
    if chamber == 'executive':
        return EXECUTIVE_TITLE_TO_OFFICE.get(member.get('title')), None
    return None, None
