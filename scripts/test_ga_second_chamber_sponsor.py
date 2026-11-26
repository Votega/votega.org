#!/usr/bin/env python3
"""The second-chamber sponsor (a senator sponsoring a House measure, or the reverse).

legis.ga.gov keeps this person in `Sponsor`, apart from `Authors`, so it was once left
out entirely. Pins: it is published as its own `secondChamberSponsor` field (never inside
`sponsors[]`, where readers would count it as a co-sponsor), and it reaches the member
slices, the legislator prose, the published CSV/schema and the MCP index.

Usage: python scripts/test_ga_second_chamber_sponsor.py     (no network, no repo writes)
"""
import contextlib
import csv
import io
import json
import os
import sys
import tempfile
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_sponsorship_slices as S  # noqa: E402
import generate_ga_bills_soap as G  # noqa: E402
import publish_ga_bills as P  # noqa: E402
from lib import mcp_bills as MB  # noqa: E402
from lib.ga_legislator_record import legislator_record  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def detail(sponsor_xml):
    return ET.fromstring(
        f'<GetLegislationDetailResult xmlns="{G.DATA_NS}">'
        '<Authors><Sponsorship><MemberDescription>Wade, Will 9th</MemberDescription>'
        '<MemberId>4988</MemberId><Sequence>1</Sequence><Type>HouseAuthor</Type></Sponsorship></Authors>'
        '<Caption>A bill</Caption><DocumentType>HB</DocumentType><Id>69463</Id><Number>105</Number>'
        f'{sponsor_xml}</GetLegislationDetailResult>')


def sponsor(kind, gid=4984, desc="Hatchett, Bo 50th"):
    return (f"<Sponsor><MemberDescription>{desc}</MemberDescription><MemberId>{gid}</MemberId>"
            f"<Sequence>7</Sequence><Type>{kind}</Type></Sponsor>")


def mapped(sponsor_xml, roster=None):
    return G.map_bill(detail(sponsor_xml), "2025_26", roster or {}, {})


print("generator")
b = mapped(sponsor("SenateSponsor"))
check("a Senate sponsor is read", b.get("secondChamberSponsor"),
      {"name": "Bo Hatchett", "legisGaGovId": 4984, "chamber": "upper"})
check("sponsors[] is unchanged", [s["legisGaGovId"] for s in b["sponsors"]], [4988])
check("a House sponsor is the lower chamber",
      mapped(sponsor("HouseSponsor"))["secondChamberSponsor"]["chamber"], "lower")
check("the roster name wins", mapped(sponsor("SenateSponsor"), {4984: "Roster Name"})["secondChamberSponsor"]["name"],
      "Roster Name")
for label, xml in (("no Sponsor element", ""), ("an empty Sponsor element", "<Sponsor/>")):
    got = mapped(xml)
    check(f"{label} -> null, key present", ("secondChamberSponsor" in got, got.get("secondChamberSponsor")),
          (True, None))
with contextlib.redirect_stderr(io.StringIO()) as err:
    got = mapped(sponsor("SomethingElse"))
check("an unknown role is not guessed at", got["secondChamberSponsor"], None)
check("...and is reported", "SomethingElse" in err.getvalue(), True)


def bill(ident, lid, authors, second=None):
    out = {"identifier": ident, "legislationId": lid, "session": "2025_26", "billType": "bill",
           "chamber": "lower" if ident.startswith("H") else "upper", "title": ident, "status": "x",
           "statusDate": "2025-01-01T00:00:00", "subjects": [], "passageVotes": [],
           "sponsors": [{"name": f"M{g}", "legisGaGovId": g, "primary": i == 0} for i, g in enumerate(authors)]}
    if second:
        out["secondChamberSponsor"] = {"name": f"M{second[0]}", "legisGaGovId": second[0], "chamber": second[1]}
    return out


BILLS = [bill("HB 1", 1, [101, 102], (201, "upper")),
         bill("SB 2", 2, [201], (101, "lower")),
         bill("HB 3", 3, [101])]  # no key at all: a bill not re-fetched yet
