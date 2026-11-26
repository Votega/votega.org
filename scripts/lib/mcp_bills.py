"""Bill index files for the VoteGA MCP server (spec §5.1, §12.3). Pure functions, stdlib only.

  bills/sessions.json                   which sessions exist and where their files are
  bills/<session>-<TYPE>.json           search rows (HB, HR, SB, SR)
  bills/<session>-<TYPE>-detail.json    links (incl. Georgia Commons), passage votes and governor
                                        action, by identifier
  bills/<session>-<TYPE>-tokens.json    title word -> bills, so keyword search never scans titles
                                        (per type: one table per session reached 145 KB gzipped)

Inputs are ga-bills.json documents, the live file FIRST and then any frozen
ga-bienniums/<tag>/ga-bills.json; a bill in two of them is taken from the first. The abstract is
not carried (it would put the largest detail file over budget).
"""
import re

TOKEN_RE = re.compile(r"[a-z0-9]+")
#: Function words only. Words common in titles ("tax", "county") stay searchable.
IGNORED = ("an", "and", "at", "by", "for", "in", "of", "on", "or", "the", "to")
TOKEN_RULE = ("Lowercase the query, split on anything that is not a-z or 0-9, drop one-character "
              "words and the words in `ignored`. Each word lists positions in `identifiers`.")
BILL_URL = "https://www.votega.org/ga-bills.html?bill={identifier}&legislationId={legislationId}"
COMMONS_URL = "https://georgiacommons.org/bills/{slug}/{number}"
COMMONS_LABEL = "Plain-language summary (AI-written), Georgia Commons"


def tokenize(text):
    words = TOKEN_RE.findall((text or "").lower())
    return sorted({w for w in words if len(w) > 1 and w not in IGNORED})


def commons_slug(session):
    """Georgia Commons' session segment: 2025_26 -> 2025-2026, 2026_ss -> 2026-special.
    An unrecognised shape gets None (no link) rather than a guessed one."""
    m = re.fullmatch(r"(\d{4})_(\d{2}|ss)", session or "")
    if not m:
        return None
    year, tail = m.groups()
    return f"{year}-special" if tail == "ss" else f"{year}-{year[:2]}{tail}"


def commons_url(session, identifier):
    """A bill's Georgia Commons page, or None for a session shape we cannot map. Commons drops
    the "EX" legis.ga.gov puts on special-session numbers: 2026_ss "HB 1EX" is .../hb1."""
    slug = commons_slug(session)
    if not slug:
        return None
    number = identifier.lower().replace(" ", "")
    if session.endswith("_ss"):
        number = re.sub(r"ex$", "", number)
    return COMMONS_URL.format(slug=slug, number=number)


def bill_type(identifier):
    m = re.match(r"([A-Z]+) \d", identifier or "")
    return m.group(1) if m else "OTHER"


