"""Turn committed Georgia executive orders into news-hub items.

The EO pipeline (update-ga-executive-orders.yml -> generate_ga_executive_orders.py
-> enrich_ga_executive_orders.py) already fetches, hashes, archives and text-extracts
every order the Governor signs. This module reads those committed artifacts:

    assets/data/ga-executive-orders-<year>.json   (date, number, title, category,
                                                   url, sha256, archiveUrl)
    assets/data/eo-text/<year>/<number>.txt       (pdftotext/OCR output)

and shapes them like a feed item for generate_ga_news.py. Deliberately NO fetch of
its own: gov.georgia.gov is already crawled once by the EO job, and a second fetch
here would add a network dependency and a second failure mode for data the repo
holds. A side benefit is that each card inherits the EO pipeline's `archiveUrl` and
`sha256`, so a news card can point at a Wayback snapshot if the PDF moves.

Two things this has to get right.

1. CATEGORY FILTERING IS NOT OPTIONAL. 257 of 2026's 318 orders (81%) are
   Appointment -- routine board appointments and reappointments. Piping everything
   in turns the hub into an appointments ticker. DEFAULT_CATEGORIES is the editorial
   cut, overridable from _data/news_sources.yml because the right cut will be
   revisited. `Writ of Election` matters more than its count suggests on a voting
   site: those are special elections.

2. THE EXTRACTED TEXT IS NOT IN READING ORDER. Georgia's EO PDFs are laid out so
   `pdftotext` emits the labels first and the body after, so the Hurricane Isaias
   order begins:

       THE STATE OF GEORGIA / EXECUTIVE ORDER / BY THE GOVERNOR: / WHEREAS:
       WHEREAS: WHEREAS: ... / STATE OF EMERGENCY FOR HURRICANE ISAIAS /
       The National Hurricane Center forecasts...

   A naive text[:200] yields "WHEREAS: WHEREAS: WHEREAS:". eo_snippet() skips the
   masthead, the label run and the all-caps subject block (which only repeats the
   title anyway) and starts at the first substantive sentence. Where it cannot find
   one -- a scan OCR'd to noise -- it returns None and the caller falls back to
   order_descriptor(): an honest "State of Emergency signed October 8, 2026." beats
   a garbled excerpt.
"""

import io
import json
import os
import re

#: Same excerpt budget the RSS path uses (generate_ga_news.SNIPPET_MAX).
SNIPPET_MAX = 200

#: An editorial judgement, not a fact about the data: every category EXCEPT
#: Appointment. Overridable via `executive_orders.categories` in
#: _data/news_sources.yml.
DEFAULT_CATEGORIES = (
    "State of Emergency",
    "Suspension",
    "Writ of Election",
    "Authorization",
    "Other",
    "Flag at Half-Staff",
)

#: A paragraph shorter than this is not a sentence: it is an OCR artifact
#: ("7 Lo", "alt Lb", "oa"), a signature line ("This 6 day of October 2026") or a
#: stray label. Body paragraphs in these orders run well over 100 characters.
MIN_BODY_CHARS = 40

#: A standalone structural label, in whatever case the extractor produced. The
#: all-caps test below already catches the usual "WHEREAS:" run; this covers a
#: title-cased one.
LABEL_RE = re.compile(
    r"^(whereas|ordered|attest|now,?\s+therefore|by\s+the\s+governor|"
    r"executive\s+order|the\s+state\s+of\s+georgia|governor|"
    r"in\s+witness\s+whereof)\b[\s:.,-]*$",
    re.IGNORECASE)

LOWERCASE_RE = re.compile(r"[a-z]")

MONTHS = ("January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December")


# --------------------------------------------------------------------------- #
# Snippet extraction
# --------------------------------------------------------------------------- #
def _paragraphs(text):
    """Blank-line-separated blocks, each with its hard line wraps collapsed."""
    for block in re.split(r"\n\s*\n", text):
        para = " ".join(block.split())
        if para:
            yield para


