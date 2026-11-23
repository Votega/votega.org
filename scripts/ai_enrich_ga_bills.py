#!/usr/bin/env python3
"""
Local AI enrichment for GA bills: plain-English summaries + subject tags.
Runs on the maintainer's PC only. No API keys, nothing called from the live site.

  draft   Ollama (local) first pass for every bill that's new or whose text changed.
  refine  Claude Code (`claude -p`, your subscription) rewrites key/flagged bills.
  publish Rebuild assets/data/ga-bill-summaries.json (what /ga-bills shows) after you
          approve entries by hand. draft/refine rebuild it automatically.
  status  Read-only report of which AI subject tags the bills generator will use.
          Tags are never written to ga-bills-subjects.json (manual overrides only):
          generate_ga_bills_soap.py reads REVIEWED tags from ga-bill-ai.json directly,
          for bills no other source tags, and marks them subjectsSource="ai".

Output: assets/data/ga-bill-ai.json  (separate file — no workflow ever overwrites it)

Usage:
  python scripts/ai_enrich_ga_bills.py draft  [--limit 50] [--session 2026_ss] [--model qwen2.5:14b]
  python scripts/ai_enrich_ga_bills.py refine [--limit 10] [--only "SB 443"]
  python scripts/ai_enrich_ga_bills.py status
  python scripts/ai_enrich_ga_bills.py publish
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

# Anchored to the repo root (this file lives in scripts/), so it runs from any directory.
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "data")
BILLS_FILE = os.path.join(DATA_DIR, "ga-bills.json")
CURATED_FILE = os.path.join(DATA_DIR, "curated-ga-bills.json")
OUT_FILE = os.path.join(DATA_DIR, "ga-bill-ai.json")
# What the site loads: REVIEWED summaries only, plus editor-written summaryOverrides,
# which always win. Small on purpose: ga-bill-ai.json is ~1.3 MB of mostly drafts.
PUBLIC_FILE = os.path.join(DATA_DIR, "ga-bill-summaries.json")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/chat")
DEFAULT_MODEL = "qwen2.5:14b"
MAX_TEXT_CHARS = 12000  # caps Claude plan usage per bill

RULES = (
    "You summarize Georgia legislation for a nonpartisan voter-information site. "
    "Use ONLY the text provided. No opinions, no predictions, no characterizing a bill as "
    "good/bad, no mention of parties or sponsors' motives. Plain English, 8th-grade reading level. "
    "If the text is too thin to tell what the bill does, say so and set confidence to 'low'. "
    "The official caption is legal boilerplate and is often CUT OFF mid-sentence: never guess "
    "how a cut-off sentence ends, and never add details it does not state (ages, dollar amounts, "
    "time periods, exceptions, who qualifies). Skip boilerplate such as 'to repeal conflicting "
    "laws' and 'to provide for related matters'."
)
# Bump whenever the prompt or schema changes: it is part of input_hash, so every draft made
# under an older prompt is redone on the next `draft` run instead of being skipped.
PROMPT_VERSION = 3


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


# Honorary resolutions (commendations, condolences, recognitions, road dedications) are
# ~2,600 of the ~2,850 untagged records. They have no topic to tag and their caption IS the
# summary, so drafting them only adds noise (the model forces a subject onto each one).
_CEREMONIAL_RE = re.compile(
    r"\b(commend\w*|condolences?|congratulat\w*|honor(?:ing|s)?\b|recogniz\w*|celebrat\w*|"
    r"memory of|day at the (?:state )?capitol|dedicat\w*)", re.I)


def is_ceremonial(bill):
    """A House/Senate resolution whose title or caption reads as honorary. Bills never are."""
    if (bill.get("identifier") or "").split(" ")[0] not in ("HR", "SR"):
        return False
    return bool(_CEREMONIAL_RE.search(f"{bill.get('title','')} {bill.get('abstract','')}"))


def input_hash(bill, model=""):
    src = f"{bill.get('title','')}|{bill.get('abstract','')}|v{PROMPT_VERSION}|{model}"
    return hashlib.sha256(src.encode("utf-8")).hexdigest()[:16]


def code_titles():
    """{title number: subject name} from legis.ga.gov GetTitles, via the bills generator.
    The subject vocabulary IS the O.C.G.A. Title names, and captions cite titles by number
    ("amend Chapter 7 of Title 48"), so giving the model the map is the biggest single
    accuracy gain. Returns {} if the service is unreachable; drafting still works."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from generate_ga_bills_soap import get_titles
        return get_titles() or {}
    except Exception as e:
        print(f"  (code title map unavailable: {e})", file=sys.stderr)
        return {}


def taxonomy(bills):
    """Canonical subjects = whatever ga-bills.json already uses (Open States + 'Local / Municipal')."""
    return sorted({s for b in bills for s in (b.get("subjects") or [])})


