#!/usr/bin/env python3
"""Assert the GA roster producer treats a biennium rollover as an event, not a daily run.

The failure this pins: at the 2027-28 changeover `regular_session()` advances, the new
listing holds only the ~236 incoming members, and the preserve-verbatim rule republishes
EVERY committed member the listing lacks as sitting. The file then claims ~290 House
seats, validate_ga_members.py tier 1 exits 1, nothing is committed, and the daily job
errors every morning until a human intervenes. Safe, but a deadlock — so the producer
now detects the changeover, refuses to write without `--new-biennium`, and in that mode
drops the outgoing class.

Everything is a synthetic outgoing and incoming roster behind a fake SOAP client: no
network, no pip packages.

Usage:
  python scripts/test_ga_members_rollover.py

Exits 0 on success, 1 on any failure.
"""
import copy
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import generate_ga_members_soap as G  # noqa: E402
import validate_ga_members as V  # noqa: E402
from lib import ga_roster as R  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


OLD_TAG, OLD_SID, OLD_DESC = "2025_26", 1033, "2025-2026 Regular Session"
NEW_TAG, NEW_SID, NEW_DESC = "2027_28", 1035, "2027-2028 Regular Session"
CHAMBERS = (("Senate", "Senate", 56, 1000), ("House of Representatives", "House", 180, 2000))
LTGOV = 805


def committed_roster():
    """A full-strength 2025-26 roster: 56 + 180, the Lt. Governor, two Resigned injects."""
    members = []
    for chamber, _, n, base in CHAMBERS:
        for d in range(1, n + 1):
            members.append({
                "id": f"ocd-person/{base + d:08d}", "name": f"{chamber.split()[0]} Member {d}",
                "firstName": "M", "lastName": str(d), "party": "Republican", "chamber": chamber,
                "district": d, "title": "Senator" if chamber == "Senate" else "Representative",
                "birthDate": "1970-01-01", "birthYear": 1970, "termStart": "2019-01-14",
                "termStartYear": 2019, "legisGaGovId": base + d, "status": None})
    members.append({"id": "ocd-person/00000805", "name": "Lt Governor", "chamber": "executive",
                    "district": None, "legisGaGovId": LTGOV, "title": "Lt_Governor",
                    "status": None})
    return members


def listing_row(m):
    return {"id": m["legisGaGovId"], "first": "M", "last": m["name"], "party": "Republican",
            "chamber": "Senate" if m["chamber"] == "Senate" else "House",
            "district": m["district"], "dateVacated": None}


def incoming_listing(committed, retire_senate=(1, 2, 3), retire_house=range(1, 31)):
    """Returning members plus first-termers in the seats that changed hands."""
    rows, newcomers = [], []
    for m in committed:
        if m["chamber"] == "executive":
            continue
        gone = m["district"] in (retire_senate if m["chamber"] == "Senate" else retire_house)
        if not gone:
            rows.append(listing_row(m))
    for chamber, short, _, base in CHAMBERS:
        seats = retire_senate if chamber == "Senate" else retire_house
        for d in seats:
            gid = 9000 + base + d
            row = {"id": gid, "first": "New", "last": f"{short}{d}", "party": "Democrat",
                   "chamber": short, "district": d, "dateVacated": None}
            rows.append(row)
            newcomers.append(gid)
    return rows, newcomers


def detail_for(gid, first_term_ids, special_ids=()):
    if gid in special_ids:
        sessions = [{"sessionId": 1034, "description": "2028 Special Session",
                     "committees": [], "title": None}]
    else:
        sessions = [{"sessionId": NEW_SID, "description": NEW_DESC, "committees": [],
                     "title": None}]
    if gid not in first_term_ids and gid not in special_ids:
        sessions.append({"sessionId": OLD_SID, "description": OLD_DESC,
                         "committees": [], "title": None})
    return {"id": gid, "phone": "4045550100", "email": f"{gid}@x.gov", "address1": "CLOB",
            "city": "Atlanta", "state": "GA", "zip": "30334", "birthday": "July 12",
            "portraits": {}, "sessions": sessions}


