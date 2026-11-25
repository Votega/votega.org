#!/usr/bin/env python3
"""freeze_congress_committees.py: the saved committee rosters of a Congress.

Usage: python scripts/test_freeze_congress_committees.py   (no network; exit 0 ok, 1 on failure)
"""
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import freeze_congress_committees as F  # noqa: E402
from lib import federal_pages  # noqa: E402

failures = []


def check(label, got, want):
    print(f"  ok   {label}" if got == want else f"  FAIL {label}: got {got!r}, want {want!r}")
    if got != want:
        failures.append(label)


NOW = datetime(2026, 11, 25, tzinfo=timezone.utc)
LATE = datetime(2027, 1, 3, tzinfo=timezone.utc)
CODES = [f"HS{i:02d}" for i in range(40)]


def docs(codes=CODES):
    membership = {c: [{"bioguide": "A1", "name": "Ann", "party": "majority", "rank": 1, "title": "Chair"},
                      {"bioguide": "B2", "name": "Bob", "party": "minority", "rank": 1}] for c in codes}
    membership["HS0001"] = membership["HS00"][:1]
    cs = [{"thomas_id": c, "name": c, "subcommittees": []} for c in codes]
    cs[0]["subcommittees"] = [{"thomas_id": "01", "name": "One"}, {"thomas_id": "02", "name": "Empty"}]
    return membership, cs


def roster(congress=119):
    return {"metadata": {"congress": congress, "generatedAt": "g"}, "members": [
        {"bioguideId": b, "name": b, "partyName": "Democratic", "state": "Ohio", "district": 1,
         "terms": {"item": [{"chamber": "House of Representatives"}]}} for b in ("A1", "B2")]}


def run(out, membership, cs, *, live=None, slug="119th", now=NOW, meta=None, raw=None, **kw):
    raw = raw if raw is not None else {
        "committee-membership-current.yaml": json.dumps(membership).encode(),
        "committees-current.yaml": json.dumps(cs).encode()}
    head = kw.pop("head", [{"sha": "abc"}])
    with tempfile.TemporaryDirectory() as data:
        with open(os.path.join(data, "current-members.json"), "w", encoding="utf-8") as f:
            json.dump(live or roster(), f)
        return F.freeze(slug, data, out, now=now, fetch=lambda u: raw.get(u.rsplit("/", 1)[1]),
                        fetch_meta=lambda u: meta if "path=" in u else head, parse=json.loads, **kw)


def contents(root):
    out = {}
    for d, _, fs in os.walk(root):
        for f in fs:
            with open(os.path.join(d, f), "rb") as fh:
                out[os.path.join(d, f)] = fh.read()
    return out


def refuses(label, edit=None, out=None, **kw):
    m, c = docs()
    if edit:
        edit(m, c)
    with tempfile.TemporaryDirectory() as t:
        target = out or t
        before = contents(target)
        try:
            run(target, m, c, **kw)
            got = "wrote"
        except F.FreezeError:
            got = "refused"
        check(label, (got, contents(target) == before), ("refused", True))


def shrink(m, c):
    few_m, few_c = docs(CODES[:32])
    m.clear()
    m.update(few_m)
    c[:] = few_c


with tempfile.TemporaryDirectory() as out:
    m, c = docs()
    man = run(out, m, c, meta=[{"sha": "abc", "commit": {"committer": {"date": "2026-11-04"}}}])
    dest = os.path.join(out, "119th", "committees")
    check("files", sorted(os.listdir(dest)), ["committee-membership.json", "committees.json",
                                              "freeze-committees.json", "members.json"])
    with open(os.path.join(dest, "committee-membership.json"), encoding="utf-8") as f:
        check("nothing dropped from membership", json.load(f), m)
    src = man["sources"]["committee-membership.json"]
    check("hash of the upstream file", src["sha256"], hashlib.sha256(json.dumps(m).encode()).hexdigest())
    check("read at the pinned commit", "/abc/committee-membership-current.yaml" in src["url"], True)
    with open(os.path.join(dest, "members.json"), encoding="utf-8") as f:
        check("member record", json.load(f)["A1"], {"name": "A1", "party": "Democratic", "state": "Ohio",
                                                    "district": 1, "chamber": "House of Representatives"})
    check("upstream date", man["membershipLastUpdated"]["committedAt"], "2026-11-04")
    check("an empty subcommittee is recorded, not refused",
          man["counts"]["subcommitteesWithNoMembersListed"], ["HS0002"])
    check("the page builder ignores a committees-only folder", federal_pages.load_frozen(out), {})
    refuses("a re-freeze that loses a fifth", shrink, out=out)
    check("provisional -> final", run(out, *docs(), kind="final")["kind"], "final")
    refuses("a final freeze is not replaced", out=out)
    check("a missing upstream date does not block",
          run(out, *docs(), overwrite=True)["membershipLastUpdated"], None)

refuses("on 3 January", now=LATE)
refuses("slug is another Congress", slug="118th")
refuses("live roster already flipped", live=roster(120))
refuses("a file that cannot be fetched", raw={})
refuses("a file that does not parse", raw={"committee-membership-current.yaml": b"<html>",
                                           "committees-current.yaml": b"[]"})
refuses("upstream commit unknown", head=None)
older = roster()
older["members"].append({"bioguideId": "C3", "name": "Cy", "committees": ["X"]})
refuses("files older than the live roster", live=older)
refuses("too few committees", lambda m, c: c.__delitem__(slice(5, None)))
refuses("full committee with no members", lambda m, c: m.pop("HS05"))
refuses("membership for an unknown committee", lambda m, c: m.update(XX99=[]))
refuses("many members not in the roster",
        lambda m, c: m["HS03"].extend({"bioguide": f"Z{i}", "name": "Zed"} for i in range(11)))
with tempfile.TemporaryDirectory() as out:
    m, c = docs()
    m["HS03"].append({"bioguide": "Z9", "name": "Zed"})
    check("a member who just left is recorded, not refused",
          run(out, m, c)["counts"]["notInLiveRoster"], ["Z9"])
    with open(os.path.join(out, "119th", "committees", "members.json"), encoding="utf-8") as f:
        check("and keeps the name upstream gives", json.load(f)["Z9"]["name"], "Zed")

if failures:
    print(f"{len(failures)} failure(s)")
    sys.exit(1)
print("all ok")
