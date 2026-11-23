"""assets/scripts/departure-label.js: when a lame-duck label shows on a live page.

Prints `skip` and passes when node is not on PATH (CI has no Node guarantee).
Run: python scripts/test_departure_label_js.py        (no network, no repo writes)
"""
import json
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
JS = ROOT / "assets/scripts/departure-label.js"

GA = {"metadata": {"session": "2025_26", "termEnds": "2027-01-11"},
      "labels": {"123": {"label": "Lost the general election on November 3, 2026."}}}
FED = {"metadata": {"termEnds": "2027-01-03"}, "labels": {"X1": {"label": "Did not run."}}}
NO_END = {"metadata": {"session": "2025_26"}, "labels": GA["labels"]}

LIVE = {"live": True, "former": False, "session": "2025_26"}
# (doc, id, ctx, local date, shows?)
CASES = [
    ("GA", 123, LIVE, "2026-11-24", True),                                   # lame duck, number id
    ("GA", "123", LIVE, "2027-01-10", True),                                 # last day in office
    ("GA", "123", LIVE, "2027-01-11", False),                                # term over
    ("GA", "123", dict(LIVE, session="2027_28"), "2026-12-01", False),       # roster rolled over
    ("GA", "123", dict(LIVE, former=True), "2026-12-01", False),             # former page
    ("GA", "123", dict(LIVE, live=False), "2026-12-01", False),              # frozen biennium view
    ("GA", "999", LIVE, "2026-12-01", False),                                # no label
    ("FED", "X1", {"live": True, "former": False, "session": None}, "2027-01-02", True),
    ("FED", "X1", {"live": True, "former": False, "session": None}, "2027-01-03", False),
    ("NO_END", "123", LIVE, "2026-12-01", False),                            # fail closed
]


def main():
    if not shutil.which("node"):
        print("skip")
        return
    script = (
        "const D = require(" + json.dumps(str(JS)) + ");\n"
        "const docs = " + json.dumps({"GA": GA, "FED": FED, "NO_END": NO_END}) + ";\n"
        "const cases = " + json.dumps(CASES) + ";\n"
        "let bad = 0;\n"
        "for (const [doc, id, ctx, day, want] of cases) {\n"
        "  const got = !!D.lameDuckLabel(docs[doc], id, Object.assign({now: new Date(day + 'T12:00:00')}, ctx));\n"
        "  if (got !== want) { bad++; console.log('FAIL', doc, id, JSON.stringify(ctx), day, 'want', want); }\n"
        "}\n"
        "if (D.longDate('2027-01-11') !== 'January 11, 2027') { bad++; console.log('FAIL longDate'); }\n"
        "process.exit(bad ? 1 : 0);\n"
    )
    r = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    sys.stdout.write(r.stdout + r.stderr)
    if r.returncode:
        sys.exit("FAIL")
    print(f"ok {len(CASES) + 1} cases")


if __name__ == "__main__":
    main()
