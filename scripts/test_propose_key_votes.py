#!/usr/bin/env python3
"""Offline tests for propose_key_votes.py (fixtures; no network).

Covers: ranking order on a known set, gating (local calendar, ceremonial resolutions,
already curated, out of window), an empty/near-empty new session, approval writing a
valid curated entry for GA and federal, duplicate refusal, dismissals, and — when the
committed data is present — that an approved entry survives the real generator and
validators (generate_curated_ga_bills.py -> validate_curated_ga_bills.py; the
federal Key Votes sidecar check in validate_federal_votes.py).

Usage:
  python scripts/test_propose_key_votes.py

Exits 0 on success, 1 on any failure.
"""

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import propose_key_votes as P  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}: got {got!r}, want {want!r}")
        failures.append(label)


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = P.main(argv)
    return code, out.getvalue(), err.getvalue()


def write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)


def gv(bill, session, chamber, motion, roll, date, yea, nay, d, r, result="Pass", title="A bill", url=None):
    return {"bill": bill, "billUrl": url or f"https://www.legis.ga.gov/legislation/{abs(hash(bill)) % 9999}",
            "title": title, "session": session, "motionText": motion, "chamber": chamber,
            "rollNumber": roll, "time": "10:00 AM", "date": date, "yea": yea, "nay": nay,
            "result": result,
            "partyTally": {"Democratic": {"yea": d[0], "nay": d[1]}, "Republican": {"yea": r[0], "nay": r[1]}}}


def ga_fixture(data_dir):
    H, S = "House of Representatives", "Senate"
    votes = {
        # HB 1: signed, tight, party-line, both chambers -> top
        "v1": gv("HB 1", "2027_28", H, "PASSAGE", 10, "2027-02-10", 92, 80, (2, 78), (90, 2), title="Tax credit; provide"),
        "v2": gv("HB 1", "2027_28", S, "AGREE TO HOUSE SUBSTITUTE", 22, "2027-02-20", 30, 24, (1, 23), (29, 1)),
        # HB 2: unanimous, one chamber, unsigned -> low
        "v3": gv("HB 2", "2027_28", H, "PASSAGE", 11, "2027-02-11", 170, 0, (75, 0), (95, 0), title="Roads; name a bridge"),
        # HB 3: local calendar batch -> gated out
        "v4": gv("HB 3", "2027_28", H, "Local Calendar", 12, "2027-02-11", 170, 0, (75, 0), (95, 0)),
        # HR 9: ceremonial resolution -> gated out
        "v5": gv("HR 9", "2027_28", H, "ADOPT", 13, "2027-02-12", 170, 0, (75, 0), (95, 0)),
        # HR 10: constitutional amendment that failed -> candidate, kind failed
        "v6": gv("HR 10", "2027_28", H, "ADOPTION OF CONSTITUTIONAL AMENDMENT", 14, "2027-02-13", 100, 80,
                 (20, 60), (80, 20), result="Fail", title="Constitutional amendment; ballot"),
        # HB 4: already curated -> excluded
        "v7": gv("HB 4", "2027_28", H, "PASSAGE", 15, "2027-02-14", 90, 80, (0, 80), (90, 0)),
        # HB 5: before the window -> excluded
        "v8": gv("HB 5", "2027_28", H, "PASSAGE", 16, "2026-12-01", 90, 80, (0, 80), (90, 0)),
        # SB 6: two House roll calls; the later one is operative
        "v9": gv("SB 6", "2027_28", H, "PASSAGE", 17, "2027-02-15", 60, 110, (0, 80), (60, 30), result="Fail"),
        "v10": gv("SB 6", "2027_28", H, "PASSAGE", 19, "2027-02-16", 100, 70, (5, 75), (95, 0)),
    }
    write(os.path.join(data_dir, "ga-votes-index.json"), {"metadata": {}, "voteIds": list(votes), "votes": votes})
    bill = lambda ident, status, subj, date="2027-03-01T10:00:00": {  # noqa: E731
        "identifier": ident, "session": "2027_28", "title": votes_title.get(ident, "A bill"),
        "status": status, "statusDate": date, "subjects": subj,
        "billUrl": f"https://www.legis.ga.gov/legislation/{ident.replace(' ', '')}"}
    votes_title = {"HB 1": "Tax credit; provide"}
    write(os.path.join(data_dir, "ga-bills.json"), {"metadata": {}, "bills": [
        bill("HB 1", "House Date Signed by Governor", ["REVENUE AND TAXATION"]),
        bill("HB 2", "House Read and Adopted", ["HIGHWAYS, BRIDGES, AND FERRIES"]),
        bill("SB 6", "Senate Read and Referred", []),
    ]})


