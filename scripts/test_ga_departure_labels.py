#!/usr/bin/env python3
"""assets/data/ga-departure-labels.json: the approved departure labels.

The labels are approved wording, recorded as data ahead of the January 2027
rollover; no page reads them yet. What must hold:

  * every key is a legisGaGovId on the roster, and the recorded name, chamber and
    district still match that member (a label attached to the wrong person is the
    failure this guards);
  * metadata.count is the number of labels;
  * every label has a known type, text and at least one source;
  * the wording rules hold: "lost" and "did not run", never "ousted" or "unseated",
    and "retire" only in Harbison's, which quotes his own announced word;
  * a label never names the winner of a contest the member lost.

Run: python scripts/test_ga_departure_labels.py        (no network, no repo writes)
"""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "assets", "data")
TYPES = {"resigned", "suspended", "withdrew", "announced-departure", "lost-primary",
         "ran-for-other-office", "did-not-run", "special-election", "lost-general"}
HARBISON = "17"

failures = []


def check(label, ok, detail=""):
    if ok:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label} {detail}")
        failures.append(label)


def load(name):
    with open(os.path.join(DATA, name), encoding="utf-8") as f:
        return json.load(f)


doc = load("ga-departure-labels.json")
labels = doc["labels"]
roster = {str(m["legisGaGovId"]): m for m in load("ga-members.json")["members"]
          if m.get("legisGaGovId") is not None}

check("count matches", doc["metadata"]["count"] == len(labels), f"{doc['metadata']['count']} vs {len(labels)}")
check("every key is on the roster", all(k in roster for k in labels),
      str([k for k in labels if k not in roster]))
bad = [k for k, v in labels.items() if k in roster and
       (v["name"] != roster[k]["name"] or v["chamber"] != roster[k]["chamber"] or v["district"] != roster[k]["district"])]
check("name, chamber and district match the roster", not bad, str(bad))
check("types are known", all(v["type"] in TYPES for v in labels.values()))
check("every label has text and a source", all(v["label"].strip() and v["sources"] for v in labels.values()))
check("no empty strings in sources", all(s.strip() for v in labels.values() for s in v["sources"]))
check("no 'ousted' or 'unseated'", not any(re.search(r"ousted|unseated", v["label"], re.I) for v in labels.values()))
check("'retire' only in Harbison's own-word label",
      all(HARBISON == k or not re.search(r"retire", v["label"], re.I) for k, v in labels.items()))
check("a did-not-run label says 'did not run'",
      all("Did not run" in v["label"] for v in labels.values() if v["type"] == "did-not-run"))

# No label names the winner of a contest the member lost.
winners = ["Keisha Lance Bottoms", "Napier", "Kim Thomas Smith", "Bradley B. Anderson", "Tremaine",
           "Teddy Reese", "Tonya", "Strickland", "Dolezal", "McLaurin", "Jasmine Clark", "Clay Fuller"]
named = [(k, w) for k, v in labels.items() for w in winners if w in v["label"]]
check("no label names a winner", not named, str(named))

print()
if failures:
    print(f"{len(failures)} failed")
    raise SystemExit(1)
print("all passed")
