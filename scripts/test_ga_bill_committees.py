#!/usr/bin/env python3
"""The committee holding a bill in each chamber (ga-bills.json `committees`).

legis.ga.gov's GetLegislationDetail carries `Committees`: one `CommitteeListing` per
chamber, overwritten when the bill moves, so it is the CURRENT committee. Pins: both
chambers are read, House first, with ids, codes and stripped names; an unknown Type or a
missing id is left out; a bill with none gets [].

Usage: python scripts/test_ga_bill_committees.py     (no network)
"""
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import generate_ga_bills_soap as G  # noqa: E402

failures = []


def check(name, got, want):
    if got != want:
        failures.append("%s: got %r, want %r" % (name, got, want))


def detail(committees_xml):
    return ET.fromstring(
        f'<GetLegislationDetailResult xmlns="{G.DATA_NS}">'
        '<Caption>A bill</Caption><DocumentType>HB</DocumentType><Id>69294</Id><Number>14</Number>'
        f'{committees_xml}</GetLegislationDetailResult>')


def listing(kind, cid, code, name):
    cid_xml = "" if cid is None else f"<Id>{cid}</Id>"
    return (f"<CommitteeListing><Code>{code}</Code>{cid_xml}<Name>{name}</Name>"
            f"<Type>{kind}</Type></CommitteeListing>")


both = detail("<Committees>" + listing("Senate", 83, "RULES", "Rules ")
              + listing("House", 117, "SRules", "Special Rules") + "</Committees>")
check("both chambers, House first", G._committees(both), [
    {"chamber": "lower", "id": 117, "code": "SRules", "name": "Special Rules"},
    {"chamber": "upper", "id": 83, "code": "RULES", "name": "Rules"}])
check("on the mapped bill", G.map_bill(both, "2025_26", {}, {})["committees"][0]["id"], 117)
check("none", G._committees(detail("")), [])
check("empty element", G._committees(detail("<Committees/>")), [])
check("unknown type and missing id left out", G._committees(detail(
    "<Committees>" + listing("Joint", 5, "J", "Joint") + listing("House", None, "Hth", "Health")
    + "</Committees>")), [])

# --- moves are recorded by comparing with the file the run replaces ----------
PAC = {"chamber": "lower", "id": 120, "code": "P&CH", "name": "Public and Community Health"}
HTH = {"chamber": "lower", "id": 196, "code": "Hth", "name": "Health"}
GVT = {"chamber": "upper", "id": 130, "code": "GvtO", "name": "Government Oversight"}
prior = [{"legislationId": 1, "committees": [PAC]},
         {"legislationId": 2, "committees": [HTH]},
         {"legislationId": 3, "committees": []}]
now = [{"legislationId": 1, "committees": [HTH, GVT]},     # moved in House, then crossed over
       {"legislationId": 2, "committees": [HTH]},           # unchanged
       {"legislationId": 3, "committees": [HTH]},           # first referral
       {"legislationId": 4, "committees": [HTH]}]           # new bill
check("moves counted", G.carry_committee_history(now, prior, "2027-02-01"), 1)
check("the move", now[0]["committeeHistory"], [
    {"chamber": "lower", "from": {"id": 120, "code": "P&CH", "name": "Public and Community Health"},
     "to": {"id": 196, "code": "Hth", "name": "Health"}, "seenOn": "2027-02-01"}])
check("unchanged, first referral, new bill: no history",
      [b["committeeHistory"] for b in now[1:]], [[], [], []])
# the next run carries the history forward and adds only new moves
prior2 = [dict(b) for b in now]
again = [{"legislationId": 1, "committees": [HTH, GVT]}]
check("second run adds nothing", G.carry_committee_history(again, prior2, "2027-02-08"), 0)
check("carried forward", len(again[0]["committeeHistory"]), 1)
check("no prior file", G.carry_committee_history([{"legislationId": 9, "committees": [HTH]}], [], "x"), 0)

if failures:
    print("FAIL (%d):" % len(failures))
    for f in failures:
        print("  " + f)
    sys.exit(1)
print("ok")