class Env:
    """One temp dir with a committed roster, an overrides file and a patched producer."""

    def __init__(self, session=(NEW_TAG, NEW_SID), overrides=None, archived=True,
                 listing=None, first_term_ids=(), special_ids=()):
        self.d = tempfile.TemporaryDirectory()
        self.committed = committed_roster()
        self.members_path = os.path.join(self.d.name, "ga-members.json")
        self.overrides_path = os.path.join(self.d.name, "overrides.json")
        with open(self.members_path, "w", encoding="utf-8") as f:
            json.dump({"metadata": {"session": OLD_TAG, "legisSessionId": OLD_SID},
                       "members": self.committed}, f)
        with open(self.overrides_path, "w", encoding="utf-8") as f:
            json.dump(overrides if overrides is not None else {}, f)
        rows, self.newcomers = incoming_listing(self.committed)
        self.rows = listing if listing is not None else rows
        self.first_term_ids, self.special_ids = set(first_term_ids), set(special_ids)
        self.before = open(self.members_path, "rb").read()
        self.saved = {k: getattr(G, k) for k in (
            "MEMBERS_FILE", "OVERRIDES_FILE", "IDENTITY_SIDECAR", "DELAY", "regular_session",
            "get_members_by_session", "get_member", "get_committees_by_session",
            "load_pin_overrides", "outgoing_archived")}
        G.MEMBERS_FILE, G.OVERRIDES_FILE = self.members_path, self.overrides_path
        G.IDENTITY_SIDECAR = os.path.join(self.d.name, "none.json")
        G.DELAY = 0
        G.regular_session = lambda: session
        G.get_members_by_session = lambda sid: self.rows
        G.get_member = lambda gid: detail_for(gid, self.first_term_ids | set(self.newcomers),
                                              self.special_ids)
        G.get_committees_by_session = lambda sid: []
        G.load_pin_overrides = lambda: {}
        G.outgoing_archived = lambda slug: archived

    def run(self, *flags):
        # The producer prints a lot; the assertions below are what matter.
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return G.main(list(flags))

    def out(self):
        with open(self.members_path, encoding="utf-8") as f:
            return json.load(f)

    def untouched(self):
        return open(self.members_path, "rb").read() == self.before

    def close(self):
        for k, v in self.saved.items():
            setattr(G, k, v)
        self.d.cleanup()


def tagged_overrides():
    return {"_inject": [
        {"_session": OLD_TAG, "id": "ocd-person/00001001", "name": "Senate Member 1",
         "chamber": "Senate", "district": 1, "status": "Resigned", "statusDate": "2026-03-13",
         "legisGaGovId": 1001}]}


def ids(doc):
    return {m["id"] for m in doc["members"]}


def helper_cases():
    print("lib.ga_roster helpers")
    import datetime
    check("2027 convenes the second Monday of January", R.convening_date(2027),
          datetime.date(2027, 1, 11))
    check("2025 convened January 13", R.convening_date(2025), datetime.date(2025, 1, 13))
    check("a Monday January 1 still makes the 8th the FIRST Monday's successor",
          R.convening_date(2024), datetime.date(2024, 1, 8))
    check("tag -> archive slug", R.biennium_slug("2025_26"), "2025-2026")
    meta = {"session": OLD_TAG, "legisSessionId": OLD_SID}
    check("same session is no rollover", R.detect_rollover(meta, OLD_TAG, OLD_SID), None)
    check("no committed metadata is a bootstrap, not a rollover",
          R.detect_rollover({}, NEW_TAG, NEW_SID), None)
    check("a different tag is a rollover",
          R.detect_rollover(meta, NEW_TAG, NEW_SID)["to"]["session"], NEW_TAG)
    check("a different legis id alone is a rollover",
          R.detect_rollover({"legisSessionId": OLD_SID}, OLD_TAG, NEW_SID) is not None, True)
    check("scoping: untagged applies everywhere", R.entry_in_scope({}, NEW_TAG), True)
    check("scoping: another biennium's entry is inert",
          R.entry_in_scope({"_session": OLD_TAG}, NEW_TAG), False)
    check("scoping: session=None applies everything (old callers)",
          R.entry_in_scope({"_session": OLD_TAG}, None), True)
    ov = {"_inject": [{"id": "a", "_session": OLD_TAG}, {"id": "b"}]}
    check("injects_for_session keeps untagged + matching",
          [e["id"] for e in R.injects_for_session(ov, OLD_TAG)], ["a", "b"])
    check("injects_for_session drops the other biennium's",
          [e["id"] for e in R.injects_for_session(ov, NEW_TAG)], ["b"])

    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "o.json")
        members = [{"id": "ocd-person/x", "name": "Pat Doe", "legisGaGovId": 1}]
        with open(p, "w") as f:
            json.dump({"Pat Doe": {"status": "Resigned", "statusDate": "2026-01-01",
                                   "_session": OLD_TAG}}, f)
        ms = copy.deepcopy(members)
        R.apply_member_overrides(ms, p, session=NEW_TAG)
        check("a name patch for another biennium does not apply", ms[0].get("status"), None)
        ms = copy.deepcopy(members)
        R.apply_member_overrides(ms, p, session=OLD_TAG)
        check("...and does apply to its own", ms[0].get("status"), "Resigned")
        ms = copy.deepcopy(members)
        R.apply_member_overrides(ms, p)
        check("_session never leaks into the published record", "_session" in ms[0], False)


