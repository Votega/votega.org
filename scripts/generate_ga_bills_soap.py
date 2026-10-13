#!/usr/bin/env python3
"""Generate ga-bills.json from the legis.ga.gov SOAP web service (official source).

Replaces generate_ga_bills_data.py (Open States, archived). Same output schema, so
nothing downstream changes. The win: bills and votes now come from ONE source, so the
party-tally enrichment join (enrich_bills_with_party_votes.py) is exact — each bill's
passageVotes are the SAME SOAP roll calls that generate_ga_votes_soap.py emits. Plus
no API key, no 250/day quota, and richer provenance (sponsor legisGaGovId, act number,
full status history, bill-text versions).

Source:
  * GetLegislationForSession(SessionId) -> every bill's {Id, Number, Description} (one call).
  * GetLegislationDetail(LegislationId) -> full bill: Caption (title), Summary (abstract),
    Authors (sponsors, with legisGaGovId), Status + StatusHistory (status + governor action),
    ActVetoNumber, Versions (bill text), and Votes[] (the bill's roll calls, filtered to
    passage by the shared lib.ga_passage rule — identical to the votes producer).

Subjects: SOAP has no topical subject tags, so they come from the frozen Open States
overlay assets/data/ga-bills-subjects-base.json (snapshot), then manual corrections in
ga-bills-subjects.json (overrides win), then local-bill inference (lib.ga_bill_subjects).
Refresh the base snapshot periodically from a historical OS pull as new bills accrue.

Incremental model: only the ACTIVE session is fetched live; every closed session in
the biennium is carried forward verbatim from the existing output file. Closed sessions
cannot change, and re-fetching them dominated the run — the 2025-2026 regular session is
5,480 of 5,656 bills, so a full sweep spent 97% of its GetLegislationDetail calls
re-downloading immutable records. This is the model lib/ga_sessions.py documents (see
ACTIVE_SESSION / preserved_session_ids) and that the archived Open States producer
implemented; it was dropped in the SOAP cutover and is restored here.

Carrying bills forward also PRESERVES downstream enrichment on closed sessions:
enrich_bills_with_party_votes.py injects partyTally into each passageVote after this
producer runs, and a re-fetch would blank it until the next enrichment pass.

Preservation is a hard requirement, not a fallback. The active session alone is well
over the 100-bill write floor, so a silently-failed preserve would publish a file
missing thousands of bills and still pass validation. If the prior file cannot be read,
or is missing bills for a session it claims to carry, the run ABORTS and tells you to
re-run with --full-refresh.

Use --full-refresh (or FULL_REFRESH=1) to re-fetch every session: when a closed session
is amended retroactively, when the schema here changes in a way that must reach
historical records, or to rebuild after the preserve check above has aborted.

A biennium rollover needs NO full refresh. SESSION_NAMES then holds only the new
biennium, so nothing is marked for preservation and the run is already a single-session
fetch; the prior biennium lives on in the publishers' sessions/<slug>/ archives.

Usage:
  python generate_ga_bills_soap.py                 # active session + preserved -> assets/data/ga-bills.json
  python generate_ga_bills_soap.py OUT.json        # explicit output path
  python generate_ga_bills_soap.py --full-refresh  # re-fetch ALL sessions (slow)
  python generate_ga_bills_soap.py --session 2025_26       # re-fetch one, preserve the rest
  python generate_ga_bills_soap.py --sample 40 --inspect   # a few bills, diagnostics, no write
"""

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from lib.atomic_io import write_json_atomic, atomic_write
from lib.ga_passage import native_is_passage
from lib.ga_vote_rules import is_state_constitutional_amendment, vote_passed
from lib.ga_bill_subjects import infer_local_subject
from lib.ga_sessions import (ACTIVE_SESSION, BIENNIUM, all_session_ids,
                             legis_session_id, preserved_session_ids, session_name,
                             tag_session)

LEG_URL  = "http://webservices.legis.ga.gov/GGAServices/Legislation/Service.svc"
SVC_NS   = "http://www.legis.ga.gov/2009/01/01/services/"
DATA_NS  = "http://www.legis.ga.gov/2009/01/01/data/"
ns = {"s": SVC_NS, "d": DATA_NS}
ACTION = {
    "GetLegislationForSession": SVC_NS + "LegislationSearch/GetLegislationForSession",
    "GetLegislationDetail":     SVC_NS + "LegislationSearch/GetLegislationDetail",
    "GetTitles":                SVC_NS + "LegislationSearch/GetTitles",
}

