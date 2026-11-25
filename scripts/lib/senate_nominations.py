#!/usr/bin/env python3
"""What a Senate roll call's XML says about nominations.

Each Senate vote carries two fields: `documentType` (the first <document>'s type,
e.g. "PN", "S.", "S.Amdt."; null when absent) and `nomineeCount` (the number of
nomination documents; null when the vote is not on a nomination, or when it came
from Voteview, which cannot say).

An en bloc roll call is one vote on many nominees and carries one <document> per
nomination. Those lists go to a side file, federal-en-bloc-nominees.json:

    batches  {batchId: [{pn, name, state, position, title}]}
    votes    {voteId: batchId}     votes share a batch only with identical PN sets
    pending  [voteId]              en bloc, but no complete list yet (Voteview rows)

A list is complete or absent, never partial. The file describes one Congress.

Used by generate_federal_votes_data.py, backfill_federal_nomination_fields.py and
validate_federal_votes.py. Stdlib only.
"""
import hashlib
import re
from datetime import datetime, timezone

NOMINEES_FILE = "federal-en-bloc-nominees.json"
SOURCE = "Senate.gov roll-call XML, one <document> per nomination"

#: The stored title of an en bloc row Voteview supplied: it has no reliable count.
EN_BLOC_TITLE = "En bloc"

_TITLE = re.compile(r"^(?P<name>.+?), of (?P<state>.+?), to be (?P<position>.+)$")
#: Voteview joins an en bloc vote's nominees as "A, of X, to be ...; and B, of Y, to be ...".
_SECOND_NOMINEE = re.compile(r"; and [^;]+?, of [^;]+?, to be ")


def _text(element, tag):
    return re.sub(r"\s+", " ", (element.findtext(tag) or "")).strip() or None


def parse_title(title):
    """(name, state, position) from "name, of state, to be position", or three Nones.
    "the District of Columbia" loses its article; the source title is kept beside it."""
    m = _TITLE.match(title or "")
    if not m:
        return None, None, None
    return m["name"], re.sub(r"^the ", "", m["state"]), m["position"]


def _nomination_documents(root):
    return [d for d in root.findall("./document") if _text(d, "document_type") == "PN"]


def nomination_fields(root):
    """(documentType, nomineeCount) for a parsed roll call."""
    first = root.find("./document")
    doc_type = _text(first, "document_type") if first is not None else None
    if doc_type != "PN":
        return doc_type, None
    docs = _nomination_documents(root)
    numbers = [_text(d, "document_number") for d in docs]
    # A repeated number is one nomination; an unnumbered document still counts.
    unique = len(set(n for n in numbers if n)) + sum(1 for n in numbers if not n)
    return doc_type, unique


def nominees(root):
    """The complete nominee list of an en bloc roll call, in source order. None for a
    single nomination or anything else, and None if any document lacks a PN number."""
    docs = _nomination_documents(root)
    if len(docs) < 2:
        return None
    out = {}
    for d in docs:
        number = _text(d, "document_number")
        if not number:
            return None
        title = _text(d, "document_title")
        name, state, position = parse_title(title)
        out.setdefault(number, {"pn": "PN" + number, "name": name, "state": state,
                                "position": position, "title": title})
    return list(out.values()) if len(out) > 1 else None


def en_bloc_label(count, first_title):
    """"En bloc: 48 nominations, including Jessica Kramer"."""
    label = f"En bloc: {count} nominations"
    first = parse_title(first_title)[0] or (first_title or "").split(",")[0].strip()
    return f"{label}, including {first}" if first else label


def is_en_bloc_description(description):
    """True when a Voteview description names more than one nominee."""
    return bool(_SECOND_NOMINEE.search(description or ""))


def lists_from_doc(doc):
    """{voteId: list, or None when pending} from an existing nominee file."""
    doc = doc or {}
    batches = doc.get("batches") or {}
    out = {vote_id: None for vote_id in doc.get("pending") or []}
    for vote_id, batch_id in (doc.get("votes") or {}).items():
        if batch_id in batches:
            out[vote_id] = batches[batch_id]
    return out


def batch_id(entries):
    key = "|".join(sorted(e["pn"] for e in entries))
    return "b" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]


