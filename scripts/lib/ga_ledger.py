"""Append-only ledger of every page URL each GA legislator has ever had.

Keyed on legisGaGovId (stringified). A person's entry:
    {"rosterId": str, "urls": [{"path": "/ga-legislators/<slug>/", "biennium": "<tag>"}],
     "bienniums": [tag, ...]}
`urls[0]` is the current URL; older ones are kept forever so they can redirect.
Nothing is ever removed: `append_only_violations` is the CI check for that.
"""
import datetime
import json
import os

from lib.atomic_io import write_json_atomic
from lib.ga_legislator_pages import SITE_URL

LEDGER_PATH = "assets/data/ga-legislator-ledger.json"


class LedgerError(Exception):
    pass


def empty_ledger():
    return {"metadata": {"generatedAt": None, "count": 0}, "people": {}}


def load_ledger(path=LEDGER_PATH):
    if not os.path.exists(path):
        return empty_ledger()
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_ledger(ledger, path=LEDGER_PATH, generated_at=None):
    if generated_at is None:
        generated_at = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    ledger["metadata"]["generatedAt"] = generated_at
    ledger["metadata"]["count"] = len(ledger["people"])
    write_json_atomic(path, ledger, sort_keys=True, indent=2)


def _path_of(member):
    url = member.get("votegaUrl")
    gid = member.get("legisGaGovId")
    if not url or gid is None or not url.startswith(SITE_URL):
        return None, None
    return str(gid), url[len(SITE_URL):]


def owner_of(ledger, path):
    for gid, person in ledger["people"].items():
        if any(u["path"] == path for u in person["urls"]):
            return gid
    return None


def current_path(ledger, gid):
    person = ledger["people"].get(str(gid))
    if not person or not person["urls"]:
        return None
    return person["urls"][0]["path"]


def update_ledger(ledger, members, session_tag):
    """Fold the roster into the ledger. Returns human-readable change lines."""
    claims = {}
    for mem in members:
        gid, path = _path_of(mem)
        if gid is None:
            continue
        other = owner_of(ledger, path)
        if other is None:
            other = claims.get(path)
        if other is not None and other != gid:
            raise LedgerError(f"{path} is owned by legisGaGovId {other} but member {gid} claims it")
        claims[path] = gid

    changes = []
    for mem in members:
        gid, path = _path_of(mem)
        if gid is None:
            continue
        person = ledger["people"].get(gid)
        if person is None:
            ledger["people"][gid] = {"rosterId": mem.get("id"),
                                     "urls": [{"path": path, "biennium": session_tag}],
                                     "bienniums": []}
            changes.append(f"new {gid}: {path}")
            continue
        if not person.get("rosterId") and mem.get("id"):
            person["rosterId"] = mem["id"]
        urls = person["urls"]
        if urls and urls[0]["path"] == path:
            continue
        existing = next((u for u in urls if u["path"] == path), None)
        if existing is not None:
            urls.remove(existing)
            urls.insert(0, existing)
            changes.append(f"back {gid}: {path}")
        else:
            old = urls[0]["path"] if urls else None
            urls.insert(0, {"path": path, "biennium": session_tag})
            changes.append(f"rename {gid}: {old} -> {path}")
    return changes


def add_biennium(ledger, gid, tag):
    person = ledger["people"].get(str(gid))
    if person is None:
        raise LedgerError(f"legisGaGovId {gid} has no URL in the ledger; cannot add biennium {tag}")
    if tag not in person["bienniums"]:
        person["bienniums"] = sorted(person["bienniums"] + [tag], reverse=True)


def append_only_violations(old, new):
    out = []
    for gid, op in old["people"].items():
        np_ = new["people"].get(gid)
        if np_ is None:
            out.append(f"person {gid} removed")
            continue
        new_paths = {u["path"] for u in np_["urls"]}
        for u in op["urls"]:
            if u["path"] not in new_paths:
                out.append(f"person {gid}: path {u['path']} removed")
        for b in op.get("bienniums", []):
            if b not in np_.get("bienniums", []):
                out.append(f"person {gid}: biennium {b} removed")
    return out