def plain_run_cases():
    print("an ordinary daily run (same session) is unchanged")
    env = Env(session=(OLD_TAG, OLD_SID), listing=[listing_row(m) for m in committed_roster()
                                                   if m["chamber"] != "executive"])
    try:
        check("exits 0", env.run(), 0)
        out = env.out()
        check("the committed Lt. Governor row is dropped, not preserved",
              LTGOV in {m.get("legisGaGovId") for m in out["members"]}, False)
        check("no executive row remains in the roster",
              [m for m in out["members"] if m.get("chamber") == "executive"], [])
        check("no rollover marker in metadata", "rollover" in out["metadata"], False)
        check("no rollover queues in review",
              sorted(k for k in out["review"] if k in (
                  "incomingCohort", "departingCohort", "newMemberNameReview")), [])
    finally:
        env.close()
    env = Env(session=(OLD_TAG, OLD_SID), listing=[listing_row(m) for m in committed_roster()
                                                   if m["chamber"] != "executive"],
              first_term_ids=(), overrides={})
    try:
        env.rows.append({"id": 9999, "first": "Late", "last": "Entrant", "party": "Democrat",
                         "chamber": "House", "district": 181, "dateVacated": None})
        env.newcomers.append(9999)
        check("exits 0 with a mid-biennium entrant", env.run(), 0)
        late = [m for m in env.out()["members"] if m.get("legisGaGovId") == 9999][0]
        check("a mid-biennium entrant gets NO derived termStart (opening day would be wrong)",
              late["termStart"], None)
    finally:
        env.close()


def refusal_cases():
    print("a rollover without --new-biennium is refused")
    env = Env()
    try:
        check("exits 1", env.run(), 1)
        check("and writes nothing", env.untouched(), True)
    finally:
        env.close()

    print("--new-biennium against an unchanged session is refused")
    env = Env(session=(OLD_TAG, OLD_SID))
    try:
        check("exits 1", env.run("--new-biennium"), 1)
        check("and writes nothing", env.untouched(), True)
    finally:
        env.close()

    print("the outgoing roster must be archived first")
    env = Env(archived=False, overrides=tagged_overrides())
    try:
        check("not archived -> exits 1", env.run("--new-biennium"), 1)
        check("and writes nothing", env.untouched(), True)
        check("--archive-confirmed lets it through", env.run("--new-biennium",
                                                             "--archive-confirmed"), 0)
    finally:
        env.close()

    print("an untagged departure is a decision a human has to make")
    env = Env(overrides={"_inject": [{k: v for k, v in tagged_overrides()["_inject"][0].items()
                                      if k != "_session"}]})
    try:
        check("exits 1", env.run("--new-biennium"), 1)
        check("and writes nothing", env.untouched(), True)
    finally:
        env.close()


