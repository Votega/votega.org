#!/usr/bin/env python3
"""lib/month_dates.py: month-name dates for the revize and htmltable adapters. No network.
Run: python scripts/test_month_dates.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from lib.month_dates import parse_month_name_date as p  # noqa: E402
from lib import revize  # noqa: E402

CASES = [
    ("Work Session Agenda November 03, 2026.pdf", "2026-11-03"),
    ("Regular%20Meeting%20Minutes%20of%20October%2006,%202026.pdf", "2026-10-06"),
    ("January 13, 2026", "2026-01-13"),
    ("October 28, 2026", "2026-10-28"),   # a day starting with 2 or 0 must survive whole
    ("June%2022,%202026.pdf", "2026-06-22"),
    ("November 20, 2026", "2026-11-20"),
    ("Nov. 3rd, 2026", "2026-11-03"),
    ("May 2026", None),           # month + year, no day: never guessed
    ("Mayor 12, 2026", None),     # "may" inside a word
    ("February 30, 2026", None),  # impossible date
]
bad = [(t, p(t), want) for t, want in CASES if p(t) != want]
PAGE = ('<a href="Finance Committee Minutes October 06, 2026.pdf">x</a>'
        '<a href="Regular Meeting Minutes October 06, 2026.pdf">y</a>')
got = sorted(m["body"] for m in revize.parse_page(PAGE, "https://x.test/", split_committees=True))
if got != ["Board of Commissioners", "Finance Committee"] or len(revize.parse_page(PAGE, "https://x.test/")) != 1:
    bad.append(("split_committees", got, None))
if revize._parse_date("Minutes of October 06, 2026.pdf") != "2026-10-06" or revize._parse_date("9-2-2026") != "2026-09-02":
    bad.append(("revize._parse_date", None, None))
F = "Minutes and Agendas/"
m = revize.parse_page('<a href="%sWork Session Agenda November 03, 2026.pdf">a</a>'
                      '<a href="%sRegular Meeting Board Actions November 03, 2026.pdf">b</a>' % (F, F), "https://x.test/")[0]
if "Agenda" not in (m["agendaUrl"] or "") or "Board%20Actions" not in (m["minutesUrl"] or ""):
    bad.append(("folder name vs file name", m, None))
for b in bad:
    print("FAIL", b)
print("FAILED" if bad else "ok: month-name dates")
sys.exit(1 if bad else 0)
