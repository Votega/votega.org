#!/usr/bin/env python3
"""Build consumer-friendly bill artifacts for the Votega/ga-legislation repo.

Source: assets/data/ga-bills.json (+ ga-bills-subjects.json overrides).
Artifacts (repo root, matching ga-legislation's layout):
  ga-bills.json            Passthrough
  ga-bills-subjects.json   Passthrough (manual subject overrides)
  ga-bills.csv             One row per bill (flattened) — for spreadsheets
  ga-bills.schema.json     JSON Schema for ga-bills.json
  BILLS.md                 Overview: counts by chamber, status, type, and top subjects

latest.json also lists every EARLIER General Assembly under `earlierBienniums`, read from
the frozen files scripts/freeze_ga_bills.py writes (assets/data/ga-bienniums/<tag>/). Their
session folders were published while they were current and are never rewritten here, so
without this index a rollover would leave them in the repo with nothing pointing to them.

Writes artifacts only; the workflow commits them. Dry-run to $OUT_DIR standalone.
"""
import csv
import glob
import io
import json
import os
from collections import Counter

from lib.ga_sessions import (ACTIVE_SESSION, BIENNIUM, all_session_ids,
                             session_name, session_slug, tag_session)
from lib.sibling_publish import add_dataset_manifest, build_json, publish_or_dry_run
import validate_ga_bills

REPO = "Votega/ga-legislation"
TOKEN_ENV = "GA_BILLS_TOKEN"

SRC_JSON = "assets/data/ga-bills.json"
SRC_SUBJECTS = "assets/data/ga-bills-subjects.json"
FROZEN_GLOB = "assets/data/ga-bienniums/*/ga-bills.json"

CHAMBER_LABEL = {"lower": "House", "upper": "Senate"}

RAW_BASE = "https://raw.githubusercontent.com/Votega/ga-legislation/main"
#: Bumped on a change a consumer must act on; adding optional properties is a minor bump.
SCHEMA_VERSION = "1.1.0"
SCHEMA_STABILITY = (
    "Stable field names and meanings. 1.1.0 describes fields added in 2026-11, all "
    "optional and absent from files published before then: legislationType, footnotes, "
    "committees, committeeHistory, statusHistory, stage, passageVotes[].time and "
    "passageVotes[].linkedBy on each bill, and metadata.legislativeCalendar. Nothing "
    "new is `required`, so older copies still validate. `status` is legis.ga.gov's "
    "latest action, not an outcome (a vetoed bill's reads 'Date Signed by Governor'): "
    "read governorAction or stage for the outcome. committeeHistory records moves seen "
    "between publisher runs from the 2027 session on; it is empty before then.")


def schema_url(path):
    """The $id for a schema published at `path`: each file declares the path it
    actually lives at (docs/conventions-publishing.md). Every session's
    bills.schema.json used to claim one hardcoded root URL that no file occupies."""
    return f"{RAW_BASE}/{path}"