# A bill's topical subject is the O.C.G.A. Code Title it amends; the title NAME is the
# exact Open States subject vocabulary (served by GetTitles). A summary states the title
# two ways, both captured here, and may cite several (a school-funding bill amends Title 20
# AND Title 48) — that is how multi-subject tagging arises. See subjects_from_summary().
#   1. by title:   "to amend Title 7 of the O.C.G.A." / "...of the Official Code of Georgia"
#   2. by section: "to amend Code Section 20-2-165 of the..." — the leading number is the title
_OF_THE_CODE = r"of the (?:Official Code of Georgia|O\.?\s*C\.?\s*G\.?\s*A)"
_TITLE_OF_CODE_RE = re.compile(r"\bTitle\s+(\d{1,2})\s+" + _OF_THE_CODE, re.IGNORECASE)
# Plural form: "Titles 34 and 48 of the O.C.G.A." / "Titles 16, 31, and 43 of the...".
_TITLES_PLURAL_RE = re.compile(r"\bTitles\s+([\d,\s]+?(?:and\s+)?\d+)\s+" + _OF_THE_CODE, re.IGNORECASE)
# Section citation: "Code Section 20-2-165 of the..." — the leading number is the title.
_CODE_SECTION_RE = re.compile(r"\bCode Sections?\s+(\d{1,2})-", re.IGNORECASE)
# Budget/appropriations bills cite no code title but are tagged GENERAL ASSEMBLY (Title 28).
_APPROPRIATIONS_RE = re.compile(r"\bmak\w+ and provid\w+ appropriations", re.IGNORECASE)
_GENERAL_ASSEMBLY_TITLE = 28

DATA_DIR          = "assets/data"
OUTPUT_FILE       = os.path.join(DATA_DIR, "ga-bills.json")
SUBJECTS_BASE     = os.path.join(DATA_DIR, "ga-bills-subjects-base.json")
OVERRIDES_FILE    = os.path.join(DATA_DIR, "ga-bills-subjects.json")
MEMBERS_FILE      = os.path.join(DATA_DIR, "ga-members.json")
REVIEW_CSV_FILE   = os.path.join(DATA_DIR, "ga-bills-untagged-review.csv")
ABSTRACT_MAX      = 500
RESOLUTION_TYPES  = {"HR", "SR"}

# legis numeric session id -> our session tag (reverse of lib.ga_sessions.LEGIS_SESSIONS).
_TAG_BY_LEGIS_ID = {legis_session_id(t): t for t in all_session_ids()
                    if legis_session_id(t) is not None}


def _envelope(op, inner):
    return ('<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" '
            f'xmlns:s="{SVC_NS}"><soap:Body><s:{op}>{inner}</s:{op}>'
            '</soap:Body></soap:Envelope>')


def _is_fault(raw):
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return None
    fs = root.find(".//faultstring")
    return fs.text if fs is not None else None


