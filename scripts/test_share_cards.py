#!/usr/bin/env python3
"""Offline checks for the per-entity share-card renderer (scripts/lib/share_card.py).

No browser and no network: the module is pure string/file work. The Chromium render in
build_share_cards.py is exercised by running it.

Usage:
  python scripts/test_share_cards.py

Stdlib only. Exits 0 on success, 1 on any failure.
"""

import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from lib import share_card as S  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def truth(label, cond):
    check(label, bool(cond), True)


# --- monogram / names -------------------------------------------------------
check("monogram first+last", S.monogram("Derek Dooley"), "DD")
check("monogram skips suffix", S.monogram("Herbert Lehman Franklin III"), "HF")
check("monogram skips title", S.monogram("Dr. Jane Q. Public Jr."), "JP")
check("monogram single word", S.monogram("Cher"), "C")
check("monogram empty falls back", S.monogram(""), "VG")
check("suffix upper-cased and bound", S.display_name("Herbert Franklin Iii"), "Herbert Franklin III")
check("Jr. normalised", S.display_name("John G. Roberts, jr"), "John G. Roberts, Jr")
check("no suffix untouched", S.display_name("Akbar Ali"), "Akbar Ali")

sizes = [S.name_font_px("x" * n) for n in (5, 16, 17, 24, 25, 34, 35, 80)]
truth("headline never below the guide's 48px", min(sizes) >= 48)
truth("headline shrinks as the name grows", sizes == sorted(sizes, reverse=True))

check("party d", S.party_key("Democratic"), "d")
check("party r", S.party_key("Republican"), "r")
check("party i", S.party_key("Independent"), "i")
check("no party key for others", S.party_key("Libertarian"), None)
check("nonpartisan has no key", S.party_key(""), None)

check("stamp formats", S.fmt_stamp("2026-10-21"), "October 21, 2026")
check("stamp tolerates a timestamp", S.fmt_stamp("2026-10-21T14:23:33Z"), "October 21, 2026")
check("bad stamp is omitted", S.fmt_stamp("soon"), None)

# --- card markup ------------------------------------------------------------
TOKENS = ":root{--color-surface:#fff}"
row = {"name": "Jane <b>Doe</b>", "kind": "person", "role": "GA House District 5",
       "party": "Democratic", "badges": ["Incumbent"], "fact": "General election: November 3, 2026",
       "stamp": "2026-10-20", "source": "Georgia Secretary of State"}
doc = S.card_html(row, TOKENS, HERE)
truth("name is HTML-escaped", "<b>Doe</b>" not in doc and "&lt;b&gt;Doe" in doc)
truth("monogram shown without a photo", 'class="mono-text"' in doc)
truth("party pill uses the party token class", 'class="pill p-d"' in doc)
truth("data stamp and source printed", "Data last updated: October 20, 2026" in doc and "Source: Georgia Secretary of State" in doc)
truth("domain printed", "VOTEGA.ORG" in doc)

css, body = S.card_parts(row, HERE)
truth("no raw hex colours in the card CSS", not re.search(r"#[0-9a-fA-F]{3,8}\b", css))
px = [int(m) for m in re.findall(r"font-size:\s*(\d+)px", css)]
truth("nothing under 24px on the 1200px canvas", min(px) >= 24)

with tempfile.TemporaryDirectory() as tmp:
    with open(os.path.join(tmp, "p.jpg"), "wb") as fh:
        fh.write(b"\xff\xd8\xff\xd9")
    withphoto = S.card_html({**row, "photo": "p.jpg"}, TOKENS, tmp)
    truth("portrait embedded as a data URI when present", "data:image/jpeg;base64," in withphoto)
    truth("monogram dropped when a portrait is shown", 'mono-text' not in withphoto.split("<body>")[1])
    missing = S.card_html({**row, "photo": "gone.jpg"}, TOKENS, tmp)
    truth("a missing portrait file falls back to the monogram", 'mono-text' in missing.split("<body>")[1])