def compact_json(obj):
    """Compact UTF-8 JSON bytes for the large per-session bills.json (pretty-printing
    the ~9 MB regular-session file would roughly double it)."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode()


def session_files(slug, with_subjects=True):
    """The files a session folder holds, by role. One definition for every biennium."""
    base = f"sessions/{slug}"
    files = {"bills": f"{base}/bills.json", "billsCsv": f"{base}/bills.csv",
             "schema": f"{base}/bills.schema.json", "summary": f"{base}/BILLS.md"}
    if with_subjects:
        files["subjects"] = f"{base}/bills-subjects.json"
    return files


def earlier_bienniums(pattern=FROZEN_GLOB, current=BIENNIUM):
    """Index entries for every frozen General Assembly other than the current one.

    Reads only what the freeze recorded; writes nothing for these bienniums. A frozen
    file for the CURRENT biennium (frozen early, before the rollover) is not earlier and
    is skipped. A frozen file that cannot be read, or is not marked frozen, refuses the
    publish rather than silently dropping a General Assembly from the index.
    """
    out = []
    for path in sorted(glob.glob(pattern)):
        try:
            with open(path, encoding="utf-8") as fh:
                meta = json.load(fh).get("metadata") or {}
        except (OSError, ValueError) as exc:
            raise SystemExit(f"refusing to publish: cannot read frozen bills {path}: {exc}")
        if not meta.get("frozen") or not meta.get("biennium"):
            raise SystemExit(f"refusing to publish: {path} is not a frozen bills file")
        if meta["biennium"] == current:
            continue
        sessions = [{"id": s["id"], "name": s.get("name") or session_name(s["id"]),
                     "slug": session_slug(s["id"]), "billCount": s.get("billCount"),
                     "files": session_files(session_slug(s["id"]))}
                    for s in meta.get("sessions") or []]
        out.append({"biennium": meta["biennium"], "frozenAt": meta.get("frozenAt"),
                     "billCount": meta.get("totalBills"),
                     "sessions": sorted(sessions, key=lambda s: s["slug"])})
    return sorted(out, key=lambda b: b["biennium"], reverse=True)


def _committee_name(bill, chamber):
    for c in bill.get("committees") or []:
        if c.get("chamber") == chamber:
            return c.get("name")
    return None


def bills_csv(bills):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    # New columns are APPENDED, never inserted, so positional readers keep working.
    w.writerow(["identifier", "billType", "chamber", "title", "status", "statusDate",
                "subjects", "primarySponsors", "sponsorCount", "billUrl",
                "secondChamberSponsor", "legislationType", "stage",
                "houseCommittee", "senateCommittee"])
    for b in bills:
        sponsors = b.get("sponsors") or []
        primary = [s.get("name") for s in sponsors if s.get("primary")]
        w.writerow([
            b.get("identifier"), b.get("billType"),
            CHAMBER_LABEL.get(b.get("chamber"), b.get("chamber")),
            b.get("title"), b.get("status"), b.get("statusDate"),
            "; ".join(b.get("subjects") or []),
            "; ".join(primary), len(sponsors), b.get("billUrl"),
            (b.get("secondChamberSponsor") or {}).get("name"),
            b.get("legislationType"),
            (b.get("stage") or {}).get("label"),
            _committee_name(b, "lower"), _committee_name(b, "upper"),
        ])
    return buf.getvalue().encode()


def bills_md(doc):
    bills = doc.get("bills", [])
    meta = doc.get("metadata", {})
    by_chamber = Counter(CHAMBER_LABEL.get(b.get("chamber"), b.get("chamber") or "?") for b in bills)
    by_type = Counter(b.get("billType") or "?" for b in bills)
    by_status = Counter(b.get("status") or "?" for b in bills)
    subjects = Counter(s for b in bills for s in (b.get("subjects") or []))

    L = ["# Georgia Bills", ""]
    L.append("_Auto-generated from [votega.org](https://votega.org) — do not edit by hand._  ")
    L.append(f"_Last updated {meta.get('generatedAt', '')} · {len(bills)} bills · "
             f"{meta.get('sessionName', '')}._")
    L.append("")
    L.append("> Full data in this session folder: [`bills.json`](bills.json) (richest — sponsors, "
             "votes, links) or [`bills.csv`](bills.csv) (one row per bill, for spreadsheets).")
    L.append("")

    def table(title, counter, cols=("Value", "Bills"), limit=None):
        out = [f"## {title}", "", f"| {cols[0]} | {cols[1]} |", "|---|---|"]
        items = counter.most_common(limit) if limit else sorted(counter.items())
        for k, n in items:
            out.append(f"| {k} | {n} |")
        out.append("")
        return out

    L += table("By chamber", by_chamber, ("Chamber", "Bills"))
    L += table("By type", by_type, ("Type", "Bills"))
    L += table("By status", by_status, ("Status", "Bills"), limit=15)
    L += table("Top subjects", subjects, ("Subject", "Bills"), limit=20)
    return ("\n".join(L) + "\n").encode()


_COMMITTEE = {"type": "object", "properties": {
    "chamber": {"type": "string", "enum": ["lower", "upper"]},
    "id": {"type": "integer", "description": "legis.ga.gov committee id (GetCommitteesBySession)."},
    "code": {"type": ["string", "null"]}, "name": {"type": ["string", "null"]}}}


def schema(path=None):
    path = path or session_files(session_slug(ACTIVE_SESSION))["schema"]
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": schema_url(path),
        "schemaVersion": SCHEMA_VERSION,
        "schemaStability": SCHEMA_STABILITY,
        "title": "Georgia Bills",
        "description": "Bills and resolutions from the Georgia General Assembly, sourced from its "
                       "own web service at legis.ga.gov (topical subject tags originate from "
                       "Open States), enriched with party vote tallies where available.",
        "type": "object",
        "required": ["metadata", "bills"],
        "properties": {
            "metadata": {"type": "object", "properties": {
                "session": {"type": "string", "description": "Session id, e.g. 2025_26, 2026_ss."},
                "sessionName": {"type": ["string", "null"]},
                "biennium": {"type": "string", "description": "e.g. 2025-2026."},
                "generatedAt": {"type": ["string", "null"], "description": "When the source file was generated (ISO 8601)."},
                "source": {"type": "string"},
                "totalBills": {"type": "integer"},
                "legislativeCalendar": {
                    "type": "object",
                    "description": "This session's legislative days per chamber, from legis.ga.gov "
                                   "GetSessionSchedule: {\"lower\": [[day, \"YYYY-MM-DD\"], ...], "
                                   "\"upper\": [...]}, by date. A regular session numbers days 1-40 in "
                                   "EACH year (day 28 = Crossover Day; day 40 of the second year = sine "
                                   "die); a special session 1-N.",
                    "properties": {c: {"type": "array", "items": {
                        "type": "array", "prefixItems": [{"type": "integer"}, {"type": "string"}]}}
                        for c in ("lower", "upper")}},
            }},
            "bills": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["id", "identifier", "title"],
                    "properties": {
                        "id": {"type": "string", "description": "Bill id in the form "
                               "\"gga-bill/<legislationId>\", where legislationId is the "
                               "legis.ga.gov id used in billUrl."},
                        "identifier": {"type": "string", "description": "e.g. 'HB 1', 'SB 264'."},
                        "billType": {"type": ["string", "null"], "description": "e.g. bill, resolution."},
                        "chamber": {"type": ["string", "null"], "enum": ["lower", "upper", None],
                                    "description": "'lower' = House, 'upper' = Senate."},
                        "title": {"type": "string"},
                        "abstract": {"type": ["string", "null"]},
                        "status": {"type": ["string", "null"]},
                        "statusDate": {"type": ["string", "null"]},
                        "subjects": {"type": "array", "items": {"type": "string"}},
                        "sponsors": {"type": "array", "items": {
                            "type": "object",
                            "properties": {"name": {"type": "string"}, "primary": {"type": "boolean"}}}},
                        "secondChamberSponsor": {
                            "type": ["object", "null"],
                            "description": "The member sponsoring the measure in the other chamber (a "
                                           "senator for a House measure, or the reverse). Not part of "
                                           "sponsors[]. null when the legislature lists none.",
                            "properties": {"name": {"type": ["string", "null"]},
                                           "legisGaGovId": {"type": "integer"},
                                           "chamber": {"type": "string", "enum": ["lower", "upper"]}}},
                        "billUrl": {"type": ["string", "null"]},
                        "textUrl": {"type": ["string", "null"]},
                        "passageVotes": {"type": "array", "items": {"type": "object", "properties": {
                            "chamber": {"type": "string", "enum": ["lower", "upper"]},
                            "date": {"type": "string"},
                            "time": {"type": ["string", "null"], "description": "HH:MM; orders same-day votes."},
                            "result": {"type": "string", "description": "pass / fail under Georgia's "
                                       "constitutional thresholds, never yea > nay."},
                            "motionText": {"type": "string"},
                            "yea": {"type": "integer"}, "nay": {"type": "integer"}, "other": {"type": "integer"},
                            "linkedBy": {"type": "string", "enum": ["listing"],
                                         "description": "Present when legis.ga.gov links the roll call "
                                                        "to no bill and the link was read from the vote "
                                                        "listing's text."}}}},
                        "governorAction": {"type": ["object", "string", "null"]},
                        "legislationType": {"type": ["string", "null"], "enum": ["GEN", "LOC", "CA", "PRIV", "NP", None],
                                            "description": "legis.ga.gov's kind: general bill, local act, "
                                                           "constitutional amendment, privileged or "
                                                           "non-privileged resolution."},
                        "footnotes": {"type": "array", "items": {"type": "string"},
                                      "description": "legis.ga.gov procedural notes, oldest first."},
                        "committees": {"type": "array", "items": _COMMITTEE,
                                       "description": "The committee holding the bill in each chamber "
                                                      "now; legis.ga.gov overwrites it on a move."},
                        "committeeHistory": {"type": "array", "items": {"type": "object", "properties": {
                            "chamber": {"type": "string", "enum": ["lower", "upper"]},
                            "from": _COMMITTEE, "to": _COMMITTEE,
                            "seenOn": {"type": "string", "description": "Day the publisher's run noticed "
                                       "the move, not the day of the move."}}},
                            "description": "Committee moves, recorded from the 2027 session on."},
                        "statusHistory": {"type": "array", "items": {"type": "array"},
                                          "description": "[datetime, code(, AmSub)] for every action, "
                                                         "oldest first; codes are legis.ga.gov's."},
                        "stage": {"type": ["object", "null"], "description": "Where the bill is.",
                                  "properties": {
                                      "kind": {"type": "string", "enum": [
                                          "signed", "vetoed", "governor", "agreement", "committee",
                                          "died-committee", "floor", "died-floor", "lost", "adopted"]},
                                      "label": {"type": "string", "description": "e.g. 'Passed House · Died in Senate Finance'."},
                                      "path": {"type": "string", "enum": ["full", "short"],
                                               "description": "full: origin committee, origin floor, other "
                                                              "committee, other floor, final version, Governor. "
                                                              "short: filed, adopted (a simple resolution)."},
                                      "steps": {"type": "array", "items": {
                                          "type": "array", "prefixItems": [
                                              {"type": "string", "enum": ["done", "current", "stopped", "ahead"]},
                                              {"type": "string"}, {"type": "string"}]}}}},
                    },
                    "additionalProperties": True,
                },
            },
        },
    }


def build_artifacts():
    """Split the biennium's bills by session into per-session archive dirs and refresh
    the root latest.json pointer. ga-bills.json now covers the whole biennium (each bill
    tagged with its `session`); each session directory gets a self-contained bills.json
    plus bills.csv, bills.schema.json, and BILLS.md. Closed sessions re-emit byte-stable."""
    doc = json.load(open(SRC_JSON, encoding="utf-8"))
    meta = doc.get("metadata", {})
    all_bills = doc.get("bills", [])
    subjects_bytes = open(SRC_SUBJECTS, "rb").read() if os.path.exists(SRC_SUBJECTS) else None

    bills_by_session = {}
    for b in all_bills:
        bills_by_session.setdefault(tag_session(b.get("session")), []).append(b)

    artifacts = {}
    sessions_index = []
    # Emit every session in the biennium, even one with no bills yet (a just-convened
    # special session), so the archive structure is complete and latest.json's
    # currentSession always resolves. Include any unexpected session id found in data.
    for sid in list(all_session_ids()) + [s for s in bills_by_session if s not in all_session_ids()]:
        sess_bills = bills_by_session.get(sid, [])
        slug = session_slug(sid)
        sess_doc = {
            "metadata": {
                "session": sid,
                "sessionName": session_name(sid),
                "biennium": BIENNIUM,
                "generatedAt": meta.get("generatedAt"),
                "source": meta.get("source", "legis.ga.gov official web service"),
                "totalBills": len(sess_bills),
                # This session's own legislative days, when the source file has them.
                **({"legislativeCalendar": meta["legislativeCalendar"][sid]}
                   if sid in (meta.get("legislativeCalendar") or {}) else {}),
            },
            "bills": sess_bills,
        }
        files = session_files(slug, with_subjects=False)
        artifacts[files["bills"]] = compact_json(sess_doc)
        artifacts[files["billsCsv"]] = bills_csv(sess_bills)
        artifacts[files["schema"]] = build_json(schema(files["schema"]))
        artifacts[files["summary"]] = bills_md(sess_doc)
        if subjects_bytes is not None:
            files["subjects"] = session_files(slug)["subjects"]
            artifacts[files["subjects"]] = subjects_bytes
        sessions_index.append({
            "id": sid, "name": session_name(sid), "slug": slug,
            "billCount": len(sess_bills), "files": files,
        })

    active_slug = session_slug(meta.get("activeSession") or ACTIVE_SESSION)
    # Root pointer to the biennium and the session in progress; source timestamp avoids
    # churn. Past sessions stay archived under sessions/ and are never overwritten.
    artifacts["latest.json"] = build_json({
        "biennium": BIENNIUM,
        "currentSession": active_slug,
        "activeSession": meta.get("activeSession") or ACTIVE_SESSION,
        "generatedAt": meta.get("generatedAt"),
        "billCount": len(all_bills),
        "sessions": sorted(sessions_index, key=lambda s: s["slug"]),
        # Earlier General Assemblies, newest first; [] until the first rollover.
        "earlierBienniums": earlier_bienniums(),
    })

    # latest.json above is a BILLS pointer (biennium, currentSession, sessions[]),
    # not a repo index — this repo also carries ballot measures, published
    # separately. So it stays exactly as it is, and the dataset describes itself
    # in data/bills/manifest.json instead. See
    # lib.sibling_publish.add_dataset_manifest for why no publisher here may
    # describe another's data.
    add_dataset_manifest(
        artifacts, REPO, "bills",
        title="Georgia General Assembly bills",
        description=("Every bill of the biennium with its sponsors, subjects, "
                     "status and roll-call votes, plus archived past sessions."),
        # The source file's own stamp, not this mirror's clock.
        generated_at=meta.get("generatedAt") or "",
        update_cadence="Daily January through April, while the General Assembly sits; weekly otherwise.",
        row_count=len(all_bills),
        coverage={"biennium": BIENNIUM, "activeSession": active_slug,
                  "sessions": sorted(s["slug"] for s in sessions_index)},
        files=[{"path": "latest.json",
                "description": "Biennium pointer: the session in progress and the archive."}]
              + [{"path": k, "description": ""} for k in sorted(artifacts)
                 if k != "latest.json"],
    )
    return artifacts


def gate_source(doc):
    """Refuse to publish a ga-bills.json that contradicts itself.

    This is validate_ga_bills.tier1, the same gate update-ga-bills.yml applies before
    it commits the file -- deliberately NOT a second, weaker copy. The workflow's old
    inline check was `len(bills) == 0` alone, which a file with a wrong totalBills, a
    per-session billCount that disagrees with its bills, or a duplicate bill id sailed
    through, straight into the public archive. Nothing here is a floor on the world: a
    session that legitimately holds no bills yet still publishes (build_artifacts emits
    it empty by design); only a file that contradicts itself is refused.
    """
    errors = validate_ga_bills.tier1(doc)
    if errors:
        bullets = "\n  - ".join(errors[:10])
        raise SystemExit(f"refusing to publish: ga-bills.json contradicts itself:\n  - {bullets}")


def main():
    gate_source(json.load(open(SRC_JSON, encoding="utf-8")))
    publish_or_dry_run(REPO, build_artifacts(), TOKEN_ENV)


if __name__ == "__main__":
    main()
