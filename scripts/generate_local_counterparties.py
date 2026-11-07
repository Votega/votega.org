#!/usr/bin/env python3
"""Organizations named in a place's agenda items: who has business before the board.

Reads assets/data/local-<slug>-votes.json (elected bodies only), extracts organization
names from item text, and writes assets/data/local-<slug>-counterparties.json.

NOTHING PUBLISHES UNREVIEWED. Every extracted entity not on the stoplist is queued in
_data/counterparty_review.yml as `pending` and left OUT of the output until a person
sets it to `approved`. The script never promotes its own matches, never edits a
decision, and never re-queues one. Organizations only: a capture with no corporate
suffix, organization keyword or initials pattern is treated as a possible private
individual and dropped (counted, never recorded).

    python scripts/generate_local_counterparties.py [--slug dekalb]
"""

import argparse
import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import yaml  # noqa: E402

from lib.atomic_io import write_json_atomic  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOTES_PATH = os.path.join(ROOT, "assets", "data", "local-{slug}-votes.json")
OUT_PATH = os.path.join(ROOT, "assets", "data", "local-{slug}-counterparties.json")
REVIEW_PATH = os.path.join(ROOT, "_data", "counterparty_review.yml")
STOPLIST_PATH = os.path.join(ROOT, "_data", "counterparty_stoplist.yml")

# Allowlist, mirrored in validate_local_officials.ELECTED_BODIES. Never a denylist:
# an unreviewed body (e.g. an appointed Planning Commission) is ignored.
ELECTED_BODIES = {
    "Board of Commissioners",
    "Board of Commissioners - Zoning Meeting",
    "Special Called Meeting",
    "Committee of the Whole",
}

# (regex, role). Longest alternatives first.
LEAD_INS = [
    (r"Applicant/Owner:?", "applicant"),
    (r"Owner/Applicant:?", "applicant"),
    (r"Applicant:", "applicant"),
    (r"Application of", "applicant"),
    (r"Petition of", "applicant"),
    (r"Request of", "other"),
    (r"on behalf of", "other"),
    (r"Awarded to", "vendor"),
    (r"Agreement with", "vendor"),
    (r"Contract with", "vendor"),
]
LEAD_RE = re.compile(
    r"(?:(?<=\W)|^)(" + "|".join(p for p, _ in LEAD_INS) + r")\s+", re.I)
ROLE_BY_LEAD = {re.sub(r"[^a-z]", "", p.lower().replace(":?", "")): r for p, r in LEAD_INS}

SUFFIX_WORDS = (
    r"L\.?L\.?C\.?|Inc\.?|Incorporated|L\.?P\.?|L\.?L\.?P\.?|Corp\.?|Corporation|Company|"
    r"Group|Partners|Holdings|Properties|Builders|Homes|Realty|P\.?C\.?"
)
# A corporate suffix token ends the entity.
SUFFIX_END_RE = re.compile(r"\b(?:" + SUFFIX_WORDS + r")(?=$|[\s,;:)])", re.I)
# Absent a suffix, the capture stops at the first of these.
STOP_RE = re.compile(
    r"\s+(?:to|for|c/o|dba|d/b/a|in the amount|located|at|of the|regarding|pursuant|"
    r"relating|concerning|requesting|seeking|from)\b|,\s+[a-z]|\s+-\s|;|\s\(", re.I)

# Words that mark a no-suffix capture as an organization rather than a person.
ORG_WORDS = re.compile(
    r"\b(?:Associates|Advisory|Consulting|Services|Systems|Solutions|Technolog\w*|"
    r"Construction|Engineering|Contractors?|Development|Enterprises|Investments?|"
    r"Center|Church|Foundation|Authority|Association|Institute|University|College|"
    r"Trucks?|Industries|International|Management|Associates|Architects?|Design|"
    r"Landscap\w+|Paving|Electric\w*|Security|Software|Health|Hospital|Bank|"
    r"Insurance|Capital|Ventures|Labs?|Studio|Supply|Equipment|Motors?)\b", re.I)
INITIALS_RE = re.compile(r"\b[A-Z]\.[A-Z]\.")

SUFFIX_CAPTURE_RE = re.compile(
    r"((?:[A-Z0-9][\w&'.\-]*(?:\s+|,\s*)){0,7}?(?:" + SUFFIX_WORDS + r"))(?=$|[\s,;:)])")

BARE_TAIL_RE = re.compile(r"\s+(?:c|co)$", re.I)


