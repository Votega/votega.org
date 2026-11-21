#!/usr/bin/env python3
"""assets/data/ga-departure-labels.json: the approved departure labels.

The labels are approved wording, recorded as data ahead of the January 2027
rollover; no page reads them yet. What must hold:

  * every key is a legisGaGovId on the roster, and the recorded name, chamber and
    district still match that member (a label attached to the wrong person is the
    failure this guards);
  * metadata.count is the number of labels;
  * every label has a known type, text and at least one source;
  * the wording rules hold: "lost" and "did not run", never "retire", "ousted" or
    "unseated" (Harbison's carve-out for his own word was dropped 2026-11-21);
  * a ran-for-other-office label carries `office` and `result`, and its text agrees
    with them ("Won ..." exactly when the result is won);
  * a label never names the winner of a contest the member lost.

Run: python scripts/test_ga_departure_labels.py        (no network, no repo writes)
"""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "assets", "data")
TYPES = {"resigned", "suspended", "withdrew", "announced-departure", "lost-primary",
         "ran-for-other-office", "did-not-run", "special-election", "lost-general", "deceased"}

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
check("no 'retire' in any label",
      not any(re.search(r"retire", v["label"], re.I) for v in labels.values()))
check("a did-not-run label says 'did not run'",
      all("Did not run" in v["label"] for v in labels.values() if v["type"] == "did-not-run"))

# A ran-for-other-office label names the office and its result, and the text agrees.
RESULTS = {"won", "lost-primary", "lost-primary-runoff", "lost-general", "lost-general-runoff"}
other = {k: v for k, v in labels.items() if v["type"] == "ran-for-other-office"}
check("ran-for-other-office carries an office and a known result",
      all(v.get("office") and v.get("result") in RESULTS for v in other.values()),
      str([k for k, v in other.items() if not (v.get("office") and v.get("result") in RESULTS)]))
check("a won result says 'Won', and only a won result does",
      all((v.get("result") == "won") == v["label"].startswith("Won") for v in other.values()))
check("the office appears in the label",
      all(v.get("office", "") in v["label"] for v in other.values()))
check("a lost-general label says 'Lost the general election'",
      all(v["label"].startswith("Lost the general election") for v in labels.values() if v["type"] == "lost-general"))

# No label names the winner of a contest the member lost.
winners = ["Keisha Lance Bottoms", "Napier", "Kim Thomas Smith", "Bradley B. Anderson", "Tremaine",
           "Teddy Reese", "Tonya", "Strickland", "Dolezal", "McLaurin", "Jasmine Clark", "Clay Fuller",
           # November 2026 general: winners over batch 2 members
           "Tanya Miller", "Penny Brown Reynolds", "Duncan", "Dillie", "Beth Fuller", "Danielle Bell", "Guest",
           "Starke-Jones", "Lassiter", "Soracco", "Kang", "Mishael White", "Burgess", "Mughal", "Cleveland",
           "Luchey", "Tippetts", "Castro", "Murvartian"]
named = [(k, w) for k, v in labels.items() for w in winners if w in v["label"]]
check("no label names a winner", not named, str(named))

print()
if failures:
    print(f"{len(failures)} failed")
    raise SystemExit(1)
print("all passed")
