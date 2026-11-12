"""Apply a person's counterparty review decisions to the review queue.

The browser tool (tools/counterparty-review-editor.html) writes
_data/counterparty_decisions.json, an append-only log of human decisions. The
generator is the ONLY writer of _data/counterparty_review.yml; this module folds the
log into it. Pure functions, no I/O, so the rules are testable.

Rules:
  * Only a `pending` entry is ever changed. An approved or rejected entry is a
    decision already made; a later log line about it is reported, never applied.
  * Applying is idempotent: replaying the same log yields the same queue.
  * An `aka` (another name for the same organization, e.g. a dba) is recorded only
    when the agenda item text itself states it, and only with a note saying where.
    No aka is the default: absent one, the display name is taken to be the name.
  * A split rejects the original and queues each part as `pending` (a split is not
    an approval), carrying the original's agenda context. A part whose key already
    exists is skipped, never overwritten.
"""

ACTIONS = ("approve", "reject", "edit", "split")
ROLES = ("vendor", "applicant", "other")


def _squash(text):
    return " ".join((text or "").lower().split())


def _norm_key(name, entity_id, normalize):
    return entity_id(normalize(name))


def apply_decisions(review, decisions, entity_id, normalize):
    """Mutate `review` ({key: entry}) in place. Returns (applied, skipped) where each is
    a list of human-readable strings."""
    applied, skipped = [], []
    for i, d in enumerate(decisions or []):
        key = d.get("key")
        action = d.get("action")
        label = f"#{i + 1} {action} {key}"
        if action not in ACTIONS:
            skipped.append(f"{label}: unknown action")
            continue
        entry = review.get(key)
        if entry is None:
            skipped.append(f"{label}: no such entity")
            continue
        if entry.get("status") != "pending":
            # Idempotent replay, or a decision the person already made another way.
            continue

        note = (d.get("note") or "").strip() or None
        name = (d.get("displayName") or "").strip() or None
        role = d.get("role")
        if role is not None and role not in ROLES:
            skipped.append(f"{label}: invalid role {role!r}")
            continue

        akas = []
        if d.get("aka") is not None:
            if action not in ("approve", "edit"):
                skipped.append(f"{label}: aka only goes with approve or edit")
                continue
            akas = [a.strip() for a in d.get("aka") or [] if isinstance(a, str) and a.strip()]
            if akas and not note:
                skipped.append(f"{label}: a note is required when adding an aka")
                continue
            text = _squash(entry.get("itemName"))
            missing = [a for a in akas if _squash(a) not in text]
            if missing:
                skipped.append(f"{label}: aka not stated in the agenda text: {missing}")
                continue

        if action in ("approve", "edit") and name:
            entry["displayName"] = name
        if action in ("approve", "edit") and role:
            entry["role"] = role

        if akas:
            have = list(entry.get("aka") or [])
            entry["aka"] = have + [a for a in akas if a not in have]

        if action == "approve":
            entry["status"] = "approved"
            if note:
                entry["reviewNote"] = note
            applied.append(label)
        elif action == "reject":
            entry["status"] = "rejected"
            entry["reviewNote"] = note or "rejected"
            applied.append(label)
        elif action == "edit":
            if note:
                entry["reviewNote"] = note
            applied.append(label)
        else:  # split
            parts = [p for p in (d.get("parts") or []) if (p.get("displayName") or "").strip()]
            if len(parts) < 2:
                skipped.append(f"{label}: a split needs at least two parts")
                continue
            new_entries, ok = [], True
            for p in parts:
                pname = p["displayName"].strip()
                pkey = _norm_key(pname, entity_id, normalize)
                prole = p.get("role") or entry.get("role")
                if not pkey or prole not in ROLES:
                    skipped.append(f"{label}: bad part {pname!r}")
                    ok = False
                    break
                new_entries.append((pkey, pname, prole))
            if not ok:
                continue
            entry["status"] = "rejected"
            entry["reviewNote"] = note or "split into " + ", ".join(p[1] for p in new_entries)
            for pkey, pname, prole in new_entries:
                if pkey in review:
                    continue
                review[pkey] = {
                    "key": pkey,
                    "status": "pending",
                    "displayName": pname,
                    "role": prole,
                    "date": entry.get("date"),
                    "reference": entry.get("reference"),
                    "itemName": entry.get("itemName"),
                    "reviewNote": "split from " + key,
                }
            applied.append(label)
    return applied, skipped
