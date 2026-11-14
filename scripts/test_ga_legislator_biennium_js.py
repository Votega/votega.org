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
        "const out = {pick: cases.map(c => pickBiennium(c[0], c[1])),"
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
    assert out["live"].endswith("assets/data/") and "ga-bienniums" not in out["live"], out["live"]
    assert out["frozen"].endswith("assets/data/ga-bienniums/2025_26/"), out["frozen"]
    assert out["contact"] == [True, False, False], out["contact"]
    assert out["role"] == ["Senator", "Former Senator"], out["role"]
    print("ok: biennium helpers")


if __name__ == "__main__":
    main()
