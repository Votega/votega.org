"""Former members of Georgia's congressional delegation: the frozen on-site record, the
page URLs, and the wording. The federal counterpart of lib/ga_former.py (decision D12).

`/us-congress/<slug>/` pages are built from current-members.json, so on 2027-01-03 every
member who did not return would lose their page. `scripts/freeze_federal_congress.py` copies
what a page needs into assets/data/federal-congresses/<slug>/ (the live per-Congress files
are replaced or deleted at the turnover); the page builder then builds one page per frozen
member who is no longer in the live roster.

The wording is fact and date only (D6): no "retired", "ousted" or "unseated", and no label
names the winner of a contest the member lost. An approved departure label
(assets/data/federal-departure-labels.json, keyed by bioguideId) is shown verbatim; with
none, the page says only that the member served in the Congress.
"""
import json
import os

from lib.congress_session import congress_years
from lib.ga_legislator_pages import slugify  # the one slug rule (build_entity_pages mirrors it)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FROZEN_ROOT = "assets/data/federal-congresses"
DEFAULT_ROOT = os.path.join(REPO_ROOT, FROZEN_ROOT)
LABELS_PATH = os.path.join(REPO_ROOT, "assets", "data", "federal-departure-labels.json")
PERMALINK = "/us-congress/{}/"

# File names mirror the live files, so the page needs only a different root.
MANIFEST = "freeze.json"
MEMBERS = "current-members.json"
VOTES_INDEX = "federal-votes-index.json"
VOTES_KEYVOTES = "federal-votes-keyvotes.json"
VOTES_DIR = "federal-votes"
UNITY = "federal-party-unity.json"
SPONSOR_INDEX = "federal-sponsorship-index.json"
SPONSOR_DIR = "federal-sponsorship"
CURATED = "curated-federal-bills.json"

OFFICE_END = "January 3, {}"  # a Congress's members' terms end at noon on 3 January


def member_name(m):
    """"First Last" as the page builder derives it: firstName + lastName, else the
    "Last, First" `name` reversed."""
    n = " ".join(x for x in (m.get("firstName"), m.get("lastName")) if x)
    if n:
        return n
    t = m.get("name") or ""
    return " ".join(reversed([p.strip() for p in t.split(",")])) if "," in t else t


def chamber_of(m):
    """Chamber of the member's most recent term (terms run oldest -> newest)."""
    items = (m.get("terms") or {}).get("item") or []
    return (items[-1].get("chamber") or "") if items else ""


def is_senate(m):
    return "senate" in chamber_of(m).lower()


def federal_slug(m):
    """The slug rule of build_entity_pages.build_federal_legislators, before collisions."""
    anchor = "senate" if is_senate(m) else f"ga-{m.get('district')}"
    return slugify(member_name(m), anchor)


def federal_permalink(m):
    return PERMALINK.format(federal_slug(m))


def congress_slug_years(slug):
    """"119th" -> (2025, 2027): the years the Congress sits across, last year being the
    January the terms end."""
    n = int("".join(ch for ch in slug if ch.isdigit()))
    first, second = congress_years(n)
    return first, second + 1


def load_frozen(root=DEFAULT_ROOT):
    """{slug: {"manifest": {...}, "members": {bioguideId: record}}} for every frozen
    Congress under `root` (empty when there is none)."""
    out = {}
    if not os.path.isdir(root):
        return out
    for slug in sorted(os.listdir(root)):
        mpath = os.path.join(root, slug, MANIFEST)
        rpath = os.path.join(root, slug, MEMBERS)
        if not (os.path.isfile(mpath) and os.path.isfile(rpath)):
            continue
        with open(mpath, encoding="utf-8") as f:
            manifest = json.load(f)
        with open(rpath, encoding="utf-8") as f:
            members = json.load(f).get("members") or []
        out[slug] = {"manifest": manifest,
                     "members": {m["bioguideId"]: m for m in members if m.get("bioguideId")}}
    return out


def sitting_ids(live_members):
    """bioguideIds the live roster currently lists as serving. A record flagged
    currentMember: false is NOT sitting, whatever else it carries."""
    return {m["bioguideId"] for m in live_members
            if m.get("bioguideId") and m.get("currentMember") is not False}


def former_records(live_members, frozen):
    """[(record, slug)]: every member of a frozen Congress who is not sitting, from the
    NEWEST Congress that holds them. Sorted by name, then id, for a stable page order."""
    sitting = sitting_ids(live_members)
    newest = {}
    for slug in sorted(frozen, key=lambda s: congress_slug_years(s)[0]):  # later overwrites
        for bid, rec in frozen[slug]["members"].items():
            if bid not in sitting:
                newest[bid] = (rec, slug)
    return [newest[b] for b in sorted(newest, key=lambda b: (member_name(newest[b][0]), b))]


def frozen_urls(frozen):
    """{bioguideId: permalink} every URL a frozen Congress promised, newest Congress wins.
    The manifest's `urls` is what was published at freeze time, so it is authoritative over
    a slug recomputed from a roster whose name may since have changed."""
    out = {}
    for slug in sorted(frozen, key=lambda s: congress_slug_years(s)[0]):
        out.update(frozen[slug]["manifest"].get("urls") or {})
    return out


def load_labels(path=LABELS_PATH):
    """{bioguideId: label record} from the APPROVED labels file; {} when absent or empty.
    Nothing here is drafted: only entries in this file are shown on a page."""
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return (json.load(f).get("labels")) or {}


def departure_sentence(m, slug, label=None):
    """Fact and date only. Without an approved label the sentence says only that the member
    served in the Congress; the label, once approved, supplies the departure."""
    first, end = congress_slug_years(slug)
    where = ("the U.S. Senate" if is_senate(m)
             else f"the U.S. House, Georgia District {m.get('district')}")
    s = f"Served in {where} in the {slug} Congress ({first}–{end})."
    if label:
        s += f" {label.rstrip('.')}."
    return s


def job_title(m):
    return "Former U.S. Senator" if is_senate(m) else "Former U.S. Representative"


def term_end_text(slug):
    return OFFICE_END.format(congress_slug_years(slug)[1])