def soap_call(op, inner="", retries=3, timeout=90):
    """POST a SOAP request; return the parsed root Element, or None on failure.
    Retries on 429 / transport 5xx / network errors; a deterministic SOAP fault
    (HTTP 500 with a <faultstring>) is not retried and returns None."""
    body = _envelope(op, inner).encode("utf-8")
    headers = {"Content-Type": "text/xml; charset=utf-8",
               "SOAPAction": '"%s"' % ACTION[op]}
    backoff = 4
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(LEG_URL, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return ET.fromstring(resp.read())
        except urllib.error.HTTPError as e:
            raw = e.read()
            fault = _is_fault(raw)
            if fault is not None:
                print("  %s: SOAP fault — %s" % (op, (fault or "")[:120]), file=sys.stderr)
                return None
            if 400 <= e.code < 500 and e.code != 429:
                print("  %s: HTTP %d — not retrying" % (op, e.code), file=sys.stderr)
                return None
            if attempt < retries:
                time.sleep(backoff); backoff *= 2; continue
            print("  %s: HTTP %d after retries" % (op, e.code), file=sys.stderr)
            return None
        except (urllib.error.URLError, TimeoutError, ET.ParseError) as e:
            if attempt < retries:
                time.sleep(backoff); backoff *= 2; continue
            print("  %s: %s after retries" % (op, type(e).__name__), file=sys.stderr)
            return None


def _text(el, tag, cast=None):
    if el is None:
        return None
    child = el.find("d:%s" % tag, ns)
    if child is None or child.text is None:
        return None
    if cast:
        try:
            return cast(child.text)
        except (ValueError, TypeError):
            return None
    return child.text.strip()


def derive_result(yea, nay, chamber=None, constitutional_amendment=False):
    """Pass/Fail by simple majority (Open States' result rule), or two-thirds of the
    chamber's elected members for a Georgia constitutional amendment — see
    lib/ga_vote_rules.py and generate_ga_votes_soap.derive_result."""
    passed = vote_passed(yea, nay, chamber, constitutional_amendment)
    if passed is None:
        return None
    return "pass" if passed else "fail"


def get_titles():
    """GetTitles -> {title number (int): NAME}. The authoritative 53-entry O.C.G.A.
    Code Title taxonomy; its Names are exactly the Open States subject strings, so this
    is the OS-free source of the subject vocabulary. Returns {} on failure (subjects then
    fall back to the frozen overlay + local inference only)."""
    root = soap_call("GetTitles")
    if root is None:
        return {}
    out = {}
    # GetTitles returns <Subject>{Code, Id, Name, Parent}</Subject> items — Id is the
    # O.C.G.A. title number, Name the subject string (matches the Open States vocabulary).
    for t in root.findall(".//d:Subject", ns):
        tid = _text(t, "Id", int)
        name = _text(t, "Name")
        if tid is not None and name:
            out[tid] = name
    return out


def subjects_from_summary(summary, titles_map):
    """Topical subjects for a bill, parsed from the O.C.G.A. Title(s) its summary amends.
    Returns the mapped Title names in first-seen order (deduped). Empty when the summary
    cites no title (resolutions, purely-local bills) or titles_map is unavailable."""
    if not summary or not titles_map:
        return []
    nums = []
    for m in _TITLE_OF_CODE_RE.finditer(summary):
        nums.append(int(m.group(1)))
    for m in _TITLES_PLURAL_RE.finditer(summary):           # "Titles 34 and 48 of the..."
        nums.extend(int(x) for x in re.findall(r"\d+", m.group(1)))
    for m in _CODE_SECTION_RE.finditer(summary):
        nums.append(int(m.group(1)))
    if not nums and _APPROPRIATIONS_RE.search(summary):     # budget bills -> GENERAL ASSEMBLY
        nums.append(_GENERAL_ASSEMBLY_TITLE)
    out = []
    # titles_map holds only valid title numbers (1-53), so mapping silently drops any
    # stray number the patterns pick up.
    for n in nums:
        name = titles_map.get(n)
        if name and name not in out:
            out.append(name)
    return out


def load_roster(path=MEMBERS_FILE):
    """legisGaGovId(int) -> full name, for clean sponsor names."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    return {m["legisGaGovId"]: m.get("name")
            for m in data.get("members", []) if m.get("legisGaGovId") and m.get("name")}


def load_subjects(base_path=SUBJECTS_BASE, overrides_path=OVERRIDES_FILE):
    """(base_snapshot, manual_overrides) — both {identifier: [subjects]}."""
    base = {}
    if os.path.exists(base_path):
        with open(base_path, encoding="utf-8") as f:
            base = (json.load(f) or {}).get("subjects", {})
    overrides = {}
    if os.path.exists(overrides_path):
        with open(overrides_path, encoding="utf-8") as f:
            overrides = {k: v for k, v in json.load(f).items()
                         if not k.startswith("_") and v}
    return base, overrides


def _chamber(doc_type, branch=None):
    """lower (House) / upper (Senate). From the roll-call Branch when given, else the
    bill's DocumentType prefix (H*/S*)."""
    if branch:
        return "lower" if branch.strip().lower().startswith("h") else "upper"
    return "lower" if (doc_type or "").strip().upper().startswith("H") else "upper"


def _sponsors(detail, roster):
    """[{name, primary, legisGaGovId}] from Authors/Sponsorship, in sequence order."""
    out = []
    authors = detail.find("d:Authors", ns)
    if authors is None:
        return out
    rows = []
    for sp in authors.findall("d:Sponsorship", ns):
        mid = _text(sp, "MemberId", int)
        seq = _text(sp, "Sequence", int)
        desc = _text(sp, "MemberDescription") or ""
        rows.append((seq if seq is not None else 9999, mid, desc))
    rows.sort(key=lambda r: r[0])
    for seq, mid, desc in rows:
        name = roster.get(mid) or _clean_member_desc(desc)
        out.append({"name": name, "primary": seq == 1, "legisGaGovId": mid})
    return out


def _clean_member_desc(desc):
    """'Cannon, Chas 172nd' -> 'Chas Cannon'. Falls back to the raw string."""
    m = re.match(r"\s*([^,]+),\s*(.*?)\s*\d+\w*\s*$", desc or "")
    if m:
        return "%s %s" % (m.group(2).strip(), m.group(1).strip())
    return (desc or "").strip()


def _passage_votes(detail, constitutional_amendment=False):
    """The bill's passage roll calls (native_is_passage), mapped to the ga-bills schema."""
    out = []
    votes = detail.find("d:Votes", ns)
    if votes is None:
        return out
    for vl in votes.findall("d:VoteListing", ns):
        caption = _text(vl, "Caption") or ""
        if not native_is_passage(caption):
            continue
        yea = _text(vl, "Yeas", int)
        nay = _text(vl, "Nays", int)
        nv  = _text(vl, "NotVoting", int) or 0
        exc = _text(vl, "Excused", int) or 0
        chamber = _chamber(None, _text(vl, "Branch"))
        out.append({
            "chamber":    chamber,
            "date":       (_text(vl, "Date") or "")[:10] or "",
            "result":     derive_result(yea, nay, chamber, constitutional_amendment) or "",
            "motionText": caption,
            "yea":        yea if yea is not None else 0,
            "nay":        nay if nay is not None else 0,
            "other":      nv + exc,
        })
    out.sort(key=lambda v: (v["date"], v["chamber"], v["motionText"]))
    return out


def _governor_action(detail):
    """Derive {status, sentDate, decisionDate, actNumber} from StatusHistory, or None.
    StatusHistory codes seen: H/SSG = Sent to Governor; H/SDSG + synthetic 'Signed Gov'
    (Description 'Act N') = signed; a veto carries 'Veto' in the description."""
    hist = detail.find("d:StatusHistory", ns)
    if hist is None:
        return None
    sent_date = sign_date = veto_date = None
    for sl in hist.findall("d:StatusListing", ns):
        code = (_text(sl, "Code") or "")
        desc = (_text(sl, "Description") or "")
        date = (_text(sl, "Date") or "")[:10] or None
        low = desc.lower()
        if "sent to governor" in low and sent_date is None:
            sent_date = date
        if "veto" in low and veto_date is None:
            veto_date = date
        if ("signed by governor" in low or code.strip().lower() == "signed gov") and sign_date is None:
            sign_date = date
    act_number = _text(detail, "ActVetoNumber", int)
    if veto_date:
        return {"status": "Vetoed", "sentDate": sent_date, "decisionDate": veto_date, "actNumber": None}
    if sign_date:
        return {"status": "Signed", "sentDate": sent_date, "decisionDate": sign_date, "actNumber": act_number}
    if sent_date:
        return {"status": "Sent to Governor", "sentDate": sent_date, "decisionDate": None, "actNumber": None}
    return None


def map_bill(detail, our_session, roster, titles_map):
    """GetLegislationDetailResult element -> one ga-bills.json bill.

    `subjects` is seeded here with the FALLBACK classification (parsed from the full,
    untruncated summary's O.C.G.A. Title references, then local-bill inference). The
    authoritative overlay / manual overrides are layered on top in apply_subjects()."""
    lid       = _text(detail, "Id", int)
    number    = _text(detail, "Number")
    doc_type  = _text(detail, "DocumentType") or ""
    suffix    = _text(detail, "Suffix") or ""
    identifier = ("%s %s%s" % (doc_type, number, suffix)).strip()
    title     = _text(detail, "Caption") or ""
    summary   = _text(detail, "Summary") or ""
    status    = detail.find("d:Status", ns)
    latest    = detail.find("d:LatestVersion", ns)

    # Fallback subjects: code-title parse off the FULL summary (not the truncated
    # abstract — a multi-title summary can reference a title past ABSTRACT_MAX), else
    # local-bill inference. This is what classifies a new session's bills once the
    # frozen OS overlay no longer covers them.
    subjects = subjects_from_summary(summary, titles_map) or infer_local_subject(title)

    return {
        "id":          "gga-bill/%s" % lid,
        "legislationId": lid,
        "identifier":  identifier,
        "session":     our_session,
        "billType":    "resolution" if doc_type.upper() in RESOLUTION_TYPES else "bill",
        "chamber":     _chamber(doc_type),
        "title":       title,
        "abstract":    summary[:ABSTRACT_MAX],
        "status":      _text(status, "Description") or "",
        "statusDate":  (_text(status, "Date") or "")[:19] if status is not None else "",
        "subjects":    subjects,
        "sponsors":    _sponsors(detail, roster),
        "billUrl":     "https://www.legis.ga.gov/legislation/%s" % lid,
        "textUrl":     (_text(latest, "Url") or "") if latest is not None else "",
        "passageVotes": _passage_votes(
            detail, is_state_constitutional_amendment(summary) and doc_type.upper() in RESOLUTION_TYPES),
        "governorAction": _governor_action(detail),
    }


def get_index(legis_session):
    """GetLegislationForSession -> [{Id, Number, Description}] for the session."""
    root = soap_call("GetLegislationForSession", "<s:SessionId>%d</s:SessionId>" % legis_session)
    if root is None:
        return []
    out = []
    for li in root.findall(".//d:LegislationIndex", ns):
        lid = _text(li, "Id", int)
        if lid is not None:
            out.append(lid)
    return out


def get_detail(lid):
    root = soap_call("GetLegislationDetail", "<s:LegislationId>%d</s:LegislationId>" % lid)
    if root is None:
        return None
    return root.find(".//s:GetLegislationDetailResult", ns)


def apply_subjects(bill, base, overrides):
    """Layer the authoritative subject sources on top of the fallback map_bill() seeded.
    Precedence: manual override > frozen OS snapshot (current biennium) > the code-title /
    local-inference fallback already on the bill (what carries a new session forward)."""
    ident = bill["identifier"]
    if ident in overrides:
        bill["subjects"] = overrides[ident]
    elif ident in base:
        bill["subjects"] = base[ident]
    # else: keep the fallback subjects map_bill() already derived from the summary/title.


def load_preserved_bills(path, sessions):
    """Bills for `sessions` carried forward verbatim from an existing output file.

    Returns (bills, prior_counts) where prior_counts is the per-session billCount the
    file's own metadata claimed, so the caller can verify nothing was lost in transit.
    Raises OSError/ValueError on anything unreadable — the caller MUST treat that as
    fatal rather than publishing a partial file (see the module docstring).

    Records written before multi-session support carry no `session` tag; tag_session()
    assigns those to UNTAGGED_SESSION so an old file still migrates cleanly.
    """
    wanted = set(sessions)
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    bills = [b for b in (data.get("bills") or []) if tag_session(b.get("session")) in wanted]
    prior_counts = {row.get("id"): row.get("billCount")
                    for row in ((data.get("metadata") or {}).get("sessions") or [])
                    if row.get("id") in wanted}
    return bills, prior_counts


def main():
    ap = argparse.ArgumentParser(description="Generate ga-bills.json from the legis.ga.gov SOAP service.")
    ap.add_argument("output_file", nargs="?", default=OUTPUT_FILE)
    ap.add_argument("--session", default=None, metavar="TAG",
                    help="re-fetch one session tag and preserve the rest "
                         "(default: the ACTIVE session only)")
    ap.add_argument("--full-refresh", action="store_true",
                    default=os.environ.get("FULL_REFRESH") == "1",
                    help="re-fetch EVERY configured session instead of preserving the "
                         "closed ones (slow; also settable as FULL_REFRESH=1)")
    ap.add_argument("--sample", type=int, default=None, metavar="N",
                    help="cap bills fetched per session (cheap run)")
    ap.add_argument("--inspect", action="store_true", help="diagnostics only, write nothing")
    ap.add_argument("--delay", type=float, default=0.1,
                    help="seconds between detail calls (default 0.1; this is an "
                         "unauthenticated state endpoint and a --full-refresh is "
                         "thousands of calls, so do not set 0 for a full sweep)")
    args = ap.parse_args()
    sample = args.sample if args.sample is not None else (8 if args.inspect else None)

    # Which sessions are fetched live, and which are carried forward from the existing
    # file. Closed sessions never change (lib/ga_sessions.py), so the default run fetches
    # ACTIVE_SESSION alone; --full-refresh re-fetches everything.
    if args.session:
        if args.session not in all_session_ids():
            print("Error: unknown session '%s'. Configured: %s."
                  % (args.session, ", ".join(all_session_ids())), file=sys.stderr)
            sys.exit(1)
        sessions = [args.session]
    elif args.full_refresh:
        sessions = list(all_session_ids())
    else:
        sessions = [ACTIVE_SESSION]
    sessions = [s for s in sessions if legis_session_id(s) is not None]
    if not sessions:
        print("Error: no session to fetch has a legis id (lib/ga_sessions.py).",
              file=sys.stderr)
        sys.exit(1)
    if args.session or args.full_refresh:
        preserve = [s for s in all_session_ids() if s not in sessions]
    else:
        preserve = preserved_session_ids()   # the canonical closed-session set

    # Carry the closed sessions forward. Fatal if that fails: the active session alone
    # clears the 100-bill write floor below, so a silent miss would publish a file short
    # by thousands of bills and still validate.
    #
    # A sampled run never preserves: mixing a capped active fetch with a complete frozen
    # layer would write a file that LOOKS whole but is short most of the active session.
    # Sampling stays what it was — an obviously-partial diagnostic the write floor catches.
    preserved, prior_counts = [], {}
    if sample and preserve and not args.inspect:
        print("Warning: --sample writes a PARTIAL file (%d/session, closed sessions not "
              "preserved). Use --inspect to avoid writing at all." % sample,
              file=sys.stderr)
    if preserve and not args.inspect and not sample:
        try:
            preserved, prior_counts = load_preserved_bills(args.output_file, preserve)
        except (OSError, json.JSONDecodeError, AttributeError) as exc:
            print("Error: cannot preserve closed sessions (%s) from %s: %s\n"
                  "       Re-run with --full-refresh to rebuild every session from SOAP."
                  % (", ".join(preserve), args.output_file, exc), file=sys.stderr)
            sys.exit(1)
        missing = [s for s in preserve
                   if not any(tag_session(b.get("session")) == s for b in preserved)]
        if missing:
            print("Error: %s carries no bills for %s — refusing to publish a file that "
                  "would silently drop them.\n"
                  "       Re-run with --full-refresh to rebuild every session from SOAP."
                  % (args.output_file, ", ".join(missing)), file=sys.stderr)
            sys.exit(1)
        print("Preserving %d bills from %d closed session(s): %s"
              % (len(preserved), len(preserve), ", ".join(preserve)))

    roster = load_roster()
    base, overrides = load_subjects()
    titles_map = get_titles()   # O.C.G.A. Title -> subject name (GetTitles; OS-free vocabulary)
    print("Loaded %d roster names, %d base subjects, %d manual overrides, %d code titles"
          % (len(roster), len(base), len(overrides), len(titles_map)))

    bills = []
    for our_session in sessions:
        legis_session = legis_session_id(our_session)
        index = get_index(legis_session)
        if sample:
            index = index[:sample]
        print("Session %s (legis %d): %d bills to fetch%s"
              % (our_session, legis_session, len(index), " [sample]" if sample else ""))
        t0 = time.time()
        for i, lid in enumerate(index, 1):
            detail = get_detail(lid)
            if detail is None:
                continue
            bills.append(map_bill(detail, our_session, roster, titles_map))
            if i % 250 == 0:
                print("  %d/%d (%.0fs)" % (i, len(index), time.time() - t0))
            if args.delay:
                time.sleep(args.delay)

    fetched_count = len(bills)

    # Preserved bills join the list BEFORE the subject overlay, so a manual correction in
    # ga-bills-subjects.json reaches a closed-session bill without a --full-refresh.
    if preserved:
        bills.extend(preserved)
        shortfall = {sid: prior for sid, prior in prior_counts.items()
                     if prior and sum(1 for b in preserved
                                      if tag_session(b.get("session")) == sid) < prior}
        if shortfall:
            print("Error: preserved fewer bills than %s claims for %s — refusing to write."
                  % (args.output_file,
                     ", ".join("%s (expected %d)" % (k, v) for k, v in shortfall.items())),
                  file=sys.stderr)
            sys.exit(1)

    for bill in bills:
        apply_subjects(bill, base, overrides)

    bills.sort(key=lambda b: (b.get("session") or "", b.get("chamber") or "", b.get("identifier") or ""))

    # Stats
    from collections import Counter
    bills_only = [b for b in bills if b["billType"] == "bill"]
    with_subjects = sum(1 for b in bills if b["subjects"])
    with_votes    = sum(1 for b in bills if b["passageVotes"])
    signed = sum(1 for b in bills if (b["governorAction"] or {}).get("status") == "Signed")
    vetoed = sum(1 for b in bills if (b["governorAction"] or {}).get("status") == "Vetoed")
    by_session = Counter(b["session"] for b in bills)

    if args.inspect:
        print("\n=== INSPECTION (nothing written) ===")
        print("bills: %d | with subjects: %d | with passageVotes: %d | signed: %d | vetoed: %d"
              % (len(bills), with_subjects, with_votes, signed, vetoed))
        if bills:
            print("sample bill:\n%s" % json.dumps(bills[0], indent=2)[:1400])
        return

    if len(bills) < 100:
        print("Error: only %d bills collected — refusing to write (SOAP sweep likely failed)."
              % len(bills), file=sys.stderr)
        sys.exit(1)

    output = {
        "metadata": {
            "generatedAt":       datetime.now(timezone.utc).isoformat(),
            "biennium":          BIENNIUM,
            "sessions":          [{"id": sid, "name": session_name(sid),
                                   "billCount": by_session.get(sid, 0)}
                                  for sid in all_session_ids()],
            "activeSession":     ACTIVE_SESSION,
            "activeSessionName": session_name(ACTIVE_SESSION),
            "session":           ACTIVE_SESSION,
            "sessionName":       session_name(ACTIVE_SESSION),
            "source":            "legis.ga.gov SOAP (webservices.legis.ga.gov/GGAServices)",
            "subjectsOverlay":   SUBJECTS_BASE,
            "totalBills":        len(bills),
            "updateMode":        "full" if not preserve else "incremental",
            "fetchedSessions":   sessions,
            "preservedSessions": preserve,
        },
        "bills": bills,
    }
    write_json_atomic(args.output_file, output, separators=(",", ":"))

    untagged = [b for b in bills_only if not b["subjects"]]
    if untagged:
        with atomic_write(REVIEW_CSV_FILE, newline="") as f:
            w = csv.writer(f)
            w.writerow(["identifier", "chamber", "title", "status"])
            for b in untagged:
                w.writerow([b["identifier"], "House" if b["chamber"] == "lower" else "Senate",
                            b["title"], b["status"]])

    size_mb = os.path.getsize(args.output_file) / 1024 / 1024
    print("\nDone. %d bills (%d bill, %d resolution) · %.1f MB -> %s"
          % (len(bills), len(bills_only), len(bills) - len(bills_only), size_mb, args.output_file))
    print("  %d fetched from SOAP (%s) · %d preserved (%s)"
          % (fetched_count, ", ".join(sessions),
             len(bills) - fetched_count, ", ".join(preserve) or "none"))
    print("  with subjects: %d (%.0f%%) · with passageVotes: %d · signed: %d · vetoed: %d · untagged bills: %d"
          % (with_subjects, 100 * with_subjects / len(bills), with_votes, signed, vetoed, len(untagged)))


if __name__ == "__main__":
    main()
