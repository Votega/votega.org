#!/usr/bin/env python3
"""
Local AI enrichment for GA bills: plain-English summaries + subject tags.
Runs on the maintainer's PC only. No API keys, nothing called from the live site.

  draft   Ollama (local) first pass for every bill that's new or whose text changed.
  refine  Claude Code (`claude -p`, your subscription) rewrites key/flagged bills.
  status  Read-only report of which AI subject tags the bills generator will use.
          Tags are never written to ga-bills-subjects.json (manual overrides only):
          generate_ga_bills_soap.py reads REVIEWED tags from ga-bill-ai.json directly,
          for bills no other source tags, and marks them subjectsSource="ai".

Output: assets/data/ga-bill-ai.json  (separate file — no workflow ever overwrites it)

Usage:
  python scripts/ai_enrich_ga_bills.py draft  [--limit 50] [--session 2026_ss] [--model qwen2.5:14b]
  python scripts/ai_enrich_ga_bills.py refine [--limit 10] [--only "SB 443"]
  python scripts/ai_enrich_ga_bills.py status
"""

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from collections import Counter
from datetime import datetime, timezone

DATA_DIR = os.path.join("assets", "data")
BILLS_FILE = os.path.join(DATA_DIR, "ga-bills.json")
CURATED_FILE = os.path.join(DATA_DIR, "curated-ga-bills.json")
OUT_FILE = os.path.join(DATA_DIR, "ga-bill-ai.json")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/chat")
DEFAULT_MODEL = "qwen2.5:14b"
MAX_TEXT_CHARS = 12000  # caps Claude plan usage per bill

RULES = (
    "You summarize Georgia legislation for a nonpartisan voter-information site. "
    "Use ONLY the text provided. No opinions, no predictions, no characterizing a bill as "
    "good/bad, no mention of parties or sponsors' motives. Plain English, 8th-grade reading level. "
    "If the text is too thin to tell what the bill does, say so and set confidence to 'low'."
)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data, indent=1):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=indent, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def input_hash(bill):
    src = f"{bill.get('title','')}|{bill.get('abstract','')}"
    return hashlib.sha256(src.encode("utf-8")).hexdigest()[:16]


def taxonomy(bills):
    """Canonical subjects = whatever ga-bills.json already uses (Open States + 'Local / Municipal')."""
    return sorted({s for b in bills for s in (b.get("subjects") or [])})


def clean_result(raw, allowed):
    """Validate model JSON; drop subjects outside the taxonomy."""
    if isinstance(raw, str):
        raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
        raw = json.loads(raw)
    summary = (raw.get("summary") or "").strip()
    subjects = [s for s in (raw.get("subjects") or []) if s in allowed][:3]
    conf = raw.get("confidence") if raw.get("confidence") in ("high", "medium", "low") else "low"
    if not summary:
        raise ValueError("empty summary")
    return {"summary": summary, "subjects": subjects, "confidence": conf}


def load_out():
    out = load_json(OUT_FILE) or {}
    out.setdefault("metadata", {})
    out.setdefault("bills", {})
    return out


def write_out(out):
    out["metadata"].update({
        "updatedAt": now(),
        "count": len(out["bills"]),
        "note": "AI-generated drafts (Ollama) refined for key bills (Claude). Display with an 'AI summary' label and a link to the official bill.",
    })
    save_json(OUT_FILE, out)


# ---------- draft (Ollama) ----------

def ollama(model, bill, allowed):
    schema = {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "subjects": {"type": "array", "items": {"type": "string", "enum": allowed}},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        },
        "required": ["summary", "subjects", "confidence"],
    }
    prompt = (
        f"Bill: {bill['identifier']} — {bill.get('title','')}\n"
        f"Official caption: {bill.get('abstract','')}\n\n"
        "Return JSON: summary (2-3 sentences: what it would do and who it affects), "
        "subjects (1-3 from the allowed list), confidence."
    )
    body = json.dumps({
        "model": model,
        "stream": False,
        "format": schema,
        "options": {"temperature": 0.2},
        "messages": [{"role": "system", "content": RULES}, {"role": "user", "content": prompt}],
    }).encode("utf-8")
    req = urllib.request.Request(OLLAMA_URL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())["message"]["content"]


def cmd_draft(args):
    bills = load_json(BILLS_FILE)["bills"]
    allowed = taxonomy(bills)
    out = load_out()
    todo = [b for b in bills
            if b.get("identifier")
            and (not args.session or b.get("session") == args.session)
            and out["bills"].get(b["identifier"], {}).get("inputHash") != input_hash(b)]
    todo = todo[: args.limit] if args.limit else todo
    print(f"Drafting {len(todo)} bill(s) with {args.model}…")
    done = failed = 0
    for i, b in enumerate(todo, 1):
        try:
            res = clean_result(ollama(args.model, b, allowed), allowed)
        except Exception as e:  # keep going; one bad bill shouldn't stop the batch
            failed += 1
            print(f"  ! {b['identifier']}: {e}", file=sys.stderr)
            continue
        out["bills"][b["identifier"]] = {
            **res,
            "session": b.get("session"),
            "source": f"ollama:{args.model}",
            "inputHash": input_hash(b),
            "generatedAt": now(),
            "needsReview": True,  # a human approves every AI tag; confidence is the model's own guess
            "refined": False,
        }
        done += 1
        if i % 25 == 0:
            write_out(out)  # checkpoint so a crash doesn't lose work
            print(f"  …{i}/{len(todo)}")
    write_out(out)
    print(f"Done: {done} drafted, {failed} failed → {OUT_FILE}")
    return 1 if failed and not done else 0