def normalize(name):
    s = name.lower()
    s = re.sub(r"[.,'\"()]", " ", s)
    s = s.replace("&", " and ")
    s = SUFFIX_END_RE.sub(" ", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def entity_id(norm):
    return re.sub(r"\s+", "-", norm)


def trim_entity(raw):
    """Right-boundary trim: end at the first corporate suffix, else at the first
    clause boundary."""
    raw = raw.strip()
    early = re.search(r"\s+(?:c/o|dba|d/b/a)(?=\s|$)", raw, re.I)
    if early:
        raw = raw[:early.start()]
    m = SUFFIX_END_RE.search(raw)
    if m:
        return raw[:m.end()].strip(" ,;:")
    m = STOP_RE.search(raw)
    if m:
        raw = raw[:m.start()]
    raw = BARE_TAIL_RE.sub("", raw)
    return raw.strip(" ,;:")


# Text before the entity that belongs to the surrounding sentence, not the name.
LEADING_JUNK_RE = re.compile(
    r"^(?:Traded To|Commission District \d+|Super District \d+|Amount Not|"
    r"Exceeding|Not to Exceed)\s+", re.I)
SENTENCE_BREAK_RE = re.compile(r"(?:[.:;)]\s+|\d{4}\.\s*)(?=[A-Z0-9])")


def clean_entity(ent):
    """Drop sentence residue around a suffix-pass capture; None if it is not one
    organization (a list, a clause, a lone place name)."""
    parts = SENTENCE_BREAK_RE.split(ent)
    ent = parts[-1] if len(parts) > 1 and has_suffix(parts[-1]) else ent
    ent = re.sub(r"\.\s+(?:Amount|Not|Exceeding)(?=\s|$).*$", "", ent)
    ent = re.sub(r"^(?:(?:Commission |Super )?Districts?\s+\d+\s+|All Districts\s+|\d{4}-\d+-[A-Z]+\s+|\d+\s+)+",
                 "", ent)
    for _ in range(3):
        ent = LEADING_JUNK_RE.sub("", ent)
    ent = ent.strip(" ,;:")
    if re.match(r"^\d+\s+[A-Za-z]{2,}\b", ent) and not re.match(r"^\d+\s+[A-Z]", ent):
        return None
    if ent.count(",") >= 2 or "(" in ent and ")" not in ent or ent.count(")") > ent.count("("):
        return None
    if len(ent.split()) > 9:
        return None
    return ent or None


def has_suffix(s):
    return bool(SUFFIX_END_RE.search(s))


def looks_like_org(s):
    return has_suffix(s) or bool(ORG_WORDS.search(s)) or bool(INITIALS_RE.search(s))


def load_stoplist():
    try:
        with open(STOPLIST_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        return [], []
    prefixes, patterns = [], []
    for e in data.get("stoplist") or []:
        if e.get("prefix"):
            prefixes.append(e["prefix"].lower())
        if e.get("pattern"):
            patterns.append(e["pattern"].lower())
    return prefixes, patterns


def stopped(name, prefixes, patterns):
    low = name.lower()
    return any(low.startswith(p) for p in prefixes) or any(p in low for p in patterns)


def extract(item_name, prefixes, patterns):
    """-> list of (displayName, role) for one agenda item; dict of drop counters."""
    found, dropped = [], 0
    text = " ".join((item_name or "").split())
    for m in LEAD_RE.finditer(text):
        lead_key = re.sub(r"[^a-z]", "", m.group(1).lower())
        role = ROLE_BY_LEAD.get(lead_key, "other")
        ent = clean_entity(re.split(r":\s", trim_entity(text[m.end():m.end() + 160]))[0])
        if not ent or len(ent) < 3:
            continue
        if stopped(ent, prefixes, patterns):
            continue
        if not looks_like_org(ent):
            dropped += 1  # possible private individual: never recorded
            continue
        found.append((ent, role))
    # Suffix pass runs on the text with lead-in phrases removed, so a leaked
    # "Awarded to X" cannot become part of X.
    rest = LEAD_RE.sub(" ", text)
    for m in SUFFIX_CAPTURE_RE.finditer(rest):
        ent = clean_entity(m.group(1).strip(" ,;:"))
        if not ent or len(ent) < 3 or stopped(ent, prefixes, patterns):
            continue
        if any(normalize(ent) == normalize(e) for e, _ in found):
            continue
        found.append((ent, "other"))
    return found, dropped


def load_review():
    try:
        with open(REVIEW_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        data = {}
    return {e["key"]: e for e in (data.get("entities") or []) if e.get("key")}


def write_review(entities):
    header = (
        "# Counterparty review queue — written by scripts/generate_local_counterparties.py.\n"
        "# A person sets `status` to approved | rejected. The script never edits a decision,\n"
        "# never re-queues one, and publishes ONLY `approved` entities. Each pending entry\n"
        "# carries the agenda item it came from so it can be judged without the votes file.\n"
    )
    body = yaml.safe_dump({"entities": entities}, sort_keys=False, allow_unicode=True,
                          width=100)
    new = header + body
    try:
        with open(REVIEW_PATH, encoding="utf-8", newline="") as f:
            if f.read().replace("\r\n", "\n") == new:
                return False
    except FileNotFoundError:
        pass
    with open(REVIEW_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write(new)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", default="dekalb")
    args = ap.parse_args()

    vpath = VOTES_PATH.format(slug=args.slug)
    try:
        with open(vpath, encoding="utf-8") as f:
            votes = json.load(f)
    except (FileNotFoundError, ValueError) as e:
        print(f"ERROR: cannot read {vpath}: {e}")
        sys.exit(1)

    prefixes, patterns = load_stoplist()
    review = load_review()

    scanned = with_entity = dropped_individuals = 0
    grouped = {}  # key -> {display, aliases, roles, items}
    for meeting in votes.get("meetings") or []:
        if meeting.get("body") not in ELECTED_BODIES:
            continue
        for item in meeting.get("items") or []:
            scanned += 1
            ents, dropped = extract(item.get("name"), prefixes, patterns)
            dropped_individuals += dropped
            if not ents:
                continue
            with_entity += 1
            for ent, role in ents:
                key = entity_id(normalize(ent))
                if not key:
                    continue
                g = grouped.setdefault(key, {"display": ent, "aliases": [], "roles": [],
                                             "items": []})
                if ent not in g["aliases"]:
                    g["aliases"].append(ent)
                g["roles"].append(role)
                g["items"].append({
                    "meetingId": str(meeting.get("id")),
                    "date": meeting.get("date"),
                    "body": meeting.get("body"),
                    "reference": item.get("reference"),
                    "itemName": " ".join((item.get("name") or "").split()),
                    "motionIndex": 0,
                })

    def role_of(g):
        non_other = [r for r in g["roles"] if r != "other"]
        pool = non_other or g["roles"]
        return max(set(pool), key=pool.count)

    # Queue anything new; never touch an existing decision.
    queued = 0
    for key, g in sorted(grouped.items()):
        if key in review:
            continue
        first = g["items"][0]
        review[key] = {
            "key": key,
            "status": "pending",
            "displayName": g["display"],
            "role": role_of(g),
            "date": first["date"],
            "reference": first["reference"],
            "itemName": first["itemName"],
        }
        queued += 1
    entities_sorted = [review[k] for k in sorted(review)]
    review_changed = write_review(entities_sorted)

    approved = []
    for key, g in sorted(grouped.items()):
        entry = review.get(key)
        if not entry or entry.get("status") != "approved":
            continue
        approved.append({
            "entityId": key,
            "displayName": entry.get("displayName") or g["display"],
            "normalized": normalize(g["display"]),
            "aliases": sorted(g["aliases"]),
            "role": entry.get("role") or role_of(g),
            "items": g["items"],
        })
    pending = sum(1 for e in review.values() if e.get("status") == "pending")

    out = {
        "metadata": {
            "generatedAt": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": f"assets/data/local-{args.slug}-votes.json",
            "bodies": sorted(ELECTED_BODIES),
            "itemsScanned": scanned,
            "itemsWithEntity": with_entity,
            "entitiesApproved": len(approved),
            "entitiesPending": pending,
            "possibleIndividualsSkipped": dropped_individuals,
        },
        "counterparties": approved,
    }
    opath = OUT_PATH.format(slug=args.slug)
    try:
        with open(opath, encoding="utf-8") as f:
            prev = json.load(f)
        a = {**prev.get("metadata", {}), "generatedAt": None}
        b = {**out["metadata"], "generatedAt": None}
        if a == b and prev.get("counterparties") == approved:
            out["metadata"]["generatedAt"] = prev["metadata"]["generatedAt"]
    except (FileNotFoundError, ValueError):
        pass
    write_json_atomic(opath, out, indent=2)

    print(f"{args.slug}: scanned {scanned} items, {with_entity} with an entity, "
          f"{queued} newly queued, {pending} pending, {len(approved)} approved, "
          f"{dropped_individuals} possible individuals skipped"
          f"{' (review file updated)' if review_changed else ''}")


if __name__ == "__main__":
    main()