def _clean(v):
    """Blank strings -> None, all the way down."""
    if isinstance(v, str):
        return v if v.strip() else None
    if isinstance(v, dict):
        return {k: _clean(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_clean(x) for x in v]
    return v


def source_bills(bill_docs):
    """-> {(session, identifier): (bill, doc index)}, earlier documents winning."""
    out = {}
    for i, doc in enumerate(bill_docs):
        for b in doc.get("bills") or []:
            if b.get("session") and b.get("identifier"):
                out.setdefault((b["session"], b["identifier"]), (b, i))
    return out


def _number(identifier):
    m = re.search(r"\d+", identifier)
    return (int(m.group()) if m else 0, identifier)


def word_table(titles):
    """{word: [positions of the titles that carry it]}, words sorted."""
    words = {}
    for n, title in enumerate(titles):
        for w in tokenize(title):
            words.setdefault(w, []).append(n)
    return {w: words[w] for w in sorted(words)}


def build_bills(bill_docs, generated_at):
    """-> {file name: document}."""
    live_meta = (bill_docs[0].get("metadata") or {}) if bill_docs else {}
    sessions = {}
    for (session, identifier), (b, i) in source_bills(bill_docs).items():
        sessions.setdefault(session, {}).setdefault(bill_type(identifier), []).append((b, i))

    docs, catalog = {}, []
    for session in sorted(sessions):
        shards, total, live = [], 0, False
        for kind in sorted(sessions[session]):
            pairs = sorted(sessions[session][kind], key=lambda p: _number(p[0]["identifier"]))
            live = live or any(i == 0 for _, i in pairs)
            src_stamp = (bill_docs[pairs[0][1]].get("metadata") or {}).get("generatedAt")
            names, rows, detail = {}, [], {}
            for b, _ in pairs:
                sponsors = []
                for s in b.get("sponsors") or []:
                    gid = s.get("legisGaGovId")
                    if gid is None:
                        continue
                    sponsors.append([gid, bool(s.get("primary"))])
                    if s.get("name"):
                        names[str(gid)] = s["name"]
                rows.append(_clean({
                    "legislationId": b.get("legislationId"), "identifier": b["identifier"],
                    "billType": b.get("billType"), "title": b.get("title"), "status": b.get("status"),
                    "statusDate": b.get("statusDate"), "subjects": b.get("subjects") or [],
                    "sponsors": sponsors}))
                detail[b["identifier"]] = _clean({
                    "billUrl": b.get("billUrl"), "textUrl": b.get("textUrl"),
                    "commonsUrl": commons_url(session, b["identifier"]),
                    "passageVotes": b.get("passageVotes") or [],
                    "governorAction": b.get("governorAction")})
            path = f"bills/{session}-{kind}.json"
            detail_path = f"bills/{session}-{kind}-detail.json"
            meta = {"generatedAt": generated_at, "count": len(rows), "session": session, "type": kind,
                    "sourceGeneratedAt": src_stamp}
            docs[path] = {"metadata": meta, "sponsorNames": names, "bills": rows}
            docs[detail_path] = {"metadata": dict(meta), "bills": detail}
            tokens_path = f"bills/{session}-{kind}-tokens.json"
            words = word_table(r["title"] for r in rows)
            docs[tokens_path] = {
                "metadata": {"generatedAt": generated_at, "count": len(words), "session": session,
                             "type": kind, "rule": TOKEN_RULE, "ignored": list(IGNORED)},
                "identifiers": [r["identifier"] for r in rows],
                "tokens": words,
            }
            total += len(rows)
            shards.append({"type": kind, "count": len(rows), "path": path, "detailPath": detail_path,
                           "tokensPath": tokens_path})

        catalog.append({
            "session": session, "live": live,
            "active": session == live_meta.get("activeSession"),
            "commonsSlug": commons_slug(session), "billCount": total, "shards": shards,
        })

    docs["bills/sessions.json"] = {
        "metadata": {"generatedAt": generated_at, "count": len(catalog),
                     "votegaUrlTemplate": BILL_URL, "commonsLabel": COMMONS_LABEL},
        "sessions": catalog,
    }
    return docs


def bill_errors(docs, bill_docs):
    errs = []
    catalog = docs.get("bills/sessions.json")
    if catalog is None:
        return ["bills/sessions.json is missing"]
    source = source_bills(bill_docs)
    want = set(source)
    have = []
    for s in catalog.get("sessions") or []:
        session = s["session"]
        for shard in s.get("shards") or []:
            doc, detail = docs.get(shard["path"]), docs.get(shard["detailPath"])
            if doc is None or detail is None:
                errs.append(f"bills: {shard['path']} or its detail file is not built")
                continue
            rows = doc.get("bills") or []
            if not doc["metadata"].get("count") == shard.get("count") == len(rows):
                errs.append(f"{shard['path']}: counts disagree")
            ids = [r.get("identifier") for r in rows]
            if any(bill_type(i) != shard["type"] for i in ids):
                errs.append(f"{shard['path']}: a bill is in the wrong shard")
            if set(detail.get("bills") or {}) != set(ids):
                errs.append(f"{shard['detailPath']}: detail bills differ from the search shard")
            have += [(session, i) for i in ids]
            tok = docs.get(shard["tokensPath"])
            if tok is None:
                errs.append(f"bills: {shard['tokensPath']} is not built")
                continue
            titles = [source.get((session, i), ({}, 0))[0].get("title") for i in ids]
            if tok.get("identifiers") != ids or tok.get("tokens") != word_table(titles):
                errs.append(f"{shard['tokensPath']}: word table does not match the shard's titles")
    if len(have) != len(set(have)) or set(have) != want:
        errs.append(f"bills differ from the source files (missing {sorted(want - set(have))[:5]}, "
                    f"extra {sorted(set(have) - want)[:5]})")
    return errs
