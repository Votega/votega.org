#!/usr/bin/env python3
"""Generate presidential-executive-orders.json for the federal-executive page.

Two sources, one file:

  1. The Federal Register API is the record. It carries the executive order
     number, the official title and the permanent URL, but publishes an order
     3-5 days after it is signed.
  2. whitehouse.gov's Presidential Actions RSS feed carries orders the day they
     are signed, with no number (the Office of the Federal Register assigns it at
     publication). An order that appears there and not yet in the Register is
     written as a PROVISIONAL entry: `provisional: true`, `executive_order_number:
     null`, linked to whitehouse.gov. When the Register publishes it the entry is
     replaced by the Register record, which keeps `whitehouse_url` as provenance.

Reconciliation happens here, at build time, so the page just renders the file.

Why the join is on the normalized title: the number does not exist on
whitehouse.gov at signing. Once the order is numbered, the page gains an attached
PDF named `eo-NNNNN.pdf`; that is the item identifying ITSELF (unlike numbers in
the body text, which cite other orders), so when present it is read as
`claimed_number` and OUTRANKS the title: it rescues a reworded title and vetoes a
title match to a record with a different number. Most provisional entries have no
such file yet, so the title remains the join that matters, and the fragile part:
a title reworded between posting and publication leaves a duplicate. So a
provisional entry has a hard expiry (PROVISIONAL_TTL_DAYS from signing), after
which it is dropped from `orders` and listed in `metadata.expiredProvisional`.
The validator reports that list, because an expiry means matching broke.

Failure policy: the Federal Register is required (exit 1, nothing written). The
White House feed is a supplement; when it is unreachable the previous file's
still-valid provisional entries are carried forward rather than failing the run.

Output: assets/data/presidential-executive-orders.json
"""

import html
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.atomic_io import write_json_atomic  # noqa: E402
from lib.federal_register import fetch_all  # noqa: E402
from lib.http import fetch_bytes, fetch_json  # noqa: E402

FR_URL = "https://www.federalregister.gov/api/v1/documents.json"
FR_FIELDS = ["document_number", "executive_order_number", "title",
             "signing_date", "abstract", "html_url"]
WH_FEED_URL = "https://www.whitehouse.gov/presidential-actions/feed/"
WH_CATEGORY = "Executive Orders"
TERM_START = "2025-01-20"   # Update when a new administration begins
PER_PAGE = 100

#: A provisional entry still unmatched this many days after signing is dropped.
#: The Register's lag is 3-5 days, so two weeks leaves wide margin; an order
#: still unmatched by then is a matching failure, not a lag.
PROVISIONAL_TTL_DAYS = 14
#: A Register record this far from the White House date is a different order
#: that happens to share a title (amendments repeat titles), not the same one.
MATCH_WINDOW_DAYS = 7

OUTPUT_FILE = "assets/data/presidential-executive-orders.json"

_CONTENT_NS = "{http://purl.org/rss/1.0/modules/content/}encoded"
_MONTHS = ("January February March April May June July August September "
           "October November December").split()


# ── title / date / text helpers ────────────────────────────────────────────────