def federal_fixture(data_dir):
    motions = ["On Passage", "On Cloture on the Motion to Proceed", "On the Nomination", "On Agreeing to the Resolution"]
    #   [chamber, date, type, number, title, motionIdx, result, yea, nay, tally dY dN dO rY rN rO]
    rows = [
        ["H", "2027-02-10", "hr", "100", "Appropriations Act, 2027", 0, "P", 216, 214, [2, 212, 1, 214, 2, 0]],
        ["S", "2027-02-20", "hr", "100", "Appropriations Act, 2027", 0, "P", 51, 49, [0, 46, 0, 51, 3, 0]],
        ["H", "2027-02-11", "hr", "101", "A bill to name a post office", 0, "P", 420, 0, [210, 0, 0, 210, 0, 0]],
        ["S", "2027-02-12", "s", "200", "A bill on cloture", 1, "P", 70, 30, [40, 4, 0, 30, 26, 0]],
        ["H", "2027-02-13", "hres", "55", "Ceremonial resolution", 3, "P", 400, 10, [200, 5, 0, 200, 5, 0]],
        ["S", "2027-02-14", None, None, "Nomination", 2, "P", 55, 45, [10, 40, 0, 45, 5, 0]],
        ["H", "2027-02-15", "hr", "102", "Already curated bill", 0, "P", 230, 200, [0, 200, 0, 230, 0, 0]],
        ["H", "2026-11-01", "hr", "103", "Too old", 0, "P", 230, 200, [0, 200, 0, 230, 0, 0]],
    ]
    ids = ["H2027_0001", "S120_1_00002", "H2027_0003", "S120_1_00004", "H2027_0005", "S120_1_00006", "H2027_0007", "H2026_0900"]
    write(os.path.join(data_dir, "federal-votes-index.json"), {
        "metadata": {"congress": 120}, "voteIds": ids, "motions": motions, "rows": rows})
    write(os.path.join(data_dir, "presidential-laws.json"), {"metadata": {"congress": 120}, "laws": [
        {"billLabel": "H.R. 100", "title": "Appropriations Act, 2027", "signingDate": "2027-03-01",
         "actionText": "Became Public Law No: 120-1."}]})