# Two candidates in one race must get the same layout: only the text may differ.
a = S.card_parts({**row, "name": "Alpha One"}, HERE)
b = S.card_parts({**row, "name": "Beta Two"}, HERE)
strip = lambda t: re.sub(r">[^<]*<", "><", t)  # noqa: E731
check("same structure for every candidate", strip(a[1]), strip(b[1]))

race = S.card_html({"name": "GA House District 100", "kind": "race", "role": "Georgia election"}, TOKENS, HERE)
truth("race card carries the ballot icon, not a monogram", "<svg" in race and "mono-text" not in race.split("<body>")[1])

# --- candidate line: who gets a card, and what it says ----------------------
A = {"id": "a", "name": "Ann Able", "party": "Democrat", "occupation": "Teacher", "county": "Fulton"}
B = {"id": "b", "name": "Bob Baker", "party": "Republican"}
C = {"id": "c", "name": "Cy Cole", "party": "Independent"}
D = {"id": "d", "name": "Di Dunn", "party": "Libertarian"}
E = {"id": "e", "name": "Ed Egan", "party": "Green"}
check("legislative: occupation and county", S.candidate_line([A, B], "a", True), (True, "Teacher · Fulton County"))
check("legislative with no filing data falls back to opponents", S.candidate_line([A, B], "b", True), (True, "vs. Ann Able (D)"))
check("non-legislative uses opponents even with occupation", S.candidate_line([A, B], "a", False), (True, "vs. Bob Baker (R)"))
check("someone off the active ballot gets no card", S.candidate_line([A, B], "zz", True), (False, None))
check("unopposed with no data has no line", S.candidate_line([B], "b", False), (True, None))
check("county alone", S.candidate_line([{"id": "x", "name": "X", "county": "Bibb"}], "x", True), (True, "Bibb County"))
check("occupation alone", S.candidate_line([{"id": "x", "name": "X", "occupation": "Nurse"}], "x", True), (True, "Nurse"))
check("keys fall back to the name when there is no id", S.candidate_line([{"name": "Solo"}], "Solo", False), (True, None))
check("rivals capped at three with a count", S.rivals_line([A, B, C, D, E]), "vs. Ann Able (D), Bob Baker (R), Cy Cole (I) +2 more")
check("unknown party gets no initial", S.rivals_line([E]), "vs. Ed Egan")
check("no rivals, no line", S.rivals_line([]), None)

two = S.card_html({**row, "fact2": "General election: November 3, 2026"}, TOKENS, HERE)
truth("second fact line rendered", 'class="fact2"' in two and "General election: November 3, 2026" in two)
truth("no second line when absent", 'class="fact2"' not in doc)

# --- front-matter patch -----------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    path = os.path.join(tmp, "e.html")
    src = "---\nlayout: default\ntitle: \"X\"\nentity:\n  type: \"candidate\"\n---\n<p>body</p>\n"
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(src)
    truth("patch reports success", S.patch_front_matter(path, "/assets/img/share/c/x.png"))
    once = open(path, encoding="utf-8").read()
    truth("share-img added inside the front matter", once.index("share-img:") < once.index("\n---\n", 4))
    truth("body left untouched", once.endswith("<p>body</p>\n"))
    S.patch_front_matter(path, "/assets/img/share/c/x.png")
    check("patch is idempotent", open(path, encoding="utf-8").read(), once)
    S.patch_front_matter(path, "/assets/img/share/c/y.png")
    after = open(path, encoding="utf-8").read()
    check("a second path replaces, never duplicates", after.count("share-img:"), 1)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("no front matter\n")
    check("a file with no front matter is refused", S.patch_front_matter(path, "/x.png"), False)

if failures:
    print(f"\n{len(failures)} failure(s): {failures}")
    sys.exit(1)
print("\nall share-card checks passed")
