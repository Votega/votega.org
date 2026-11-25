"""pickBiennium / dataRoot in the GA legislator include, run under node.

Prints `skip` and passes when node is not on PATH (CI has no Node guarantee).
"""
import json
import pathlib
import re
import shutil
import subprocess
import sys

INCLUDE = pathlib.Path(__file__).resolve().parent.parent / "_includes/entity/ga-legislator.html"

PICK_CASES = [
    (["current", "2025_26"], None, "current"),
    (["current", "2025_26"], "2025-2026", "2025_26"),
    (["2025_26"], None, "2025_26"),
    (["current"], "1999-2000", "current"),
    (["current"], "<script>", "current"),
    ([], None, "current"),
    (["current", "2025_26"], "2025_26", "current"),
]


def member(**kw):
    return dict({"id": "m1", "status": None, "statusDate": None, "termStart": None,
                 "termStartSession": "2025-2026 Regular Session"}, **kw)


def voted(date, chamber="house"):
    return [{"votes": {chamber: {"date": date, "memberVotes": {"m1": "yes"}}}}]


# (label, member, vote date, curated bills, want)
OFFICE_CASES = [
    ("seated mid-biennium, vote before", member(termStart="2025-12-18"), "2025-04-04", [], True),
    ("seated mid-biennium, vote after", member(termStart="2025-12-18"), "2026-03-01", [], False),
    ("vote on the day they were seated", member(termStart="2025-12-18"), "2025-12-18", [], False),
    ("first biennium is later than the vote", member(termStart="2025-01-13"), "2024-03-14", [], True),
    ("later first biennium, no termStart", member(), "2024-03-14", [], True),
    ("same biennium, no termStart: unknown", member(), "2025-03-06", [], False),
    ("no first session: unknown", member(termStart="2025-12-18", termStartSession=None), "2025-04-04", [], False),
    ("served in an earlier biennium (other chamber or a gap)",
     member(termStart="2025-12-31", termStartSession="2021 Special Session"), "2025-04-04", [], False),
    ("termStart outside the first biennium is not trusted",
     member(termStart="2025-01-13", termStartSession="2023 Special Session"), "2024-03-14", [], False),
    ("an earlier recorded vote proves service", member(termStart="2025-12-18"), "2025-04-04", voted("2025-03-06"), False),
    ("a vote in the other chamber counts", member(termStart="2025-12-18"), "2025-04-04", voted("2025-03-06", "senate"), False),
    ("a later vote proves nothing", member(termStart="2025-12-18"), "2025-04-04", voted("2026-03-01"), True),
    ("left before the vote", member(status="Resigned", statusDate="2025-09-05", termStartSession="2019-2020 Regular Session"),
     "2026-03-01", [], True),
    ("suspended members keep their seat", member(status="Suspended", statusDate="2025-09-05", termStartSession="2019-2020 Regular Session"),
     "2026-03-01", [], False),
    ("no vote date", member(termStart="2025-12-18"), None, [], False),
]


def extract():
    text = INCLUDE.read_text(encoding="utf-8")
    m = re.search(r"// BEGIN biennium-helpers\n(.*?)// END biennium-helpers", text, re.S)
    if not m:
        sys.exit("FAIL: biennium-helpers markers not found in " + str(INCLUDE))
    return m.group(1)


def main():
    helpers = extract()
    if not shutil.which("node"):
        print("skip")
        return
    script = (
        "function getBasePath(){return '/';}\n" + helpers +
        "\nconst cases = " + json.dumps(PICK_CASES) + ";\n"
        "const office = " + json.dumps([c[1:4] for c in OFFICE_CASES]) + ";\n"
        "const out = {office: office.map(c => notInOffice(c[0], c[1], c[2])), pick: cases.map(c => pickBiennium(c[0], c[1])),"
        " live: dataRoot('current'), frozen: dataRoot('2025_26'),"
        " contact: [showContact(true,null), showContact(true,{biennium:'current'}), showContact(false,null)],"
        " role: [pageTitleRole('Senator',null), pageTitleRole('Senator',{biennium:'current'})]};\n"
        "console.log(JSON.stringify(out));\n"
    )
    r = subprocess.run(["node", "-e", script], capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        sys.exit("FAIL: node error: " + r.stderr)
    out = json.loads(r.stdout)
    for (avail, param, want), got in zip(PICK_CASES, out["pick"]):
        assert got == want, f"pickBiennium({avail}, {param!r}) = {got!r}, want {want!r}"
    for (label, *_rest, want), got in zip(OFFICE_CASES, out["office"]):
        assert got is want, f"notInOffice, {label}: got {got!r}, want {want!r}"
    assert out["live"].endswith("assets/data/") and "ga-bienniums" not in out["live"], out["live"]
    assert out["frozen"].endswith("assets/data/ga-bienniums/2025_26/"), out["frozen"]
    assert out["contact"] == [True, False, False], out["contact"]
    assert out["role"] == ["Senator", "Former Senator"], out["role"]
    print("ok: biennium helpers")


if __name__ == "__main__":
    main()