DOC = {"metadata": {"biennium": "2025-2026", "generatedAt": "2026-01-01T00:00:00+00:00",
                    "sessions": [{"id": "2025_26"}]}, "bills": BILLS}

print("member slices")
d = tempfile.mkdtemp(prefix="second-")
S.DATA_DIR = d
S.BILLS_FILE = os.path.join(d, "ga-bills.json")
S.MEMBERS_FILE = os.path.join(d, "none.json")
S.INDEX_OUT = os.path.join(d, "idx.json")
S.SLICES_DIR = os.path.join(d, "sl")
with open(S.BILLS_FILE, "w", encoding="utf-8") as fh:
    json.dump(DOC, fh)
with contextlib.redirect_stdout(io.StringIO()):
    S.main()
with open(S.INDEX_OUT, encoding="utf-8") as fh:
    counts = json.load(fh)["members"]
check("counts are [primary, co, Senate sponsor, House sponsor]",
      (counts.get("101"), counts.get("102"), counts.get("201")), ([2, 0, 0, 1], [0, 1, 0, 0], [1, 0, 1, 0]))


def buckets(gid):
    with open(os.path.join(S.SLICES_DIR, f"{gid}.json"), encoding="utf-8") as fh:
        return {k: [r[0] for r in v] for k, v in json.load(fh)["sessions"]["2025_26"].items()}


check("a Senate sponsorship has its own bucket", buckets(201), {"p": ["SB 2"], "ss": ["HB 1"]})
check("a House sponsorship has its own bucket", buckets(101), {"p": ["HB 1", "HB 3"], "hs": ["SB 2"]})

print("legislator prose")
M = {"name": "Jane Roe"}


def prose(c, past=None):
    return " ".join(legislator_record(M, None, c, past))


check("all roles", prose([28, 266, 5, 0]),
      "Jane Roe is the primary sponsor of 28 bills and resolutions, a cosponsor of 266 other measures "
      "and the Senate sponsor of 5 House measures in the current biennium.")
check("second-chamber only, singular", prose([0, 0, 0, 1]),
      "Jane Roe is the House sponsor of 1 Senate measure in the current biennium.")
check("primary and co wording unchanged", prose([31, 79, 0, 0]),
      "Jane Roe is the primary sponsor of 31 bills and resolutions and a cosponsor of 79 other measures "
      "in the current biennium.")
check("two counts (an older frozen index) still read", prose([0, 3]),
      "Jane Roe is a cosponsor of 3 bills and resolutions in the current biennium.")
check("past tense", prose([0, 0, 2, 0], "2025–2026"),
      "Jane Roe was the Senate sponsor of 2 House measures in the 2025–2026 General Assembly.")
check("all zero says nothing", prose([0, 0, 0, 0]), "")

print("published dataset")
rows = list(csv.reader(io.StringIO(P.bills_csv(BILLS).decode())))
check("new CSV column goes last", rows[0][-2:], ["billUrl", "secondChamberSponsor"])
check("CSV carries the name, blank when none", [r[-1] for r in rows[1:]], ["M201", "M101", ""])
check("sponsorCount does not count them", [r[rows[0].index("sponsorCount")] for r in rows[1:]], ["2", "1", "1"])
item = P.schema()["properties"]["bills"]["items"]
check("schema describes the field", item["properties"].get("secondChamberSponsor", {}).get("type"),
      ["object", "null"])
check("schema does not require it", "secondChamberSponsor" in item["required"], False)

print("MCP index")
docs = MB.build_bills([DOC], "2026-01-02T00:00:00+00:00")
hb = docs["bills/2025_26-HB.json"]
by_id = {r["identifier"]: r for r in hb["bills"]}
check("row carries [legisGaGovId, chamber]", by_id["HB 1"].get("secondChamberSponsor"), [201, "upper"])
check("sponsors keep their shape", by_id["HB 1"]["sponsors"], [[101, True], [102, False]])
check("their name is in the shard's names", hb["sponsorNames"].get("201"), "M201")
check("absent when the bill has none (not claimed as none)", "secondChamberSponsor" in by_id["HB 3"], False)

if failures:
    sys.exit(f"{len(failures)} check(s) failed")
print("All second-chamber sponsor checks passed.")
