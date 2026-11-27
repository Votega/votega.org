#!/usr/bin/env python3
"""Import the Governor's veto messages and signing statements for one session year.

Source: the Governor's office publishes one PDF a year, after the signing deadline, at
https://gov.georgia.gov/executive-action/legislation/vetoed-legislation/<year>
("<year> Veto Messages and Signing Statements"). legis.ga.gov's web service carries the
veto NUMBER (ActVetoNumber 'V1') but not the message, so this is the only source.

The PDF is a run of blocks headed "VETO <n>" or "SIGNING STATEMENT <n>", each ending
"I VETO HOUSE BILL 14." / "I therefore sign Senate Bill 220 into law." This parses
them, takes the bill from that closing line (falling back to the first bill named),
and writes them to assets/data/ga-governor-statements.json, replacing that year's
entries. The text is the Governor's, word for word, with the PDF's line wrapping
undone; nothing is summarised.

Refuses to write (exit 1) unless the vetoes match ga-bills.json exactly: every VETO n
names a bill the data has as vetoed in that year, and every bill vetoed that year has
a message. Veto numbers run 1..N with no gaps.

Usage:
  python scripts/import_governor_statements.py 2026 SESSION_TAG URL_OR_PDF [--dry-run]
  e.g. python scripts/import_governor_statements.py 2026 2025_26 \\
    https://gov.georgia.gov/document/2026-vetoed-legislation/2026-veto-messages-and-signing-statements/download
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.atomic_io import write_json_atomic  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "data", "ga-governor-statements.json")
BILLS = os.path.join(ROOT, "assets", "data", "ga-bills.json")

_HEAD_RE = re.compile(r"^\s*(VETO|SIGNING STATEMENT)\s+(\d+)\s*$")
_BILL_RE = re.compile(r"\b(House|Senate)\s+(Bill|Resolution)\s+(\d+)(\s*EX)?\b", re.IGNORECASE)
_CLOSING_RE = re.compile(r"I\s+(?:VETO|therefore\s+sign|sign)\s+(HOUSE|SENATE)\s+(BILL|RESOLUTION)\s+(\d+)",
                         re.IGNORECASE)
_NOISE_RE = re.compile(r"^\s*(Page \d+ of \d+|\+\+|GOVERNOR .*|\d{4} SESSION OF THE .*|VETO MESSAGES AND .*)\s*$")
_PREFIX = {("house", "bill"): "HB", ("senate", "bill"): "SB",
           ("house", "resolution"): "HR", ("senate", "resolution"): "SR"}


def pdf_text(source):
    """pdftotext -layout of a local PDF or a URL."""
    path = source
    tmp = None
    if re.match(r"https?://", source):
        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        req = urllib.request.Request(source, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            tmp.write(r.read())
        tmp.close()
        path = tmp.name
    try:
        return subprocess.run(["pdftotext", "-layout", path, "-"], check=True,
                              capture_output=True, text=True).stdout
    finally:
        if tmp:
            os.unlink(tmp.name)


def _identifier(chamber, kind, number):
    return "%s %s" % (_PREFIX[(chamber.lower(), kind.lower())], int(number))


def _paragraphs(lines):
    """Undo the PDF's line wrapping: blank lines separate paragraphs."""
    paras, cur = [], []
    for ln in lines:
        if ln.strip():
            cur.append(ln.strip())
        elif cur:
            paras.append(" ".join(cur))
            cur = []
    if cur:
        paras.append(" ".join(cur))
    return [re.sub(r"\s+", " ", p) for p in paras]


def parse(text):
    """[{kind, number, bill, text}] in document order."""
    blocks, cur = [], None
    for ln in text.splitlines():
        m = _HEAD_RE.match(ln)
        if m:
            cur = {"kind": "veto" if m.group(1) == "VETO" else "signing",
                   "number": int(m.group(2)), "lines": []}
            blocks.append(cur)
        elif cur is not None and not _NOISE_RE.match(ln):
            cur["lines"].append(ln)
    out = []
    for b in blocks:
        paras = _paragraphs(b["lines"])
        body = "\n\n".join(paras)
        close = None
        for m in _CLOSING_RE.finditer(body):
            close = m
        first = _BILL_RE.search(body)
        if close:
            bill = _identifier(close.group(1), close.group(2), close.group(3))
        elif first:
            bill = _identifier(first.group(1), first.group(2), first.group(3))
        else:
            raise SystemExit("could not find the bill in %s %d" % (b["kind"], b["number"]))
        out.append({"kind": b["kind"], "number": b["number"], "bill": bill, "text": body})
    return out


