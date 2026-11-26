#!/usr/bin/env python3
"""Who issued a Georgia executive order (lib/ga_governors.py) and how the EO validator
treats it. What must hold:

  * an order's issuer comes from its date and the governor seat; a provisional successor
    is never used;
  * an order dated on an inauguration day is never guessed: the validator refuses to
    commit until assets/data/ga-eo-issuers.json names its issuer, with a `_note`;
  * an order after the last confirmed Governor's term has no issuer and is reported,
    not gated, and promoting the seat fills it in;
  * order text that names a different Governor than the date is reported;
  * an inauguration year's metadata.governor names both Governors.

Usage: python scripts/test_ga_governors.py   (no network; exit 0 ok, 1 on failure)
"""
import copy
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import ga_governors as G  # noqa: E402
import validate_ga_executive_orders as V  # noqa: E402
import publish_ga_executive_orders as P  # noqa: E402
import fetch_ga_executive_orders as F  # noqa: E402

failures = []


def check(label, got, want):
    print(f"  ok   {label}" if got == want else f"  FAIL {label}: got {got!r}, want {want!r}")
    if got != want:
        failures.append(label)


def raises(fn):
    try:
        fn()
    except (ValueError, SystemExit):
        return True
    return False


KEMP = "exec:ga-kemp-brian"
NEW = "exec:ga-next-governor"


def seats(provisional=True):
    return {"seats": [{"id": "ga-governor", "holders": [
        {"execId": NEW, "name": "Pat Next", "start": "2027-01-11", "end": None, "provisional": provisional},
        {"execId": KEMP, "start": None, "end": "2027-01-11"}]}]}


PEOPLE = {"officials": [{"id": KEMP, "name": "Brian Kemp"}, {"id": NEW, "name": "Pat Next"}]}
BEFORE = G.timeline(seats(True), PEOPLE)      # successor projected, not sworn in
AFTER = G.timeline(seats(False), PEOPLE)      # seat promoted


def order(date, n=1, title="Appointing someone to something"):
    y, m, d = date.split("-")
    return {"date": date, "number": f"{m}.{d}.{y[2:]}.{n:02d}", "title": title,
            "category": "Appointment", "url": "https://example.org/x"}


def who(date, tl, overrides=None, number="x"):
    w, reason = G.issuer(date, number, tl, overrides or {})
    return (w or {}).get("name"), reason


print("timeline and dates:")
check("Kemp keeps the name the orders always used", who("2026-11-25", BEFORE), ("Brian P. Kemp", None))
check("Deal before 2019", who("2018-06-01", BEFORE), ("Nathan Deal", None))
check("the day before the inauguration is the outgoing Governor", who("2027-01-10", BEFORE), ("Brian P. Kemp", None))
check("inauguration day is never guessed, even with the successor only projected",
      who("2027-01-11", BEFORE), (None, "handover"))
check("inauguration day after promotion is still never guessed", who("2027-01-11", AFTER), (None, "handover"))
check("a provisional successor is never used", who("2027-01-12", BEFORE), (None, "no-confirmed-governor"))
check("once promoted, the new Governor", who("2027-01-12", AFTER), ("Pat Next", None))
check("2019's inauguration day is a handover too", who("2019-01-14", AFTER), (None, "handover"))

print("hand-verified overrides:")
ok = {"01.11.27.01": {"execId": NEW, "_note": "signature on the PDF"}}
check("an override settles inauguration day", who("2027-01-11", AFTER, ok, "01.11.27.01"), ("Pat Next", None))
check("an override records how it was settled",
      G.issuer("2027-01-11", "01.11.27.01", AFTER, ok)[0]["basis"], "verified")
check("an override naming a projected Governor is refused",
      raises(lambda: G.issuer("2027-01-11", "01.11.27.01", BEFORE, ok)), True)