def main():
    tmp = tempfile.mkdtemp(prefix="kv-test-")
    try:
        data, out = os.path.join(tmp, "data"), os.path.join(tmp, "out")
        cga, cfed = os.path.join(tmp, "curated-ga-bills.json"), os.path.join(tmp, "curated-federal-bills.json")
        dec = os.path.join(tmp, "decisions.json")
        ga_fixture(data)
        federal_fixture(data)
        write(cga, {"_note": "n", "ga": [{"_name": "x", "session": "2027_28", "identifier": "HB 4"}]})
        write(cfed, {"_note": "n", "bills": [{"bill": "H.R. 102", "title": "t", "summary": "s", "billUrl": "u",
                                              "congress": 120, "voteIds": {"House": "H2027_0007"}}]})
        base = ["--data-dir", data, "--out-dir", out, "--curated-ga", cga, "--curated-federal", cfed,
                "--decisions", dec, "--today", "2027-03-05", "--days", "60"]

        print("ranking and gating")
        code, stdout, _ = run(base)
        check("propose exits 0", code, 0)
        ga = json.load(open(os.path.join(out, "ga.json"), encoding="utf-8"))
        ids = [p["id"] for p in ga["proposals"]]
        check("GA order (score, then id)", ids, ["ga-2027_28-hb1", "ga-2027_28-sb6", "ga-2027_28-hr10", "ga-2027_28-hb2"])
        check("local calendar, ceremonial resolution, curated and out-of-window bills are gated",
              {"ga-2027_28-hb3", "ga-2027_28-hr9", "ga-2027_28-hb4", "ga-2027_28-hb5"} & set(ids), set())
        top = ga["proposals"][0]
        check("HB 1 outcome is enacted", top["outcome"], "enacted")
        check("HB 1 both chambers recorded", [v["chamber"] for v in top["votes"]], ["House", "Senate"])
        pts = {s["name"]: s["points"] for s in top["signals"]}
        check("HB 1 signal points",
              (pts["outcome"], pts["bothChambers"], pts["salience"]), (25, 10, 10))
        check("HR 10 failure is proposed as failed", ga["proposals"][2]["outcome"], "failed")
        sb6 = ga["proposals"][1]
        check("SB 6 uses the later House roll call", sb6["votes"][0]["rollNumber"], 19)
        check("score is the sum of the signals", top["score"], round(sum(s["points"] for s in top["signals"]), 1))
        check("proposals file is never the curated list", json.load(open(cga))["ga"][0]["identifier"], "HB 4")

        fed = json.load(open(os.path.join(out, "federal.json"), encoding="utf-8"))
        fids = [p["id"] for p in fed["proposals"]]
        check("federal order", fids, ["federal-120-hr100", "federal-120-hr101"])
        check("federal enacted outcome from presidential-laws", fed["proposals"][0]["outcome"], "enacted")
        check("federal entry carries both chamber vote ids",
              fed["proposals"][0]["curatedEntry"]["voteIds"], {"House": "H2027_0001", "Senate": "S120_1_00002"})
        report = open(os.path.join(out, "report.md"), encoding="utf-8").read()
        check("report links the official record", "clerk.house.gov/evs/2027/roll001.xml" in report, True)
        check("report lists the party split", "D 2–212" in report, True)

        print("window")
        code, _, _ = run(base[:-2] + ["--days", "1"])
        check("a narrow window yields nothing and exits 0", (code, json.load(open(os.path.join(out, "ga.json")))["proposals"]), (0, []))
        run(base)

        print("approve")
        before = json.load(open(cga))
        code, stdout, _ = run(base + ["--approve", "ga-2027_28-hb1,ga-2027_28-hr10"])
        check("approve exits 0", code, 0)
        after = json.load(open(cga))
        check("existing entries and _note preserved", (after["_note"], after["ga"][0]), (before["_note"], before["ga"][0]))
        check("HB 1 written in the existing format", after["ga"][1],
              {"_name": "Tax credit", "session": "2027_28", "identifier": "HB 1"})
        check("no voteOverride is written (nothing reads one)", any("voteOverride" in e for e in after["ga"]), False)

        code, _, err = run(base + ["--approve", "ga-2027_28-hb1"])
        check("duplicate refused", code, 2)
        check("duplicate message names the file", "already in" in err, True)
        snapshot = open(cga, "rb").read()
        code, _, _ = run(base + ["--approve", "ga-2027_28-sb6,ga-2027_28-hb1"])
        check("a batch with one duplicate writes nothing", (code, open(cga, "rb").read()), (2, snapshot))
        code, _, err = run(base + ["--approve", "ga-2027_28-nope"])
        check("unknown id refused", code, 2)
        code, _, _ = run(base + ["--approve", "ga-2027_28-sb6,ga-2027_28-sb6"])
        check("repeated id refused", code, 2)
        code, _, _ = run(base + ["--approve", "state-1"])
        check("unrecognized id form refused", code, 2)

        code, _, _ = run(base + ["--approve", "federal-120-hr100"])
        check("federal approve exits 0", code, 0)
        fcur = json.load(open(cfed))
        check("federal entry has the generator-and-page fields",
              sorted(fcur["bills"][1]), ["bill", "billUrl", "congress", "summary", "title", "voteIds"])
        check("federal entry points at both roll calls", fcur["bills"][1]["voteIds"],
              {"House": "H2027_0001", "Senate": "S120_1_00002"})
        code, _, err = run(base + ["--approve", "federal-120-hr100"])
        check("federal duplicate refused", code, 2)

        print("dismiss")
        run(base + ["--dismiss", "ga-2027_28-sb6", "--note", "not needed"])
        check("dismissal recorded", json.load(open(dec))["dismissed"]["ga-2027_28-sb6"]["note"], "not needed")
        run(base)
        check("a dismissed candidate is no longer proposed",
              "ga-2027_28-sb6" in [p["id"] for p in json.load(open(os.path.join(out, "ga.json")))["proposals"]], False)

        print("empty new session")
        empty = os.path.join(tmp, "empty")
        write(os.path.join(empty, "ga-votes-index.json"), {"metadata": {}, "voteIds": [], "votes": {}})
        write(os.path.join(empty, "ga-bills.json"), {"metadata": {}, "bills": []})
        write(os.path.join(empty, "federal-votes-index.json"), {"metadata": {"congress": 120}, "voteIds": [], "motions": [], "rows": []})
        for label, d in (("empty files", empty), ("missing files", os.path.join(tmp, "nothing"))):
            code, stdout, _ = run(["--data-dir", d, "--out-dir", os.path.join(tmp, "o2"), "--curated-ga", os.path.join(tmp, "none.json"),
                                   "--curated-federal", os.path.join(tmp, "none2.json"), "--decisions", dec, "--today", "2027-01-12"])
            rep = open(os.path.join(tmp, "o2", "report.md"), encoding="utf-8").read()
            check(f"{label}: exits 0 with a no-candidates report", (code, "No candidates" in rep), (0, True))
        code, _, _ = run(["--data-dir", empty, "--out-dir", os.path.join(tmp, "o3"), "--curated-ga", os.path.join(tmp, "new-ga.json"),
                          "--decisions", dec])
        check("propose on an empty list leaves the missing curated file missing", os.path.exists(os.path.join(tmp, "new-ga.json")), False)
        # Approving into a curated file that does not exist yet (list emptied/new) creates it.
        shutil.copy(os.path.join(out, "ga.json"), os.path.join(tmp, "o3", "ga.json"))
        code, _, _ = run(["--data-dir", empty, "--out-dir", os.path.join(tmp, "o3"), "--curated-ga", os.path.join(tmp, "new-ga.json"),
                          "--decisions", dec, "--approve", "ga-2027_28-hb2"])
        check("approve creates a missing curated file with the right key",
              [e["identifier"] for e in json.load(open(os.path.join(tmp, "new-ga.json")))["ga"]], ["HB 2"])

        integration(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if failures:
        print(f"\n{len(failures)} failure(s): {failures}")
        return 1
    print("\nall passed")
    return 0


def integration(tmp):
    """The approve step's output through the real generator and validators, on the
    committed data. Skipped when that data is not present."""
    live = os.path.join(ROOT, "assets", "data")
    need = ["ga-votes-index.json", "ga-bills.json", "ga-member-votes.json", "ga-members.json",
            "federal-votes-index.json"]
    if not all(os.path.exists(os.path.join(live, n)) for n in need):
        print("integration: committed data absent, skipped")
        return
    print("integration: approve -> generate_curated_ga_bills.py -> validate_curated_ga_bills.py")
    out = os.path.join(tmp, "live-out")
    base = ["--out-dir", out, "--curated-ga", os.path.join(tmp, "live-ga.json"),
            "--curated-federal", os.path.join(tmp, "live-fed.json"),
            "--decisions", os.path.join(tmp, "live-dec.json"), "--since", "2026-03-01", "--until", "2026-11-22", "--limit", "3"]
    code, _, _ = run(base + ["--scope", "ga"])
    ga = json.load(open(os.path.join(out, "ga.json"), encoding="utf-8"))["proposals"]
    if not ga:
        print("  skip (no GA candidates in the committed window)")
    else:
        ids = ",".join(p["id"] for p in ga[:2])
        code, _, _ = run(base + ["--approve", ids])
        check("live GA approve exits 0", code, 0)
        work = os.path.join(tmp, "gen")
        os.makedirs(os.path.join(work, "assets"))
        os.symlink(live, os.path.join(work, "assets", "data")) if hasattr(os, "symlink") and False else \
            shutil.copytree(live, os.path.join(work, "assets", "data"),
                            ignore=shutil.ignore_patterns("ga-votes", "federal-votes", "ga-sponsorship", "federal-sponsorship",
                                                          "ga-bienniums", "candidates", "*.csv"))
        shutil.copy(os.path.join(tmp, "live-ga.json"), os.path.join(work, "assets", "data", "curated-ga-bills.json"))
        outfile = os.path.join(work, "curated-out.json")
        for sub in ("lib",):
            shutil.copytree(os.path.join(HERE, sub), os.path.join(work, "scripts", sub))
        shutil.copy(os.path.join(HERE, "generate_curated_ga_bills.py"), os.path.join(work, "scripts", "generate_curated_ga_bills.py"))
        shutil.copy(os.path.join(HERE, "validate_curated_ga_bills.py"), os.path.join(work, "scripts", "validate_curated_ga_bills.py"))
        env = dict(os.environ, PYTHONUTF8="1")
        gen = subprocess.run([sys.executable, "scripts/generate_curated_ga_bills.py", outfile], cwd=work,
                             capture_output=True, text=True, env=env, encoding="utf-8")
        check("generator accepts the approved entries", gen.returncode, 0)
        val = subprocess.run([sys.executable, "scripts/validate_curated_ga_bills.py", outfile], cwd=work,
                             capture_output=True, text=True, env=env, encoding="utf-8")
        check("validate_curated_ga_bills.py passes", val.returncode, 0)
        if val.returncode:
            print(val.stdout[-800:], val.stderr[-800:])
        got = {b["identifier"] for b in json.load(open(outfile, encoding="utf-8"))["bills"]}
        check("both approved bills were sourced", got, {p["identifier"] for p in ga[:2]})

    print("integration: federal approve -> Key Votes sidecar check")
    code, _, _ = run(base + ["--scope", "federal"])
    fed = json.load(open(os.path.join(out, "federal.json"), encoding="utf-8"))["proposals"]
    if not fed:
        print("  skip (no federal candidates in the committed window)")
        return
    code, _, _ = run(base + ["--approve", fed[0]["id"]])
    check("live federal approve exits 0", code, 0)
    import build_federal_votes_slices as B
    import validate_federal_votes as V
    idx = json.load(open(os.path.join(live, "federal-votes-index.json"), encoding="utf-8"))
    curated_path = os.path.join(tmp, "live-fed.json")
    wanted = B.curated_vote_ids(curated_path)
    side, missing = B.build_keyvotes_sidecar(idx["metadata"], idx["voteIds"], idx["rows"], idx["motions"], wanted)
    side_path = os.path.join(tmp, "side.json")
    write(side_path, side)
    V.problems.clear()
    V.check_keyvotes(side_path, curated_path, idx["voteIds"], idx["rows"], idx)
    check("every approved roll call is in the index", missing, [])
    check("validate_federal_votes key-votes check finds no problem", V.problems, [])


if __name__ == "__main__":
    sys.exit(main())