def check_against_bills(statements, year, session, bills):
    """Errors when the vetoes do not match the bills vetoed in `year` in `session`."""
    errors = []
    vetoed = {b["identifier"] for b in bills
              if b.get("session") == session
              and (b.get("governorAction") or {}).get("status") == "Vetoed"
              and str((b.get("governorAction") or {}).get("decisionDate") or "")[:4] == str(year)}
    known = {b["identifier"] for b in bills if b.get("session") == session}
    vetoes = [s for s in statements if s["kind"] == "veto"]
    for kind in ("veto", "signing"):
        nums = sorted(s["number"] for s in statements if s["kind"] == kind)
        if nums != list(range(1, len(nums) + 1)):
            errors.append("%s numbers are not 1..%d: %s" % (kind, len(nums), nums))
    for s in vetoes:
        if s["bill"] not in vetoed:
            errors.append("VETO %d names %s, which ga-bills.json does not have as vetoed in %s"
                          % (s["number"], s["bill"], year))
    for bill in sorted(vetoed - {s["bill"] for s in vetoes}):
        errors.append("%s was vetoed in %s but has no veto message" % (bill, year))
    for s in statements:
        if s["kind"] == "signing" and s["bill"] not in known:
            errors.append("SIGNING STATEMENT %d names %s, not a %s bill" % (s["number"], s["bill"], session))
    return errors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("year", type=int, help="the year the Governor acted, e.g. 2026")
    ap.add_argument("session", help="session tag the bills belong to, e.g. 2025_26")
    ap.add_argument("source", help="the PDF's URL (cited on the site) or a local copy")
    ap.add_argument("--url", default=None, help="the URL to cite when `source` is a local file")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    url = args.url or (args.source if re.match(r"https?://", args.source) else None)
    if not url:
        sys.exit("give --url: the site cites the Governor's published document")
    statements = parse(pdf_text(args.source))
    bills = json.load(open(BILLS, encoding="utf-8"))["bills"]
    errors = check_against_bills(statements, args.year, args.session, bills)
    if errors:
        print("Refusing to write:\n  " + "\n  ".join(errors), file=sys.stderr)
        sys.exit(1)

    try:
        doc = json.load(open(OUT, encoding="utf-8"))
    except (OSError, ValueError):
        doc = {"metadata": {"description": "The Governor of Georgia's veto messages and signing "
                                           "statements, word for word, from the Governor's "
                                           "published documents (scripts/import_governor_statements.py).",
                            "sources": []},
               "statements": []}
    doc["statements"] = [s for s in doc["statements"] if s.get("year") != args.year]
    for s in statements:
        doc["statements"].append({"year": args.year, "session": args.session, **s, "sourceUrl": url})
    doc["statements"].sort(key=lambda s: (s["year"], s["kind"] != "veto", s["number"]))
    doc["metadata"]["sources"] = sorted(
        [x for x in doc["metadata"].get("sources", []) if x.get("year") != args.year]
        + [{"year": args.year, "session": args.session, "url": url,
            "vetoes": sum(1 for s in statements if s["kind"] == "veto"),
            "signingStatements": sum(1 for s in statements if s["kind"] == "signing")}],
        key=lambda x: x["year"])
    for s in statements:
        print("  %-8s %2d  %s" % (s["kind"], s["number"], s["bill"]))
    if args.dry_run:
        print("dry run: nothing written")
        return
    write_json_atomic(OUT, doc)
    print("Wrote %d statements for %d to %s" % (len(statements), args.year, OUT))


if __name__ == "__main__":
    main()