def normalize_title(title):
    """Join key: lowercase, alphanumerics only. 'Of'/'of' and curly/straight
    apostrophes (and the U+FFFD whitehouse.gov sometimes ships for one) agree.

    A phrase of two or more words typed twice running collapses to one, because
    whitehouse.gov has published titles like 'Program Integrity and Integrity and
    Interagency Coordination' that the Register's record of the same order lacks, and
    the exact-title join otherwise strands the order as an expired provisional. A
    single repeated word is left alone, and the match still needs the signing dates to
    sit within MATCH_WINDOW_DAYS, so collapsing both sides cannot join two orders."""
    tokens = re.findall(r"[a-z0-9]+", (title or "").lower())
    i = 0
    while i < len(tokens):
        for n in range(2, (len(tokens) - i) // 2 + 1):
            if tokens[i:i + n] == tokens[i + n:i + 2 * n]:
                del tokens[i + n:i + 2 * n]
                break
        else:
            i += 1
    return "".join(tokens)


def clean_title(title):
    """Display title: unescaped, with the feed's U+FFFD apostrophes repaired."""
    t = html.unescape(title or "")
    t = re.sub(r"(?<=\w)�(?=\w)", "’", t)
    return re.sub(r"\s+", " ", t.replace("�", " ")).strip()


def strip_tags(fragment):
    # Inline tags vanish (the feed wraps "Section" and "1" in separate <span>s, and
    # a space for each leaves "Section 1 ."); only <br> separates words.
    text = re.sub(r"<br\s*/?>", " ", fragment, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text).replace("\xa0", " ").replace("�", " ")
    return re.sub(r"\s+", " ", text).strip()


def _us_eastern_offset(utc_dt):
    """Hours behind UTC for US Eastern at that instant (4 in DST, else 5).
    Computed rather than read from zoneinfo, which needs a tz database the
    Windows dev machines and some runners do not have."""
    y = utc_dt.year

    def nth_sunday(month, n):
        d = date(y, month, 1)
        d += timedelta(days=(6 - d.weekday()) % 7)
        return d + timedelta(weeks=n - 1)

    # DST runs 2am local, second Sunday of March -> first Sunday of November.
    start = datetime.combine(nth_sunday(3, 2), datetime.min.time()) + timedelta(hours=7)
    end = datetime.combine(nth_sunday(11, 1), datetime.min.time()) + timedelta(hours=6)
    naive = utc_dt.replace(tzinfo=None)
    return 4 if start <= naive < end else 5


def pubdate_to_eastern_date(pub_date):
    """RFC 822 pubDate -> the US Eastern calendar date it was posted."""
    from email.utils import parsedate_to_datetime
    dt = parsedate_to_datetime(pub_date).astimezone(timezone.utc)
    return (dt - timedelta(hours=_us_eastern_offset(dt))).date()


_SIGNATURE = re.compile(
    r"THE\s+WHITE\s+HOUSE,?\s*(" + "|".join(_MONTHS) + r")\s+(\d{1,2}),\s*(\d{4})",
    re.IGNORECASE)


def parse_signature_date(text):
    """The date in the signature block ('THE WHITE HOUSE, October 16, 2026.'), or
    None. Takes the last match: an order quoting another's signature is rare, but
    the real block is always the end of the document."""
    found = _SIGNATURE.findall(text or "")
    if not found:
        return None
    month, day, year = found[-1]
    try:
        return date(int(year), _MONTHS.index(month.capitalize()) + 1, int(day))
    except ValueError:
        return None


def body_paragraphs(content_html):
    """Text of the order's own paragraphs. The feed's `content:encoded` opens with
    the site's topper and navigation markup, none of which is in a
    `wp-block-paragraph` <p>, so selecting those drops it all."""
    paras = re.findall(r'<p class="wp-block-paragraph"[^>]*>(.*?)</p>',
                       content_html or "", flags=re.S)
    return [t for t in (strip_tags(p) for p in paras) if t]


_SECTION_LEAD = re.compile(r"^Sec(?:tion|\.)\s*\d+[A-Za-z]?\.\s*")
_SMALL = {"of", "and", "the", "to", "for", "in", "on", "a", "an", "or", "with"}


def _strip_section_heading(text):
    """'Section 1. Purpose. This order...' -> 'This order...'. The heading is up
    to five Title-Case words ending in a period; anything else is kept."""
    m = _SECTION_LEAD.match(text)
    if not m:
        return text
    rest = text[m.end():]
    h = re.match(r"((?:[A-Za-z,'’&-]+\s){0,5}[A-Za-z,'’&-]+)\.\s+(?=\S)", rest)
    if h:
        words = h.group(1).split()
        if all(w[0].isupper() or w.lower() in _SMALL for w in words):
            return rest[h.end():]
    return rest


def build_abstract(paragraphs, limit=320):
    """First substantive sentence(s) of the order, or None. Skips the identical
    'By the authority vested in me...' preamble paragraph and the 'Section 1.
    Purpose.' lead-in; stops before the signature block."""
    for para in paragraphs:
        if re.match(r"By the authority vested in me", para, re.I):
            continue
        if re.match(r"(DONALD J\. TRUMP|THE WHITE HOUSE)", para):
            break
        text = _strip_section_heading(para).strip()
        if len(text) < 40:
            continue
        if len(text) > limit:
            text = text[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"
        return text
    return None


# ── sources ────────────────────────────────────────────────────────────────────

def fetch_federal_register(term_start, fetcher=fetch_json):
    """Every executive order signed on/after term_start, or None if any page
    failed (a short list would publish as fact)."""
    return fetch_all(
        "conditions%5Btype%5D%5B%5D=PRESDOCU"
        "&conditions%5Bpresidential_document_type%5D%5B%5D=executive_order"
        f"&conditions%5Bsigning_date%5D%5Bgte%5D={term_start}",
        FR_FIELDS, fetcher=fetcher, per_page=PER_PAGE)


_EO_PDF = re.compile(r"/uploads/[^\"'\s<>]*?/eo-(\d{4,6})\.pdf", re.I)


def claimed_number(content_html):
    """The EO number of the PDF whitehouse.gov attached to the item, or None.
    Read only from an `uploads/.../eo-NNNNN.pdf` URL - never from prose, where
    numbers are references to other orders - and None unless exactly one appears."""
    found = set(_EO_PDF.findall(content_html or ""))
    return found.pop() if len(found) == 1 else None


def parse_whitehouse_feed(xml_bytes):
    """Executive Orders items from the RSS feed as {title, url, signing_date,
    signing_date_source, abstract, claimed_number} dicts."""
    root = ET.fromstring(xml_bytes)
    items = []
    for item in root.iter("item"):
        if WH_CATEGORY not in [c.text for c in item.findall("category")]:
            continue
        body = item.findtext(_CONTENT_NS) or ""
        paras = body_paragraphs(body)
        signed = parse_signature_date(" ".join(paras[-6:]))
        source = "signature"
        pub = item.findtext("pubDate")
        posted = pubdate_to_eastern_date(pub) if pub else None
        # A signature outside [posted-30d, posted+1d] is a misparse, not a date.
        if signed and posted and not (posted - timedelta(days=30) <= signed <= posted + timedelta(days=1)):
            signed = None
        if signed is None:
            signed, source = posted, "pubDate"
        if signed is None:
            continue
        items.append({
            "title": clean_title(item.findtext("title")),
            "url": (item.findtext("link") or "").strip(),
            "signing_date": signed.isoformat(),
            "signing_date_source": source,
            "abstract": build_abstract(paras),
            "claimed_number": claimed_number(body),
        })
    return items


def dedupe_register(fr_orders):
    """One record per EO number. The Register republishes a corrected order under
    an `R1-` document number alongside the original (EO 14388 appears twice), and
    rendering both shows one order as two. Keeps the original; returns
    (kept, dropped_document_numbers)."""
    keep, dropped = {}, []
    for o in fr_orders:
        num = o.get("executive_order_number")
        if not num or num not in keep:
            keep[num or id(o)] = o
            continue
        rival = keep[num]
        reprint = lambda r: bool(re.match(r"R\d", r.get("document_number") or ""))
        if reprint(rival) and not reprint(o):
            dropped.append(rival["document_number"])
            keep[num] = o
        else:
            dropped.append(o.get("document_number"))
    kept_ids = {id(o) for o in keep.values()}
    return [o for o in fr_orders if id(o) in kept_ids], dropped


# ── reconciliation ─────────────────────────────────────────────────────────────

def _days_apart(a, b):
    return abs((date.fromisoformat(a) - date.fromisoformat(b)).days)


def reconcile(fr_orders, wh_items, today, carried=(), notes=None):
    """Merge the two sources. Returns (orders, expired).

    Every Register record is kept, gaining `whitehouse_url` if a White House item
    matches it. An item matches by its claimed EO number when it has one, else by
    normalized title within MATCH_WINDOW_DAYS; a title match to a record whose
    number differs from the one the item claims is vetoed. An item with no match
    becomes provisional unless it is past its TTL, in which case it is returned in
    `expired`. `carried` are provisional entries from the previous file, used only
    when the feed was unavailable (wh_items is None).

    `notes`, if given, is filled in place for the validator:
    `matchedByNumber` (number matched, titles differ: a reworded title the title
    join would have lost) and `numberConflicts` (a title join the number
    overruled)."""
    if notes is None:
        notes = {}
    notes.setdefault("matchedByNumber", [])
    notes.setdefault("numberConflicts", [])
    orders = [dict(o, whitehouse_url=o.get("whitehouse_url"), provisional=False)
              for o in fr_orders]
    by_key, by_num = {}, {}
    for o in orders:
        by_key.setdefault(normalize_title(o["title"]), []).append(o)
        if o.get("executive_order_number"):
            by_num[str(o["executive_order_number"])] = o
    claimed = set()

    expired, provisional = [], []
    if wh_items is None:
        wh_items = [{"title": c["title"], "url": c["whitehouse_url"],
                     "signing_date": c["signing_date"], "abstract": c.get("abstract"),
                     "signing_date_source": c.get("signing_date_source")}
                    for c in carried]
    def near(o, item):
        return bool(o.get("signing_date")) and _days_apart(o["signing_date"], item["signing_date"]) <= MATCH_WINDOW_DAYS

    # Numbered items first, so a title match can never take a record that an item
    # claiming its number is entitled to.
    for item in sorted(wh_items, key=lambda i: not i.get("claimed_number")):
        num = item.get("claimed_number")
        by_title = [o for o in by_key.get(normalize_title(item["title"]), [])
                    if id(o) not in claimed and near(o, item)]
        match = None
        if num:
            rec = by_num.get(num)
            if rec is not None and id(rec) not in claimed and near(rec, item):
                match = rec
                if normalize_title(rec["title"]) != normalize_title(item["title"]):
                    notes["matchedByNumber"].append({
                        "executive_order_number": num, "title": rec["title"],
                        "whitehouse_title": item["title"], "whitehouse_url": item["url"]})
            wrong = [o for o in by_title if str(o.get("executive_order_number")) != num]
            if wrong:
                notes["numberConflicts"].append({
                    "executive_order_number": num, "whitehouse_title": item["title"],
                    "title_matched_eo": wrong[0].get("executive_order_number"),
                    "whitehouse_url": item["url"]})
            by_title = [o for o in by_title if str(o.get("executive_order_number")) == num]
        if match is None and by_title:
            match = min(by_title, key=lambda o: _days_apart(o["signing_date"], item["signing_date"]))
        if match is not None:
            claimed.add(id(match))
            match["whitehouse_url"] = item["url"]     # provenance, never overwritten
            continue
        age = (today - date.fromisoformat(item["signing_date"])).days
        if age > PROVISIONAL_TTL_DAYS:
            expired.append({"title": item["title"], "signing_date": item["signing_date"],
                            "whitehouse_url": item["url"]})
            continue
        provisional.append({
            "document_number": None,
            "executive_order_number": None,
            "title": item["title"],
            "signing_date": item["signing_date"],
            "abstract": item.get("abstract"),
            "html_url": item["url"],
            "whitehouse_url": item["url"],
            "provisional": True,
            "signing_date_source": item.get("signing_date_source"),
        })

    merged = orders + provisional
    merged.sort(key=lambda o: (o.get("signing_date") or "",
                               int(o["executive_order_number"]) if o.get("executive_order_number") else 10 ** 9),
                reverse=True)
    return merged, expired


def build_output(fr_orders, wh_items, today, term_start, carried=(), now=None):
    fr_orders, duplicates = dedupe_register(fr_orders)
    notes = {}
    orders, expired = reconcile(fr_orders, wh_items, today, carried, notes)
    provisional = sum(1 for o in orders if o["provisional"])
    return {
        "metadata": {
            "generatedAt": (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": "Federal Register API (federalregister.gov), supplemented by "
                      "whitehouse.gov Presidential Actions for orders not yet published",
            "termStart": term_start,
            "count": len(orders),
            "federalRegisterCount": len(orders) - provisional,
            "provisionalCount": provisional,
            "whitehouseFeed": "unavailable" if wh_items is None else "ok",
            "whitehouseItems": 0 if wh_items is None else len(wh_items),
            "provisionalTtlDays": PROVISIONAL_TTL_DAYS,
            "expiredProvisional": expired,
            "duplicateRegisterRecords": duplicates,
            "matchedByNumber": notes["matchedByNumber"],
            "numberConflicts": notes["numberConflicts"],
        },
        "orders": orders,
    }


def read_carried(path):
    try:
        with open(path, encoding="utf-8") as f:
            prev = json.load(f)
    except (OSError, ValueError):
        return []
    return [o for o in prev.get("orders", []) if o.get("provisional")]


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else OUTPUT_FILE
    term_start = os.environ.get("TERM_START", TERM_START)
    today = date.fromisoformat(os.environ["TODAY"]) if os.environ.get("TODAY") else datetime.now(timezone.utc).date()

    fr = fetch_federal_register(term_start)
    if not fr:
        print("FATAL: Federal Register fetch failed or returned nothing", file=sys.stderr)
        sys.exit(1)
    print(f"Federal Register: {len(fr)} executive orders since {term_start}")

    raw = fetch_bytes(WH_FEED_URL, label="whitehouse.gov presidential-actions feed")
    wh = None
    if raw is not None:
        try:
            wh = parse_whitehouse_feed(raw)
        except ET.ParseError as exc:
            print(f"WARNING: whitehouse.gov feed did not parse: {exc}")
    if wh is None:
        print("WARNING: whitehouse.gov unavailable; carrying forward previous provisional entries")
    else:
        print(f"whitehouse.gov: {len(wh)} executive orders in the feed")

    data = build_output(fr, wh, today, term_start, carried=read_carried(out))
    m = data["metadata"]
    print(f"Wrote {m['count']} orders ({m['provisionalCount']} provisional, "
          f"{len(m['expiredProvisional'])} expired unmatched)")
    write_json_atomic(out, data, indent=2)


if __name__ == "__main__":
    main()