with tempfile.TemporaryDirectory() as t:
    p = os.path.join(t, "o.json")
    with open(p, "w") as fh:
        json.dump({"orders": {"01.11.27.01": {"execId": NEW}}}, fh)
    check("an override without a _note is refused", raises(lambda: G.load_overrides(p)), True)
    check("the committed override file loads", isinstance(G.load_overrides(), dict), True)

print("assigning a year file:")
doc = {"metadata": {"year": 2027}, "orders": [order("2027-01-10"), order("2027-01-11"), order("2027-01-12")]}
check("assign reports a change", G.assign(doc, AFTER, {}), True)
check("issuers", [(o["issuedBy"] or {}).get("name") for o in doc["orders"]],
      ["Brian P. Kemp", None, "Pat Next"])
check("an inauguration year names both Governors, in order", doc["metadata"]["governor"],
      "Brian P. Kemp / Pat Next")
check("assigning again changes nothing", G.assign(doc, AFTER, {}), False)
verified = copy.deepcopy(doc)
G.assign(verified, AFTER, ok)
check("a verified inauguration-day order gets its issuer", verified["orders"][1]["issuedBy"]["name"], "Pat Next")
check("an empty year names the Governor on 1 January",
      (G.assign(d := {"metadata": {"year": 2026}, "orders": []}, AFTER, {}), d["metadata"]["governor"])[1],
      "Brian P. Kemp")

print("validator:")
held = V.held_for_person(doc, AFTER, {})
check("an unverified inauguration-day order is held for a person", [o["date"] for o in held], ["2027-01-11"])
check("a verified one is not", V.held_for_person({"orders": [order("2027-01-11")]}, AFTER,
      {"01.11.27.01": ok["01.11.27.01"]}), [])
check("an ordinary order is not", V.held_for_person({"orders": [order("2026-05-01")]}, AFTER, {}), [])
bad = copy.deepcopy(doc)
bad["metadata"]["count"] = 3
bad["orders"][0]["issuedBy"] = {"name": "Brian P. Kemp"}
check("a malformed issuedBy fails tier 1", any("issuedBy" in e for e in V.tier1(bad, 2027)), True)
with tempfile.TemporaryDirectory() as t:
    os.makedirs(os.path.join(t, "2027"))
    for o in doc["orders"]:
        o["number"] = o["number"]
    with open(os.path.join(t, "2027", "01.12.27.01.txt"), "w", encoding="utf-8") as fh:
        fh.write("NOW, THEREFORE, I, Brian P. Kemp, Governor of the State\nof Georgia, do order")
    sections = dict(V.issuer_sections(doc, 2027, t))
    check("an order with no issuer is reported, not gated",
          any("01.11.27.01" in line for line in sections.get("Orders with no confirmed Governor", [])), True)
    check("text naming a different Governor is reported",
          any("01.12.27.01" in line and "Brian P. Kemp" in line
              for line in sections.get("Order text names a different Governor than its date", [])), True)

print("fetch and publish:")
check("a re-scrape keeps the issuer", F._carry_enrichment({"url": "u"}, {"url": "u", "issuedBy": {"name": "X"}}),
      {"url": "u", "issuedBy": {"name": "X"}})
csv = P.orders_csv([dict(o, _year="2027") for o in doc["orders"]]).decode().splitlines()
check("the CSV ends with issuedBy", csv[0].split(",")[-1], "issuedBy")
check("an unconfirmed issuer is blank in the CSV", csv[2].endswith(","), True)
check("the schema describes issuedBy",
      "issuedBy" in P.schema()["properties"]["orders"]["items"]["properties"], True)

print("the committed files:")
import glob  # noqa: E402
for path in sorted(glob.glob(os.path.join(os.path.dirname(__file__), "..", "assets", "data",
                                          "ga-executive-orders-20*.json"))):
    d = json.load(open(path, encoding="utf-8"))
    check(f"{os.path.basename(path)}: every order has an issuer and assign is stable",
          (all(o.get("issuedBy") for o in d["orders"]), G.assign(copy.deepcopy(d))), (True, False))

if failures:
    print(f"\n{len(failures)} failure(s)")
    sys.exit(1)
print("\nall ok")