def rollover_cases():
    print("--new-biennium builds the new class and drops the outgoing one")
    env = Env(overrides=tagged_overrides())
    try:
        check("exits 0", env.run("--new-biennium"), 0)
        out = env.out()
        members = out["members"]
        voting = [m for m in members if m["chamber"] in V.CHAMBER_MAX]
        check("236 voting members", len(voting), 236)
        check("the roster is the 236 voting members and nothing else",
              len(members), 236)
        check("the Lt. Governor is not republished (ga-executive.json owns him)",
              LTGOV in {m.get("legisGaGovId") for m in members}, False)
        gone = {m["id"] for m in env.committed if m["chamber"] != "executive"
                and m["district"] in ((1, 2, 3) if m["chamber"] == "Senate" else range(1, 31))}
        check("no departed member is republished as sitting", gone & ids(out), set())
        returning = {m["id"] for m in env.committed
                     if m["chamber"] != "executive" and m["id"] not in gone}
        check("every returning incumbent keeps their id (never-re-key)",
              returning <= ids(out), True)
        newcomers = [m for m in members if m.get("legisGaGovId") in env.newcomers]
        check("newcomers get the deterministic legis- key",
              all(m["id"] == f"legis-{m['legisGaGovId']}" for m in newcomers), True)
        check("the tagged 2025-26 Resigned inject is inert, not re-seated",
              "ocd-person/00001001" in ids(out), False)
        check("metadata.rollover stamped", out["metadata"]["rollover"]["incoming"], 33)
        check("departing count", out["metadata"]["rollover"]["departing"], 33)
        check("incoming cohort queue", len(out["review"]["incomingCohort"]), 33)
        check("departing cohort queue", len(out["review"]["departingCohort"]), 33)
        check("name review queue names the entity URL a new member will get",
              out["review"]["newMemberNameReview"][0].split(" -> ")[1].split(" ")[0].startswith(
                  "/ga-legislators/"), True)
        check("no executive is queued for a human to verify (ga-executive.json owns them)",
              out["review"]["rolloverPreservedNonMembers"], [])
        check("out-of-scope overrides are reported",
              out["review"]["overridesOutOfScope"], ["_inject: Senate Member 1"])
        check("the file passes tier 1 against the tagged overrides",
              V.tier1(out, tagged_overrides(), {"metadata": {"session": OLD_TAG}}), [])
        check("derived termStart for a first-term member is the convening date",
              {m["termStart"] for m in newcomers}, {"2027-01-11"})
        check("a returning member keeps their carried termStart",
              [m for m in members if m["id"] == "ocd-person/00001010"][0]["termStart"],
              "2019-01-14")
        check("birthDate stays null for a first-termer (month+day cannot yield an age)",
              {m["birthDate"] for m in newcomers}, {None})
        check("termStartYear still comes from the earliest session",
              {m["termStartYear"] for m in newcomers}, {2027})
    finally:
        env.close()

    print("a special-session entrant is not dated to the opening day")
    env = Env(overrides=tagged_overrides())
    try:
        special = env.newcomers[0]
        env.special_ids = {special}
        check("exits 0", env.run("--new-biennium"), 0)
        rec = [m for m in env.out()["members"] if m.get("legisGaGovId") == special][0]
        check("termStart stays null", rec["termStart"], None)
    finally:
        env.close()


def validator_cases():
    print("validate_ga_members: rollover tiering")
    seated = lambda ch, n: [{"id": f"{ch}{i}", "name": f"{ch}{i}", "chamber": ch,  # noqa: E731
                             "district": i, "status": None} for i in range(1, n + 1)]
    members = seated("Senate", 56) + seated("House of Representatives", 180)
    new = {"metadata": {"count": 236, "session": NEW_TAG}, "members": members}
    old = {"metadata": {"session": OLD_TAG}}
    errs = V.tier1(new, None, old)
    check("a different biennium with no rollover stamp is tier 1", len(errs), 1)
    check("...and names the cause", "metadata.rollover" in errs[0], True)
    new["metadata"]["rollover"] = {"from": {"session": OLD_TAG}, "to": {"session": NEW_TAG},
                                   "incoming": 1, "departing": 1}
    check("an acknowledged rollover passes", V.tier1(new, None, old), [])
    check("the same biennium needs no stamp",
          V.tier1({"metadata": {"count": 236, "session": OLD_TAG}, "members": members},
                  None, old), [])
    check("a rollover is REPORTED (tier 2), never gated",
          [h for h, _ in V.tier2(new, old) if h == "Biennium rollover"], ["Biennium rollover"])

    ov = {"_inject": [{"id": "x", "_session": OLD_TAG}, {"id": "y"}]}
    got = V.tier1({"metadata": {"count": 236, "session": NEW_TAG, "rollover": {}},
                   "members": members}, ov, None)
    check("an _inject for another biennium is not an orphan; an untagged one still is",
          ("['y']" in got[0]) and ("'x'" not in got[0]), True)


helper_cases()
plain_run_cases()
refusal_cases()
rollover_cases()
validator_cases()

if failures:
    print(f"\n{len(failures)} FAILED: {failures}")
    sys.exit(1)
print("\nAll cases passed.")