def clean_result(raw, allowed):
    """Validate model JSON; drop subjects outside the taxonomy."""
    if isinstance(raw, str):
        raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
        # Take the first JSON object and ignore any note the model adds before or after it.
        raw = json.JSONDecoder().raw_decode(raw[raw.index("{"):])[0]
    summary = (raw.get("summary") or "").strip()
    subjects = list(dict.fromkeys(s for s in (raw.get("subjects") or []) if s in allowed))[:3]
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
    save_json(PUBLIC_FILE, build_public(out, load_json(CURATED_FILE) or {}))


def build_public(out, curated):
    """{metadata, summaries: {"<session>|<identifier>": {text, source}}} for the site.

    source "editor": a human summaryOverride from curated-ga-bills.json. It always wins,
    so AI text never replaces it. source "ai": a REVIEWED (needsReview false) AI summary.
    Unreviewed drafts are left out entirely. Keys carry the session because bill
    numbers restart each biennium."""
    summaries = {}
    for ident, v in sorted(out.get("bills", {}).items()):
        if v.get("needsReview", True) is False and v.get("summary") and v.get("session"):
            summaries[f"{v['session']}|{ident}"] = {
                "text": v["summary"], "source": "ai", "refined": bool(v.get("refined"))}
    for e in curated.get("ga", []):
        text = (e.get("summaryOverride") or "").strip()
        if text and e.get("identifier") and e.get("session"):
            summaries[f"{e['session']}|{e['identifier']}"] = {"text": text, "source": "editor"}
    return {
        "metadata": {
            "note": "Bill summaries shown on /ga-bills. 'editor' = written by Votega; "
                    "'ai' = AI-generated from the official bill and reviewed by a person. "
                    "Built by scripts/ai_enrich_ga_bills.py; do not edit by hand.",
            "count": len(summaries),
            "ai": sum(1 for s in summaries.values() if s["source"] == "ai"),
            "editor": sum(1 for s in summaries.values() if s["source"] == "editor"),
        },
        "summaries": summaries,
    }


def cmd_publish(args):
    """Rebuild ga-bill-summaries.json, e.g. after approving entries by hand."""
    out = load_out()
    data = build_public(out, load_json(CURATED_FILE) or {})
    save_json(PUBLIC_FILE, data)
    m = data["metadata"]
    print(f"{m['count']} summaries ({m['ai']} reviewed AI, {m['editor']} editor) → {PUBLIC_FILE}")
    return 0


# ---------- draft (Ollama) ----------

# "to amend an Act providing a $40,000 exemption for residents 65 to 70 ..." describes the
# EXISTING law; the change comes later ("so as to ...") and is often past the 500-char cut.
# The model read those existing figures as the new ones, so these captions get an extra rule.
_AMENDS_ACT_RE = re.compile(r"to amend an Act (?:providing|to provide|creating|to create|establishing)", re.I)
AMENDS_ACT_RULE = (
    "\n\nIMPORTANT: this caption amends an existing Act. The words right after 'to amend an "
    "Act' describe the CURRENT law, not the change. Any amounts, ages, or dates in that part "
    "are what the law says NOW. Describe only the change stated after 'so as to'. If the change "
    "is cut off, say what the bill amends without giving new figures, and set confidence to 'low'."
)


def subject_guide(allowed, titles):
    """The allowed list as prompt text, with each subject's Code Title number when known."""
    num = {name: n for n, name in titles.items()}
    return "\n".join(f"- {s}" + (f"  (Title {num[s]})" if s in num else "") for s in allowed)