# ---------- refine (Claude Code) ----------

def fetch_text(url):
    """Best-effort full text from legis.ga.gov PDF; falls back to caption if pypdf missing/fails."""
    if not url:
        return ""
    try:
        from pypdf import PdfReader
        with urllib.request.urlopen(url, timeout=60) as r:
            pdf = PdfReader(io.BytesIO(r.read()))
        text = "\n".join((p.extract_text() or "") for p in pdf.pages)
        return re.sub(r"\s+", " ", text)[:MAX_TEXT_CHARS]
    except Exception as e:
        print(f"    (full text unavailable: {e})", file=sys.stderr)
        return ""


def claude(prompt):
    exe = shutil.which("claude")
    if not exe:
        raise RuntimeError("Claude Code CLI not found on PATH (install it and run `claude` once to sign in).")
    r = subprocess.run([exe, "-p", "--output-format", "json"], input=prompt,
                       capture_output=True, text=True, encoding="utf-8", timeout=600)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[:300] or "claude exited non-zero")
    return json.loads(r.stdout)["result"]


def cmd_refine(args):
    bills = {b["identifier"]: b for b in load_json(BILLS_FILE)["bills"] if b.get("identifier")}
    allowed = taxonomy(bills.values())
    curated = {e["identifier"] for e in (load_json(CURATED_FILE) or {}).get("ga", [])}
    out = load_out()
    if args.only:
        targets = args.only
    else:  # key bills first, then low-confidence drafts
        flagged = [k for k, v in out["bills"].items() if v.get("confidence") == "low" and not v.get("refined")]
        targets = [k for k in curated if not out["bills"].get(k, {}).get("refined")] + flagged
    targets = [t for t in dict.fromkeys(targets) if t in bills][: args.limit]
    print(f"Refining {len(targets)} bill(s) with Claude Code (uses your plan's usage)…")
    for ident in targets:
        b = bills[ident]
        draft = out["bills"].get(ident, {})
        text = fetch_text(b.get("textUrl"))
        prompt = (
            f"{RULES}\n\nImprove this draft summary of Georgia bill {ident} — {b.get('title','')}. "
            "Fix anything the source doesn't support. Return ONLY JSON: "
            '{"summary": "...", "subjects": [...], "confidence": "high|medium|low"}\n'
            f"Allowed subjects: {json.dumps(allowed)}\n\n"
            f"Draft: {json.dumps(draft.get('summary',''))}\nDraft subjects: {draft.get('subjects', [])}\n\n"
            f"Official caption: {b.get('abstract','')}\n\n"
            f"Bill text (may be truncated or empty): {text}"
        )
        try:
            res = clean_result(claude(prompt), allowed)
        except Exception as e:
            print(f"  ! {ident}: {e}", file=sys.stderr)
            continue
        out["bills"][ident] = {
            **draft, **res,
            "session": b.get("session"),
            "source": "claude-code",
            "inputHash": input_hash(b),
            "usedFullText": bool(text),
            "generatedAt": now(),
            "needsReview": True,  # a human approves every AI tag, refined or not
            "refined": True,
        }
        write_out(out)
        print(f"  ✓ {ident}")
    return 0


# ---------- status (what the generator will apply) ----------

def cmd_status(args):
    """Read-only: what the bills generator will do with ga-bill-ai.json on its next run.

    AI tags are NOT copied into ga-bills-subjects.json — that file is manual overrides and
    is published as such. generate_ga_bills_soap.py reads ga-bill-ai.json itself and uses
    a REVIEWED tag (needsReview: false) only for a bill no other source tags, marking it
    subjectsSource="ai". So: approve entries here, commit ga-bill-ai.json, and the next
    weekly update-ga-bills run (or a manual dispatch) applies them."""
    bills = {b["identifier"]: b for b in load_json(BILLS_FILE)["bills"] if b.get("identifier")}
    ai = load_out()["bills"]
    c = Counter()
    for ident, v in ai.items():
        b = bills.get(ident)
        if not b or b.get("session") != v.get("session"):
            c["no matching bill"] += 1
        elif not v.get("subjects"):
            c["no subjects"] += 1
        elif b.get("subjects") and b.get("subjectsSource") != "ai":
            c["already tagged by another source"] += 1
        elif v.get("needsReview", True):
            c["untagged, awaiting review"] += 1
        else:
            c["untagged, reviewed: generator will apply"] += 1
    print(f"{len(ai)} AI entr(ies) in {OUT_FILE}:")
    for k, n in c.most_common():
        print(f"  {n:5d}  {k}")
    print("Approve an entry by setting needsReview: false, commit ga-bill-ai.json, "
          "then run update-ga-bills (weekly, or dispatch it).")
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("draft"); d.add_argument("--limit", type=int); d.add_argument("--session"); d.add_argument("--model", default=DEFAULT_MODEL)
    r = sub.add_parser("refine"); r.add_argument("--limit", type=int, default=10); r.add_argument("--only", nargs="+")
    sub.add_parser("status")
    args = p.parse_args()
    sys.exit({"draft": cmd_draft, "refine": cmd_refine, "status": cmd_status}[args.cmd](args))


if __name__ == "__main__":
    main()
