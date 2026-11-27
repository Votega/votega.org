#!/usr/bin/env python3
"""Where a GA bill is (lib/ga_bill_stage.py).

Histories are trimmed copies of real 2025-26 records: HB 973 (signed, conference),
HB 1148 (passed the House, died in Senate Finance), HB 520 (died in House Health),
HB 1066 (reported, never voted on), a lost bill, a tabled one, a simple resolution, and
the session-over rule (45 quiet days; a regular session's first year carries over).

Usage: python scripts/test_ga_bill_stage.py     (no network)
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.ga_bill_stage import apply_stages, bill_stage, session_over  # noqa: E402

failures = []


def check(name, got, want):
    if got != want:
        failures.append("%s: got %r, want %r" % (name, got, want))


def h(*rows):
    return [[d + "T10:00:00", c] for d, c in rows]


HOUSE_APP = {"chamber": "lower", "id": 88, "code": "App", "name": "Appropriations"}
SEN_APP = {"chamber": "upper", "id": 103, "code": "APPROP", "name": "Appropriations"}
WM = {"chamber": "lower", "id": 101, "code": "W&M", "name": "Ways & Means"}
FIN = {"chamber": "upper", "id": 138, "code": "FIN", "name": "Finance"}
HTH = {"chamber": "lower", "id": 196, "code": "Hth", "name": "Health"}


def bill(history, committees=(), votes=(), ga=None, chamber="lower", bill_type="bill", lt="GEN"):
    return {"chamber": chamber, "billType": bill_type, "legislationType": lt,
            "statusHistory": history, "committees": list(committees),
            "passageVotes": list(votes), "governorAction": ga}


def vote(chamber, date, yea, nay, result="pass"):
    return {"chamber": chamber, "date": date, "time": "11:00", "yea": yea, "nay": nay, "result": result}


# --- HB 973: signed after a conference committee ------------------------------
hb973 = bill(h(("2026-01-16", "HSR"), ("2026-02-04", "HCFR"), ("2026-02-05", "HPA"),
               ("2026-02-05", "SRAR"), ("2026-02-18", "SCFR"), ("2026-02-20", "SPA"),
               ("2026-02-25", "HCA"), ("2026-02-25", "SCRA"), ("2026-02-25", "HSG")),
             [HOUSE_APP, SEN_APP],
             [vote("lower", "2026-02-05", 167, 5), vote("upper", "2026-02-20", 49, 1),
              vote("lower", "2026-02-25", 169, 2), vote("upper", "2026-02-25", 49, 0)],
             {"status": "Signed", "decisionDate": "2026-03-03", "actNumber": 372, "sentDate": "2026-02-25"})
s = bill_stage(hb973, True)
check("973 kind/label", (s["kind"], s["label"]), ("signed", "Signed · Act 372"))
check("973 all done", [x[0] for x in s["steps"]], ["done"] * 6)
check("973 House floor is the passage, not the CCR", s["steps"][1][1], "Passed 167–5")
check("973 Senate floor", s["steps"][3][1], "Passed 49–1")
check("973 committees", (s["steps"][0][1], s["steps"][2][1]), ("Appropriations", "Appropriations"))
check("973 final", s["steps"][4][:2], ["done", "Agreed"])
check("973 governor", s["steps"][5], ["done", "Signed", "Mar 3, 2026 · Act 372"])

# --- HB 1148: passed the House, never reported in the Senate -------------------
hb1148 = bill(h(("2026-02-04", "HSR"), ("2026-03-03", "HCFR"), ("2026-03-04", "HPA"),
                ("2026-03-06", "SRAR")), [WM, FIN], [vote("lower", "2026-03-04", 163, 3)])
dead = bill_stage(hb1148, True)
check("1148 dead label", (dead["kind"], dead["label"]),
      ("died-committee", "Passed House · Died in Senate Finance"))
check("1148 states", [x[0] for x in dead["steps"]], ["done", "done", "stopped", "ahead", "ahead", "ahead"])
check("1148 detail", dead["steps"][2][2], "Referred Mar 6, 2026 · never reported")
live = bill_stage(hb1148, False)
check("1148 in session", (live["kind"], live["label"], live["steps"][2][0]),
      ("committee", "Passed House · In Senate Finance", "current"))

# --- HB 520: died in its first committee ---------------------------------------
hb520 = bill(h(("2025-02-20", "HFR"), ("2025-02-21", "HSR"), ("2025-02-27", "HRECM")), [HTH])
s = bill_stage(hb520, True)
check("520", (s["kind"], s["label"], s["steps"][0][0]), ("died-committee", "Died in House Health", "stopped"))

# --- reported, never voted on --------------------------------------------------
s = bill_stage(bill(h(("2026-01-20", "HSR"), ("2026-02-12", "HCFR")), [HTH]), True)
check("no vote", (s["kind"], s["label"], s["steps"][1][:2]),
      ("died-floor", "Died awaiting a House vote", ["stopped", "No vote"]))
s = bill_stage(bill(h(("2026-01-20", "HSR"), ("2026-02-12", "HCFR")), [HTH]), False)
check("awaiting vote", (s["kind"], s["label"]), ("floor", "Awaiting House vote"))

# --- lost on the floor, and lost then passed -----------------------------------
lost = bill(h(("2026-01-20", "HSR"), ("2026-02-12", "HCFR"), ("2026-02-13", "HTRL")), [HTH],
            [vote("lower", "2026-02-13", 80, 85, "fail")])
s = bill_stage(lost, True)
check("lost", (s["kind"], s["label"], s["steps"][1][:2]),
      ("lost", "Lost on the House floor", ["stopped", "Lost 80–85"]))
revived = bill(lost["statusHistory"] + h(("2026-02-13", "HRECO"), ("2026-02-14", "HPA")), [HTH],
               lost["passageVotes"] + [vote("lower", "2026-02-14", 120, 40)])
s = bill_stage(revived, False)
check("lost then passed", (s["steps"][1][:2], s["kind"]), (["done", "Passed 120–40"], "committee"))

# --- tabled in the Senate ------------------------------------------------------
s = bill_stage(bill(h(("2026-01-20", "SRAR"), ("2026-02-12", "SCFR"), ("2026-02-20", "STAB")),
                    [FIN], chamber="upper"), True)
check("tabled", (s["kind"], s["label"]), ("died-floor", "Tabled in the Senate"))

# --- a simple resolution -------------------------------------------------------
s = bill_stage(bill(h(("2026-01-20", "HRA")), bill_type="resolution", lt="PRIV"), True)
check("adopted", (s["kind"], s["label"], s["path"]), ("adopted", "Adopted by the House", "short"))
s = bill_stage(bill(h(("2026-01-20", "SRAR")), chamber="upper", bill_type="resolution", lt="PRIV"), True)
check("not adopted", (s["kind"], s["label"]), ("died-committee", "Not adopted"))

# --- vetoed, and on the Governor's desk ----------------------------------------
both = h(("2026-01-16", "HSR"), ("2026-02-04", "HCFR"), ("2026-02-05", "HPA"), ("2026-02-05", "SRAR"),
         ("2026-02-18", "SCFR"), ("2026-02-20", "SPA"), ("2026-02-25", "HSG"))
s = bill_stage(bill(both, [HOUSE_APP, SEN_APP], ga={"status": "Vetoed", "decisionDate": "2026-05-12"}), True)
check("vetoed", (s["kind"], s["steps"][4][1], s["steps"][5][:2]),
      ("vetoed", "Same version passed", ["stopped", "Vetoed"]))
s = bill_stage(bill(both, [HOUSE_APP, SEN_APP],
                    ga={"status": "Sent to Governor", "sentDate": "2026-02-25"}), True)
check("governor's desk stays current after adjournment", (s["kind"], s["steps"][5][0]), ("governor", "current"))

# --- session over ---------------------------------------------------------------
in_2025 = [{"statusHistory": h(("2025-04-04", "HPA"))}]
in_2026 = [{"statusHistory": h(("2026-04-04", "HPA"), ("2026-05-12", "EFF"))}]
check("first year carries over", session_over(in_2025, datetime(2025, 9, 1), 2026), False)
check("second year, 45 quiet days", session_over(in_2026, datetime(2026, 6, 1), 2026), True)
check("still sitting", session_over(in_2026, datetime(2026, 4, 20), 2026), False)
check("EFF/Governor rows are not action", session_over(in_2026, datetime(2026, 5, 25), 2026), True)
check("special session", session_over([{"statusHistory": h(("2026-06-23", "HPA"))}],
                                       datetime(2026, 11, 27)), True)
check("no history", session_over([{}], datetime(2026, 11, 27)), False)
bills = [dict(hb1148, session="2025_26"), dict(hb520, session="2026_ss")]
check("apply_stages", apply_stages(bills, datetime(2026, 11, 27), 2026), {"2025_26": True, "2026_ss": True})
check("stage set", bills[0]["stage"]["kind"], "died-committee")

# --- the legislative calendar decides adjournment when present ---------------
from lib.ga_bill_stage import sine_die  # noqa: E402
CAL = {"2025_26": {"lower": [[40, "2025-04-04"], [1, "2026-01-12"], [40, "2026-04-02"]]},
       "2026_ss": {"lower": [[1, "2026-06-17"], [5, "2026-06-23"]]}}
check("sine die is the last day of the whole calendar", sine_die(CAL["2025_26"]["lower"]), "2026-04-02")
check("no calendar", sine_die([]), None)
fresh = [dict(hb1148, session="2025_26"), dict(hb520, session="2026_ss")]
check("calendar: both over", apply_stages(fresh, datetime(2026, 11, 27), 2026, CAL),
      {"2025_26": True, "2026_ss": True})
check("dead step names the day", fresh[0]["stage"]["steps"][2][2],
      "Referred Mar 6, 2026 · never reported · session ended Apr 2, 2026")
fresh = [dict(hb1148, session="2025_26")]
check("calendar: sitting on sine die", apply_stages(fresh, datetime(2026, 4, 2), 2026, CAL), {"2025_26": False})
check("calendar beats the quiet-days rule", apply_stages(
    [dict(hb1148, session="2025_26")], datetime(2025, 9, 1), 2026, CAL), {"2025_26": False})
check("no calendar for a session: fallback", apply_stages(
    [dict(hb1148, session="2023_24")], datetime(2026, 11, 27), 2026, CAL), {"2023_24": True})

# --- the producer keeps the committed calendar when a call fails --------------
import generate_ga_bills_soap as G  # noqa: E402
got = G.legislative_calendar(["2025_26"], {"2025_26": {"upper": [[1, "2025-01-13"]]}},
                             fetch=lambda s, b: [[1, "2025-01-13"], [40, "2026-04-02"]] if b == "House" else [])
check("fetched House, carried-forward Senate", got,
      {"2025_26": {"lower": [[1, "2025-01-13"], [40, "2026-04-02"]], "upper": [[1, "2025-01-13"]]}})
check("nothing at all", G.legislative_calendar(["2025_26"], None, fetch=lambda s, b: []), {})

# --- the Governor's deadline (Ga. Const. Art. III, Sec. V, Para. XIII(a)) -------
from lib.ga_bill_stage import governor_deadline  # noqa: E402
REG = [[39, "2025-04-02"], [40, "2025-04-04"], [1, "2026-01-12"], [40, "2026-04-02"]]
check("sent after sine die: 40 days", governor_deadline("2026-04-10", REG), "2026-05-12")
check("sine die inside the six days: 40 days", governor_deadline("2025-04-01", REG), "2025-05-14")
check("sent mid-session: six days", governor_deadline("2026-03-20", REG), "2026-03-26")
check("first year adjourns on its own", governor_deadline("2025-04-10", REG), "2025-05-14")
check("special session", governor_deadline("2026-06-23", [[1, "2026-06-17"], [5, "2026-06-23"]]), "2026-08-02")
check("no calendar: six days", governor_deadline("2026-04-10", []), "2026-04-16")
check("no sent date", governor_deadline(None, REG), None)
desk = bill(both, [HOUSE_APP, SEN_APP], ga={"status": "Sent to Governor", "sentDate": "2026-04-10"})
cal = {"2025_26": {"lower": REG}}
apply_stages([dict(desk, session="2025_26")], datetime(2026, 4, 20), 2026, cal)
b = dict(desk, session="2025_26")
apply_stages([b], datetime(2026, 4, 20), 2026, cal)
check("waiting: label names the deadline", (b["stage"]["kind"], b["stage"]["label"], b["stage"]["governorDeadline"]),
      ("governor", "Sent to Governor · must act by May 12, 2026", "2026-05-12"))
check("waiting: step detail", b["stage"]["steps"][5], ["current", "On the Governor's desk",
                                                         "Sent Apr 10, 2026 · must act by May 12, 2026"])
b = dict(desk, session="2025_26")
apply_stages([b], datetime(2026, 5, 12, 20), 2026, cal)
check("on the deadline day it is still waiting", b["stage"]["kind"], "governor")
b = dict(desk, session="2025_26")
apply_stages([b], datetime(2026, 5, 13), 2026, cal)
check("deadline passed: law without signature", (b["stage"]["kind"], b["stage"]["label"], b["stage"]["steps"][5]),
      ("signed", "Became law without the Governor's signature",
       ["done", "Law without signature", "Not signed or vetoed by May 12, 2026"]))
s2 = dict(bill(both, [HOUSE_APP, SEN_APP], ga={"status": "Signed", "decisionDate": "2026-05-11", "actNumber": 5}),
          session="2025_26")
apply_stages([s2], datetime(2026, 11, 27), 2026, cal)
check("a decided bill gets no deadline", ("governorDeadline" in s2["stage"], s2["stage"]["label"]),
      (False, "Signed · Act 5"))

if failures:
    print("FAIL (%d):" % len(failures))
    for f in failures:
        print("  " + f)
    sys.exit(1)
print("ok")