def build_nominees_doc(votes, lists, provisional, congress, previous=None, now=None):
    """The side file for `votes` (the monolith's, one Congress).

    `lists` is {voteId: list or None}; ids not in `votes` are ignored, which is what
    empties the file at a Congress turnover. `previous` is the file being replaced:
    when nothing but the stamp would change, its generatedAt is kept, so a quiet run
    leaves the file byte-identical.
    """
    batches, mapping, pending = {}, {}, []
    for vote_id in sorted(votes):
        meta = votes[vote_id]
        if meta.get("chamber") != "Senate":
            continue
        if vote_id in provisional:
            if meta.get("title") == EN_BLOC_TITLE:
                pending.append(vote_id)
            continue
        if (meta.get("nomineeCount") or 0) < 2 or vote_id not in lists:
            continue  # a list that has gone missing is left for the validator to report
        entries = lists[vote_id]
        if entries is None:
            pending.append(vote_id)
            continue
        key = batch_id(entries)
        batches.setdefault(key, entries)
        mapping[vote_id] = key
    doc = {
        "metadata": {
            "congress": congress,
            "generatedAt": (now or datetime.now(timezone.utc)).isoformat(),
            "count": sum(len(b) for b in batches.values()),
            "source": SOURCE,
        },
        "batches": batches,
        "votes": mapping,
        "pending": pending,
    }
    if previous:
        old = previous.get("metadata") or {}
        stamped = dict(doc, metadata=dict(doc["metadata"], generatedAt=old.get("generatedAt")))
        if stamped == previous:
            return previous
    return doc


def problems(votes_doc, nominees_doc):
    """Why the monolith and the nominee file contradict each other. Empty = sound."""
    votes = votes_doc.get("votes") or {}
    meta = votes_doc.get("metadata") or {}
    provisional = set(meta.get("senateRollsFromVoteview") or [])
    side = nominees_doc.get("metadata") or {}
    batches = nominees_doc.get("batches")
    mapping = nominees_doc.get("votes")
    pending = nominees_doc.get("pending")
    if not isinstance(batches, dict) or not isinstance(mapping, dict) or not isinstance(pending, list):
        return ["nominee file lacks batches, votes or pending"]
    errors = []
    if side.get("congress") != meta.get("congress"):
        errors.append(f"nominee file describes Congress {side.get('congress')}, "
                      f"the votes describe {meta.get('congress')}")
    count = sum(len(b) for b in batches.values())
    if side.get("count") != count:
        errors.append(f"nominee file metadata.count is {side.get('count')!r} but holds {count}")

    unfielded = sorted(k for k, v in votes.items() if v.get("chamber") == "Senate"
                       and not ("documentType" in v and "nomineeCount" in v))
    if unfielded:
        errors.append(f"{len(unfielded)} Senate row(s) lack documentType/nomineeCount (run "
                      f"scripts/backfill_federal_nomination_fields.py), e.g. {unfielded[:3]}")

    seen = {}
    for key, entries in batches.items():
        pns = [e.get("pn") for e in entries]
        if not pns or len(set(pns)) != len(pns) or not all(pns):
            errors.append(f"batch {key}: empty, or a PN number missing or repeated")
        other = seen.setdefault(frozenset(pns), key)
        if other != key:
            errors.append(f"batches {other} and {key} hold the same PN numbers")
    unused = sorted(set(batches) - set(mapping.values()))
    if unused:
        errors.append(f"batch(es) no vote uses: {unused[:3]}")

    for vote_id, key in sorted(mapping.items()):
        row = votes.get(vote_id)
        if row is None or key not in batches:
            errors.append(f"{vote_id}: unknown roll call or missing batch {key!r}")
        elif vote_id in provisional:
            errors.append(f"{vote_id}: a Voteview row must not have a nominee list")
        elif row.get("nomineeCount") != len(batches[key]):
            errors.append(f"{vote_id}: nomineeCount {row.get('nomineeCount')} but the list "
                          f"holds {len(batches[key])}")
    stray = sorted(v for v in pending if v not in votes or v in mapping)
    if stray:
        errors.append(f"pending names unknown or already-listed roll call(s): {stray[:3]}")
    lost = sorted(k for k, v in votes.items() if (v.get("nomineeCount") or 0) > 1
                  and k not in mapping and k not in pending)
    if lost:
        errors.append(f"{len(lost)} en bloc roll call(s) have no nominee list and are not "
                      f"pending, e.g. {lost[:3]}")
    return errors