def _is_body(para):
    """True for a paragraph that reads as prose rather than scaffolding.

    An all-caps paragraph is never body text here: the masthead
    ("THE STATE OF GEORGIA"), every structural label ("WHEREAS:", "ORDERED:",
    "NOW, THEREFORE, BY THE POWER VESTED IN...") and the subject block
    ("STATE OF EMERGENCY FOR HURRICANE ISAIAS", which only restates the title)
    are upper-case, while the body is mixed-case.
    """
    if len(para) < MIN_BODY_CHARS:
        return False
    if not LOWERCASE_RE.search(para):
        return False
    if LABEL_RE.match(para):
        return False
    return True


def _truncate(s, max_chars):
    """Trim to max_chars on a word boundary, marking the cut with an ellipsis."""
    if len(s) <= max_chars:
        return s
    cut = s[:max_chars - 1]
    space = cut.rfind(" ")
    if space > 0:
        cut = cut[:space]
    return cut.rstrip(" ,;:.-") + "…"


def eo_snippet(text, max_chars=SNIPPET_MAX):
    """A readable excerpt from an order's extracted text, or None.

    None means "no substantive sentence found" -- the caller should fall back to
    order_descriptor() rather than publish a garbled excerpt.
    """
    if not text:
        return None
    body = [p for p in _paragraphs(text) if _is_body(p)]
    if not body:
        return None
    return _truncate(" ".join(body), max_chars)


def order_descriptor(order):
    """Honest short descriptor for an order whose text yields no clean snippet."""
    category = (order.get("category") or "").strip() or "Executive order"
    when = _pretty_date(order.get("date"))
    if not when:
        return f"{category} order." if category != "Executive order" else "Executive order."
    return f"{category} signed {when}."


def _pretty_date(iso):
    """'2026-05-01' -> 'May 1, 2026'. None for anything unparseable."""
    if not iso:
        return None
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", str(iso))
    if not m:
        return None
    year, month, day = (int(x) for x in m.groups())
    if not 1 <= month <= 12:
        return None
    return f"{MONTHS[month - 1]} {day}, {year}"


# --------------------------------------------------------------------------- #
# Loading the committed artifacts
# --------------------------------------------------------------------------- #
def load_orders(data_dir, years):
    """Orders from assets/data/ga-executive-orders-<year>.json for each year.

    A missing year file is skipped silently -- the hub's 45-day window spans a
    New Year, so the caller asks for the previous year too, and in early January
    the new year's file does not exist yet either.
    """
    orders = []
    for year in years:
        path = os.path.join(data_dir, f"ga-executive-orders-{year}.json")
        if not os.path.exists(path):
            continue
        with io.open(path, encoding="utf-8") as f:
            orders.extend(json.load(f).get("orders") or [])
    return orders


def make_text_reader(text_dir):
    """A (year, number) -> text|None lookup over assets/data/eo-text/.

    errors="replace" rather than a hard failure: these texts come from OCR of
    scanned PDFs, and one undecodable byte must not take down the news build.
    """
    def read(year, number):
        path = os.path.join(text_dir, str(year), f"{number}.txt")
        if not os.path.exists(path):
            return None
        with io.open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    return read


# --------------------------------------------------------------------------- #
# Item building
# --------------------------------------------------------------------------- #
def build_news_items(orders, source_name, text_lookup, categories, make_id,
                     snippet_max=SNIPPET_MAX):
    """Shape allowlisted orders like feed items from generate_ga_news.parse_feed.

    `make_id` is injected (the generator passes its own canonical-URL hash, so EO
    cards dedupe against feed cards by exactly the same rule) and `text_lookup` is
    injected so this is testable with no disk.
    """
    allowed = set(categories or ())
    items = []
    for order in orders:
        category = order.get("category")
        if category not in allowed:
            continue
        url = (order.get("url") or "").strip()
        if not url:
            continue
        number = order.get("number")
        date = order.get("date")
        text = text_lookup(str(date)[:4], number) if (date and number) else None
        snippet = eo_snippet(text, snippet_max) or order_descriptor(order)
        items.append({
            "id": make_id(url),
            "title": order.get("title") or f"Executive Order {number}",
            "url": url,
            "source": source_name,
            "publishedAt": f"{date}T00:00:00+00:00" if date else None,
            "snippet": snippet,
            "category": category,
            "orderNumber": number,
            "archiveUrl": order.get("archiveUrl"),
            "sha256": order.get("sha256"),
        })
    return items
