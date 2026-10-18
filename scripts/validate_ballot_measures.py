#!/usr/bin/env python3
"""
Validate assets/data/ga-ballot-measures.json against its schema, and check that
every `explainer` link still points at a heading that exists.

The second check is the reason this script exists. A measure's explainer URL
carries a #fragment into a post heading, and Jekyll derives those ids from the
heading text -- so rewording "Nonpartisan Elections for Probate Judges" silently
turns a voter-facing "What a yes or no vote means" link into a jump to the top of
the post. Nothing else would notice: the link still resolves, the page still
loads, and the one thing the voter wanted is what they do not get.

Usage:
    python scripts/validate_ballot_measures.py          # exit 1 on any problem

Run from the repo root. Checks:
  * the data validates against ga-ballot-measures.schema.json (if jsonschema is
    installed; otherwise the enum/required/extra-key subset by hand)
  * every explainer URL's path resolves to a post or page in the working tree
  * every explainer #fragment matches a heading id that page will generate
  * lifecycle sanity: a measure with results must be terminal, and a measure
    that is not on the ballot must not be presented as pending
"""
import json
import os
import re
import sys

DATA = "assets/data/ga-ballot-measures.json"
SCHEMA = "assets/data/ga-ballot-measures.schema.json"

ON_BALLOT = ("certified", "passed", "failed")


def heading_id(text):
    """Reproduce kramdown's automatic heading id.

    Lowercase, drop anything that is not a word character, space or hyphen, then
    collapse whitespace to single hyphens. Verified against the ids in the built
    site for the 2026 explainer post, including "1. Next Generation 9-1-1 Fund"
    -> "1-next-generation-9-1-1-fund".
    """
    text = re.sub(r"`([^`]*)`", r"\1", text)                 # inline code
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)      # links -> label
    text = re.sub(r"[*_]", "", text)                          # emphasis
    text = text.strip().lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    return text.strip("-")


def headings_of(path):
    """Every heading id a markdown file will generate, plus explicit {#id}s."""
    ids = set()
    with open(path, encoding="utf-8") as fh:
        in_front_matter = False
        for i, line in enumerate(fh):
            if i == 0 and line.strip() == "---":
                in_front_matter = True
                continue
            if in_front_matter:
                if line.strip() == "---":
                    in_front_matter = False
                continue
            m = re.match(r"\s{0,3}(#{1,6})\s+(.*?)\s*$", line)
            if not m:
                continue
            text = m.group(2)
            explicit = re.search(r"\{#([\w-]+)\}\s*$", text)
            if explicit:
                ids.add(explicit.group(1))
                text = text[: explicit.start()]
            ids.add(heading_id(text))
    return ids


def find_source(url_path):
    """Map a site-relative URL to the markdown/HTML source that produces it."""
    slug = url_path.strip("/")
    if not slug:
        return "index.html" if os.path.exists("index.html") else None
    # A post URL is its slug; the file carries a date prefix.
    for name in os.listdir("_posts"):
        if name.endswith((".md", ".markdown", ".html")):
            stem = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", os.path.splitext(name)[0])
            if slug in (stem, f"{stem}/") or slug.endswith(stem):
                return os.path.join("_posts", name)
    for cand in (f"{slug}.html", f"{slug}.md", f"{slug}/index.html"):
        if os.path.exists(cand):
            return cand
    return None


def main():
    problems = []
    with open(DATA, encoding="utf-8") as fh:
        data = json.load(fh)
    with open(SCHEMA, encoding="utf-8") as fh:
        schema = json.load(fh)

    try:
        import jsonschema
        try:
            jsonschema.validate(data, schema)
            print("schema: valid")
        except jsonschema.ValidationError as e:
            problems.append(f"schema: {e.message} at {list(e.absolute_path)}")
    except ImportError:
        mdef = schema["$defs"]["measure"]
        allowed, required = set(mdef["properties"]), mdef["required"]
        enum = mdef["properties"]["status"]["enum"]
        for m in data["measures"]:
            if m.get("status") not in enum:
                problems.append(f"{m.get('id')}: status {m.get('status')!r} not in {enum}")
            for k in required:
                if k not in m:
                    problems.append(f"{m.get('id')}: missing required {k}")
            for k in set(m) - allowed:
                problems.append(f"{m.get('id')}: unknown key {k}")
        print("schema: jsonschema not installed — checked enum/required/extra keys only")

    checked = 0
    for m in data["measures"]:
        ex = m.get("explainer")
        if not ex or not ex.get("url"):
            continue
        checked += 1
        url = ex["url"]
        path, _, frag = url.partition("#")
        src = find_source(path)
        if src is None:
            problems.append(f"{m['id']}: explainer path {path!r} matches no post or page")
            continue
        if frag:
            ids = headings_of(src)
            if frag not in ids:
                problems.append(
                    f"{m['id']}: explainer anchor #{frag} is not a heading in {src}. "
                    f"A heading was probably reworded; available: {sorted(ids)}")

    # Editorial policy, enforced rather than documented. See about-the-data.md.
    # These are the rules that keep a reading list from drifting into advocacy;
    # a reviewer cannot be relied on to notice a single bad entry years later.
    AI_GENERATED_HOSTS = ("cpo.soar.com",)   # self-flagged as possibly inaccurate
    for m in data["measures"]:
        for src in m.get("sources") or []:
            url = src.get("url", "")
            for host in AI_GENERATED_HOSTS:
                if host in url:
                    problems.append(
                        f"{m['id']}: source {url} is from {host}, whose articles are AI-generated "
                        f"and self-flagged as possibly inaccurate — not citable")
            if not url.startswith(("http://", "https://", "/")):
                problems.append(f"{m['id']}: source url {url!r} is neither absolute nor site-relative")
        kinds = [s.get("kind") for s in m.get("sources") or []]
        if m.get("status") in ON_BALLOT and m.get("sources") and "official" not in kinds:
            problems.append(
                f"{m['id']}: a measure on the ballot must cite at least one 'official' source, "
                f"so the reading list is anchored to the state's own material (kinds: {kinds})")
        # Silence about opposition is the failure mode: a voter cannot tell
        # whether none exists or nobody looked.
        if m.get("status") in ON_BALLOT and "oppose" not in kinds and not m.get("opposition"):
            problems.append(
                f"{m['id']}: no 'oppose' source and no `opposition` note — say what was found when "
                f"looking for organised opposition, including that none was identified")

    for m in data["measures"]:
        if m.get("results") and m.get("status") not in ("passed", "failed"):
            problems.append(f"{m['id']}: carries results but status is {m.get('status')!r}")
        if m.get("status") == "not-on-ballot" and not m.get("statusNote"):
            problems.append(f"{m['id']}: not-on-ballot measures must explain why in statusNote")

    counts = {s: sum(1 for m in data["measures"] if m.get("status") == s)
              for s in ("certified", "potential", "not-on-ballot")}
    md = data.get("metadata", {})
    for key, status in (("certifiedCount", "certified"),
                        ("potentialCount", "potential"),
                        ("notOnBallotCount", "not-on-ballot")):
        if key in md and md[key] != counts[status]:
            problems.append(f"metadata.{key} is {md[key]} but {counts[status]} measures are {status}")

    if problems:
        print(f"\nFAIL — {len(problems)} problem(s):", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print(f"explainer links: {checked} checked, all anchors resolve")
    print(f"counts: {counts} — consistent with metadata")
    print(f"OK — {len(data['measures'])} measures — {DATA}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