def ollama(model, bill, allowed, titles=None):
    schema = {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "subjects": {"type": "array", "items": {"type": "string", "enum": allowed},
                         "maxItems": 3},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        },
        "required": ["summary", "subjects", "confidence"],
    }
    prompt = (
        f"Bill: {bill['identifier']} — {bill.get('title','')}\n"
        f"Official caption: {bill.get('abstract','')}\n\n"
        "Return JSON with:\n"
        "- summary: 1-3 plain sentences on what the bill would do and who it affects.\n"
        "- subjects: 0 to 3 DIFFERENT subjects from the list below, best fit first; use an "
        "empty list if none clearly fits (for example a purely honorary resolution). Subjects are "
        "the titles of the Official Code of Georgia: when the caption says it amends 'Title N', "
        "that title's subject is almost always the right first pick. A bill about one city or "
        "county (a local act, charter, or local authority) is 'Local / Municipal'. Fewer is "
        "better; never pad the list.\n"
        "- confidence: 'high' only if the caption plainly states the main change; 'medium' if "
        "it is partly clear; 'low' if it is mostly boilerplate or cut off before the main change.\n\n"
        f"Allowed subjects:\n{subject_guide(allowed, titles or {})}"
    )
    if _AMENDS_ACT_RE.search(bill.get("abstract") or ""):
        prompt += AMENDS_ACT_RULE
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
    only = set(args.only or [])
    if args.amends_act:
        only |= {b["identifier"] for b in bills
                 if b.get("identifier") and _AMENDS_ACT_RE.search(b.get("abstract") or "")}

    def stale(b):
        prev = out["bills"].get(b["identifier"], {})
        return not prev.get("refined") and prev.get("inputHash") != input_hash(b, args.model)

    todo = [b for b in bills
            if b.get("identifier")
            and (not args.session or b.get("session") == args.session)
            and (not only or b["identifier"] in only)
            and (args.include_ceremonial or only or not is_ceremonial(b))
            # naming a bill with --only re-drafts it regardless; --amends-act never
            # overwrites a Claude-refined entry
            and (b["identifier"] in (args.only or []) or
                 (stale(b) if not only else not out["bills"].get(b["identifier"], {}).get("refined")))]
    if args.untagged_first:  # untagged bills are where AI subjects can actually be used
        todo.sort(key=lambda b: bool(b.get("subjects")))
    todo = todo[: args.limit] if args.limit else todo
    titles = code_titles()
    print(f"Drafting {len(todo)} bill(s) with {args.model} (prompt v{PROMPT_VERSION}, "
          f"{len(titles)} code titles)…")
    done = failed = 0
    for i, b in enumerate(todo, 1):
        try:
            res = clean_result(ollama(args.model, b, allowed, titles), allowed)
        except Exception as e:  # keep going; one bad bill shouldn't stop the batch
            failed += 1
            print(f"  ! {b['identifier']}: {e}", file=sys.stderr)
            continue
        out["bills"][b["identifier"]] = {
            **res,
            "session": b.get("session"),
            "source": f"ollama:{args.model}",
            "inputHash": input_hash(b, args.model),
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
    try:  # --output-format json reports errors (e.g. "Not logged in") on stdout, not stderr
        data = json.loads(r.stdout)
    except ValueError:
        data = {}
    if r.returncode != 0 or data.get("is_error"):
        msg = data.get("result") or r.stderr.strip() or "claude exited non-zero"
        raise RuntimeError(msg[:300])
    return data["result"]


def cmd_refine(args):
    bills = {b["identifier"]: b for b in load_json(BILLS_FILE)["bills"] if b.get("identifier")}
    allowed = taxonomy(bills.values())
    # Match curated entries on session too: bill numbers restart each biennium, so a
    # 2023_24 curated "SB 189" is not the 2025_26 SB 189 in ga-bills.json.
    curated = {e["identifier"] for e in (load_json(CURATED_FILE) or {}).get("ga", [])
               if e["identifier"] in bills and bills[e["identifier"]].get("session") == e.get("session")}
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
            "Fix anything the source doesn't support. Keep it SHORT: 2-4 sentences, under 90 words, "
            "covering the main change and who it affects, not every provision. The bill text below "
            "may be cut off at a length limit; if so, summarize what is shown and do not say the text "
            "was unavailable. Return ONLY JSON: "
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
            "inputHash": input_hash(b, "claude-code"),
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
    # Free benchmark: bills that already carry non-AI tags show how good the AI tags are.
    scored = [(v["subjects"], bills[i]["subjects"]) for i, v in ai.items()
              if i in bills and v.get("subjects") and bills[i].get("subjects")
              and bills[i].get("subjectsSource") != "ai"]
    if scored:
        first = sum(a[0] in e for a, e in scored)
        precision = sum(len(set(a) & set(e)) for a, e in scored) / sum(len(a) for a, _ in scored)
        print(f"Tag check vs existing tags on {len(scored)} already-tagged bill(s): first pick "
              f"right {first}/{len(scored)} ({100 * first / len(scored):.0f}%), "
              f"{100 * precision:.0f}% of all AI tags match")
    print("Approve an entry by setting needsReview: false, run `publish` (updates the summaries "
          "/ga-bills shows), commit both files; tags reach ga-bills.json on the next update-ga-bills run.")
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("draft"); d.add_argument("--limit", type=int); d.add_argument("--session"); d.add_argument("--model", default=DEFAULT_MODEL)
    d.add_argument("--only", nargs="+", help="re-draft just these identifiers (even if unchanged), e.g. --only \"HB 1\" \"SB 2\"")
    d.add_argument("--amends-act", action="store_true",
                   help="re-draft only bills whose caption amends an existing Act (the current-law trap)")
    d.add_argument("--untagged-first", action="store_true", help="do bills with no subjects before tagged ones")
    d.add_argument("--include-ceremonial", action="store_true",
                   help="also draft honorary resolutions (commend/condolences/recognize), skipped by default")
    r = sub.add_parser("refine"); r.add_argument("--limit", type=int, default=10); r.add_argument("--only", nargs="+")
    sub.add_parser("status")
    sub.add_parser("publish")
    args = p.parse_args()
    sys.exit({"draft": cmd_draft, "refine": cmd_refine, "status": cmd_status,
              "publish": cmd_publish}[args.cmd](args))


if __name__ == "__main__":
    main()
