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

if failures:
    print("FAIL (%d):" % len(failures))
    for f in failures:
        print("  " + f)
    sys.exit(1)
print("ok")
