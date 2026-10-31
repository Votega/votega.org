#!/usr/bin/env python3
"""Shared subject taxonomy for local-government meeting enrichment.

ONE source of truth for the keyword taxonomy and the place-level rollup shared by
both meeting enrichers:

    enrich_legistar_meetings.py   Fulton / DeKalb — STRUCTURED Legistar API
                                  (EventItems / Matters / RollCalls), no OCR.
    enrich_ocr_meetings.py        Newton (CivicPlus) / Covington (CoreCode) /
                                  Douglas / Cobb / Henry (CivicClerk) — agenda &
                                  minutes PDFs, poppler text-layer + tesseract OCR.

Both classify meeting text with the same `TOPIC_RULES`, derive the same per-place
`flags`, and emit the same enriched-sidecar `summary` shape, so the UI
(assets/scripts/local-subjects.js "On recent agendas" + the local.html hub badges
via local-flags.json) lights up identically no matter which platform a place is
on. Keeping the taxonomy here — not copied into each enricher — is the same
single-source discipline as scripts/lib/votes_schema.py and lib/ga_match.py: a new
watch keyword is added once and every place inherits it.
"""

import json
import os
import re
from datetime import datetime, timezone

from lib.atomic_io import write_json_atomic

# ── Subject taxonomy ──────────────────────────────────────────────────────────
# Keyword rules over the meeting/agenda-item text. Matched case-insensitively as
# plain substrings (see classify). Data-center / land-use is the killer app —
# rezonings, special-use permits and comprehensive-plan amendments are where data
# centers, warehouses and quarries get approved, so those subjects drive the card
# flags. Add a keyword here and BOTH enrichers pick it up.
#
# The 'alpr' rule (automated license plate readers / mass-surveillance cameras)
# was tuned against real agendas with scripts/probe_alpr_keywords.py: the generic
# capability terms alone under-matched (recall 1/3) because governments name the
# dominant vendor plainly — "Flock", "Flock cameras", "safer city" — not "license
# plate reader". So the net is two layers: generic phrases (catch any vendor,
# even unknown ones) plus a vendor lexicon (Flock and its competitors). The
# probe measured recall 3/3 with zero false positives across 46 control docs.
TOPIC_RULES = {
    'data-center':        ['data center', 'data centre', 'hyperscale', 'data-center'],
    'rezoning':           ['rezon'],
    'special-land-use':   ['special land use', 'special-use', 'slup', 'conditional use',
                           'land use permit'],
    'variance':           ['variance'],
    # Not the bare prefix 'annex': it fired on the building noun "Annex" in meeting
    # location headers ("Courthouse Annex Boardroom | 150 Hudson Ridge …"), which
    # sits on every agenda, so a place like Banks looked wall-to-wall annexation.
    # The land-use action is always spelled "annexation" (noun) or annexed/annexing
    # (verb) — none of which is the building word — and in a mixed doc these skip the
    # header "Annex" and anchor on the real body item.
    'annexation':         ['annexation', 'annexed', 'annexing'],
    'development':        ['apartment', 'subdivision', 'warehouse', 'mixed use',
                           'mixed-use', 'townhome', 'multifamily', 'multi-family'],
    'comprehensive-plan': ['comprehensive plan', 'future land use', 'land use plan'],
    'millage-budget':     ['millage', 'ad valorem', 'tax rate', 'budget', 'fiscal year'],
    # Taxes and ballot questions a resident pays or votes on. Separate from
    # 'millage-budget', whose bare 'budget' / 'fiscal year' match nearly every agenda.
    # Georgia's local-option sales taxes are known by acronym: SPLOST (special purpose),
    # ESPLOST (education), TSPLOST (transportation), FLOST (floating), HOST (homestead
    # option), LOST (local option). 'splost' as a substring carries splost / esplost /
    # tsplost / t-splost in one keyword. Deliberately NOT matched: bare 'lost' and 'most'
    # (ordinary English - "lost time", "most members") and bare 'host' (hosted by);
    # those taxes are caught by their spelled-out names below. Bare 'tax' is also out:
    # it fires on every fee and permit line. Measured against the corpus before
    # shipping - see scripts/score_topic_lexicon.py --topic local-taxes.
    #
    # MEASURED 2026-10-30 over 935 documents / 40 places: 359 match. Hits: splost 247,
    # millage 109, ad valorem 40, referendum 32, local option sales tax 26, special
    # purpose local option 22, homestead exemption 19, tax allocation district 17,
    # tax digest 16, hotel/motel tax 16, tax abatement 14, general obligation bond 12,
    # homestead option sales tax 9, flost 7. Dead across the whole corpus, so not
    # shipped: 'education local option' and 'bond referendum' (the long ESPLOST name
    # and any bond vote are already caught by 'special purpose local option' and
    # 'referendum'), and the unhyphenated 'bond for title' ('bond-for-title' fired 2).
    'local-taxes':        ['splost', 'special purpose local option',
                           'local option sales tax', 'homestead option sales tax',
                           'floating local option',
                           'millage', 'rollback rate', 'ad valorem', 'tax digest',
                           'property tax increase', 'notice of property tax',
                           'homestead exemption',
                           'hotel-motel tax', 'hotel/motel tax', 'hotel motel tax',
                           'tax allocation district', 'tax increment',
                           'tax abatement', 'bond-for-title',
                           'general obligation bond',
                           'referendum'],
    'contract':           ['contract', 'procurement', 'task order', 'award of', 'purchase order'],
    'appointment':       ['appoint', 'reappoint'],
    'alpr':               ['license plate reader', 'license plate recognition',
                           'automated license plate', 'automatic license plate',
                           'plate reader', 'lpr camera', 'safer city',
                           # Vendors beyond Flock (Flock itself is a word-rule below).
                           # Keyed on ALPR-SPECIFIC brands: 'vigilant solutions' is
                           # Motorola's ALPR line, but the bare 'motorola solutions'
                           # parent brand (radios/CAD/body cams) and 'mobile-vision'
                           # (in-car video) over-matched non-ALPR contracts, so they
                           # are omitted. 'fusus' (Axon real-time crime center) is a
                           # camera aggregator, not an ALPR vendor — omitted too.
                           'vigilant solutions', 'genetec', 'autovu', 'sharpv',
                           'rekor', 'openalpr', 'elsag', 'neology', 'jenoptik',
                           'perceptics', 'verra mobility', 'platesmart',
                           # ── Expansion (2026-10): wider capability + surveillance net.
                           # Generic ALPR phrasing, incl. hyphen / "number plate" / scanner
                           # spellings the original four phrases missed. NOT the bare
                           # 'license plate': every county tag office has agenda items on
                           # plate fees, specialty plates and renewals.
                           'plate recognition', 'plate-reader', 'plate reading',
                           'plate scanner', 'plate capture', 'license plate camera',
                           'license-plate', 'number plate recognition',
                           'tag reader', 'tag recognition', 'lpr system',
                           # Surveillance beyond plate reading (the badge is
                           # "ALPR / surveillance"). Each is a narrow phrase: bare
                           # 'surveillance' (disease/health surveillance, inspection),
                           # 'cctv' (sewer-line inspection) and 'camera' are too broad.
                           'surveillance camera', 'surveillance technology',
                           'surveillance system', 'surveillance equipment',
                           # Face recognition stays IN scope: it runs on the camera
                           # feeds this page already tracks, so it is a camera
                           # capability rather than separate forensics.
                           'facial recognition', 'face recognition',
                           'real time crime center', 'real-time crime center',
                           # Gunshot detection. 'gunfire detection' is not a synonym
                           # we guessed at — it is the phrase a real Columbus agenda
                           # used for a SoundThinking contract ("a gunfire detection,
                           # alert, and analysis program"), which this rule matched
                           # only because the vendor was also named. An unknown
                           # vendor's contract in the same words was missed outright,
                           # so the capability net has to carry both spellings.
                           'gunshot detection', 'gunfire detection',
                           'gunshot sensor', 'acoustic gunshot',
                           'drone as first responder', 'drone as a first responder',
                           # ── SCOPE (2026-10) ────────────────────────────────────
                           # This page covers cameras, plate readers, drones and
                           # gunshot detection. Deliberately NOT matched, though they
                           # are surveillance in the broad sense: phone forensics
                           # ('cellebrite', 'graykey', 'magnet forensics'), phone
                           # interception ('cell site simulator', 'imsi catcher'),
                           # data-broker / fusion platforms ('peregrine
                           # technologies', 'palantir', 'babel street', 'fog data
                           # science') and records analytics with no sensor of its
                           # own ('predictive policing'). Each was dropped from this
                           # rule rather than never added: they were in the 2026-10
                           # expansion and pulled back when the page's scope was set.
                           # Re-adding any of them is a scope decision about what the
                           # page is FOR, not a recall tweak.
                           #
                           # Surveillance vendors. Narrow brand names only - never a
                           # word that is also a place or a common noun ('clearview'
                           # alone is a street name; 'axon' is tasers/body cams;
                           # 'motorola' is radios).
                           # ── PRECISION/RECALL POLICY (set 2026-10) ─────────────
                           # This rule is deliberately RECALL-FAVOURED: false
                           # positives are tolerated to avoid missing true ones.
                           # A missed ALPR contract is a story the public never
                           # learns about; a stray facility-camera item is noise a
                           # reader can see through in one click to the source. So
                           # when a term's evidence is genuinely mixed, it stays IN,
                           # and the bar an ALPR-capable vendor has to clear is
                           # "this brand sells the capability", not "every match in
                           # today's corpus was a clean purchase".
                           #
                           # 'avigilon' is kept on exactly that basis: it ships LPR
                           # analytics and sits in the Motorola Solutions portfolio
                           # alongside Vigilant. Measured note, not an argument
                           # against it: in the 1220-document corpus its 5 matches
                           # were all Comcast-resold "Eagle Eye Avigilon video
                           # management" for the Douglas County landfill, so expect
                           # facility-security items on the page from it. 'verkada'
                           # is kept for the same reason (it ships LPR too) despite
                           # matching nothing yet.
                           #
                           # The policy does NOT rescue a term that matches a
                           # PROHIBITION. 'hikvision' and 'dahua' are out because
                           # 100% of their matches were NDAA s.889 boilerplate
                           # ("shall not procure equipment produced by ... Hangzhou
                           # Hikvision ... or Dahua Technology Company") — a
                           # certification that the government does NOT buy the gear.
                           # That is not a tolerable false positive trading against
                           # a true one; in this corpus there was no true one to
                           # catch, so the term is pure noise with no upside. Revisit
                           # if a place is ever seen debating REMOVAL of such gear,
                           # which would be a real surveillance-policy item.
                           'fusus', 'shotspotter', 'soundthinking', 'clearview ai',
                           'avigilon', 'verkada',
                           # ── Added from corpus measurement (2026-10) ───────────
                           # Each earned its place by matching real documents; the
                           # candidates that did NOT are recorded below so the same
                           # guesses are not re-made.
                           #
                           # 'skydio' — drone vendor, in scope. 4 documents: a
                           # Gwinnett CID donating two Skydio X10 drones, and
                           # Gwinnett awarding a "Skydio Drone as First Responder"
                           # multi-year contract.
                           'skydio',
                           # 'axon enterprise video' — NOT bare 'axon enterprise'.
                           # Axon bought Fusus and renamed the product "Axon
                           # Enterprise Video and Data Collection"; Clayton's
                           # renewal still says "from FUSUS to Axon Enterprise
                           # Video...", so 'fusus' catches it only while the old
                           # name is mentioned. This phrase keeps catching it after
                           # that. Bare 'axon enterprise' was measured and rejected:
                           # 23 documents, of which the inspected majority are
                           # "BODY CAMERA/POLICE EQUIPMENT & SERVICES" and an
                           # "Interview Bundle" — body cams are an explicit category
                           # exclusion ('axon' is tasers/body cams), so matching the
                           # bare company name would reverse that decision sideways.
                           'axon enterprise video',
                           # 'crime center' without the 'real-time' prefix. No
                           # marginal documents today (the two hits already match on
                           # 'real-time crime center'), kept because the bare form
                           # is specific and costs nothing.
                           'crime center',
                           # ── Police-worn and in-car cameras (scope widened
                           # 2026-10, at the publisher's direction) ──────────────
                           # Body cams sit next to plate readers rather than inside
                           # them, and were originally excluded with the bare 'axon'
                           # brand. They are in now because a resident asking "what
                           # is my police department recording" is asking one
                           # question, not two. Measured: these phrases carry 26
                           # documents, 21 of them previously unmatched, across 8
                           # jurisdictions the page did not cover at all — among
                           # them Atlanta's amendment "TO INCREASE THE TOTAL NUMBER
                           # OF FLEET CAMERAS AND BODY WORN CAMERAS ... NOT TO
                           # EXCEED FORTY MILLION", and Carrollton's "PD Body Cam /
                           # Dash Cam Upgrades".
                           # 'body cam' is the substring form on purpose: it carries
                           # 'body cam', 'body cams' and 'body camera/s' in one
                           # keyword.
                           'body cam', 'bodycam', 'body-worn', 'body worn',
                           'dashcam', 'dash cam', 'in-car camera', 'in car camera',
                           # In-car "fleet" cameras are the closest crossover of all
                           # — Axon Fleet does plate recognition, so this is ALPR in
                           # a patrol car rather than on a pole. Zero marginal
                           # documents today (Atlanta's four already match on 'body
                           # worn'), kept because an agenda that says only "fleet
                           # cameras" would otherwise be missed, and because it
                           # costs no false positives to carry.
                           'fleet camera', 'axon fleet',
                           # The company as it is named in contracts. Deliberately
                           # NOT given a vendor label below, which keeps it MEDIUM
                           # confidence so it lands in the page's "possible
                           # mentions" tier rather than the confirmed one. That is
                           # the right home for it: of the 12 documents it adds
                           # beyond the capability phrases above, 2 are plainly
                           # tasers (a weapon, not surveillance) while ~5 are
                           # umbrella deals like Cherokee's "consolidated agreement
                           # ... for existing and future public safety technology"
                           # — worth surfacing for review, not worth asserting.
                           # Bare 'axon' stays out entirely: 32 documents, far too
                           # broad.
                           'axon enterprise',
                           #
                           # MEASURED AND REJECTED, with what they actually matched:
                           #   'detection camera'  both hits were a "Portable Gas
                           #       Detection Camera System" for Public Utilities —
                           #       sewer gas, no surveillance at all.
                           #   'license tag'       one hit, a disabled-veteran
                           #       parking exemption ordinance. Confirms bare tag /
                           #       plate words are tag-office noise.
                           #   'lvt'               no marginal documents, and it is
                           #       also luxury-vinyl-tile in construction packets.
                           #   'leonardo'          no marginal documents; a common
                           #       personal name.
                           # Dead across all 1220 documents, so not added at all:
                           #   flockos, flock nova, aerodome, vehicle fingerprint,
                           #   hotlist, tag camera, tag scanner, brinc, drone
                           #   program, unmanned aerial, public safety camera,
                           #   community camera, camera registry, camera sharing,
                           #   video analytics, smart camera, safe city, safety as a
                           #   service, vehicle detection system, license plate
                           #   data, gunfire alert, gunshot location, surveillance
                           #   policy, pips technology, insight lpr, tattile.
                           ],
}

# Keywords that must match as WHOLE WORDS, not substrings — same tag semantics as
# TOPIC_RULES but matched with a word boundary. 'flock' is how agendas name Flock
# Safety, but a bare substring would also fire on "flocking"/"flocked"; \bflock\b
# skips those while still catching "flock", "flock cameras", "flock/axon". 'alpr'
# is the acronym itself: as a substring it fired INSIDE unrelated words — a real
# case was "AppraisalPro" (apprais·ALPR·o), which flagged an appraisal-services
# contract as surveillance. \balpr\b still catches "ALPR", "ALPR cameras",
# "ALPR/LPR". (The substring rules above deliberately keep prefix behaviour like
# 'rezon'/'annex'; the multi-word ALPR phrases there — "plate reader", "lpr camera"
# — are space-delimited and can't hide inside a single word.)
TOPIC_WORD_RULES = {
    # 'lpr' / 'anpr' / 'rtcc' are acronyms, so whole-word only (never inside another
    # word). 'lpr' is near-unambiguous in agendas; 'rtcc' = real-time crime center.
    'alpr': ['flock', 'alpr', 'lpr', 'anpr', 'rtcc'],
    # Tax acronyms not already carried by the 'splost' substring; whole-word so they
    # cannot fire inside a longer word. 'lhost' (Local Homestead Option Sales Tax) and
    # 'olost' (Other LOST, Macon-Bibb's wording) were found by reading the corpus
    # matches: Catoosa, Meriwether and Morgan agendas call the new homestead tax
    # "LHOST", which the spelled-out phrase misses when only the acronym is used.
    # TAD (tax allocation district) is omitted: it is also a first name and a car part.
    'local-taxes': ['flost', 'lhost', 'olost'],
}
_WORD_RE = {kw: re.compile(r'\b' + re.escape(kw) + r'\b')
            for kws in TOPIC_WORD_RULES.values() for kw in kws}

# ── Whitespace-tolerant phrase matching ───────────────────────────────────────
# A multi-word keyword is matched with \s+ between its words, not as a literal
# single-spaced substring. PDF text layers break lines mid-phrase and carry the
# indentation with them, so a plain substring test silently misses the phrase:
#
#   '... purchase of Skydio Drone as First\n                Responder ...'
#
# which is a real Gwinnett agenda item buying a Drone-as-First-Responder program.
# Measured over the 1220-document corpus, collapsing whitespace recovers 11
# documents across five topics (comprehensive-plan +4, special-land-use +3,
# millage-budget +2, alpr +1, data-center +1) on 8 distinct keywords — among them
# 'data center', the subject this taxonomy exists for.
#
# Done as a REGEX over the original text rather than by normalising the text
# first, because topic_excerpts needs match OFFSETS that are valid in the text it
# quotes; normalising would shift every offset and corrupt the published excerpt.
# Joining re.escape()d words is deliberate too: re.escape stopped escaping spaces
# in 3.7, so replacing an escaped space would silently no-op on a modern runtime.
#
# NOT handled, because the corpus says it does not happen: end-of-line hyphenation
# ('read-\ner'). Collapsing those recovered ZERO documents, so the rule stays
# simple.
_PHRASE_RE = {kw: re.compile(r'\s+'.join(re.escape(w) for w in kw.split(' ')))
              for kws in TOPIC_RULES.values() for kw in kws if ' ' in kw}


def _find_kw(low, kw):
    """(start, end) of substring keyword `kw` in lowercased `low`, or None.

    Multi-word keywords match across any whitespace run; single-word keywords keep
    plain substring semantics, so deliberate prefix rules ('rezon' -> rezoning/
    rezoned) are unchanged."""
    rx = _PHRASE_RE.get(kw)
    if rx is not None:
        m = rx.search(low)
        return (m.start(), m.end()) if m else None
    i = low.find(kw)
    return (i, i + len(kw)) if i != -1 else None

# Every keyword (substring + word-rule) that counts as ALPR evidence — used to
# filter a meeting's matchedTerms down to the vendor/capability phrases that
# actually fired, for the sourced alprItems citations.
ALPR_TERMS = set(TOPIC_RULES['alpr']) | set(TOPIC_WORD_RULES['alpr'])

# Display labels for the ALPR vendor keywords, so a matched term can be shown as a
# vendor NAME on the topic index pages (assets/scripts/topic-index.js reads the
# vendor list the generator derives from these). Kept here, beside the lexicon it
# maps from, so the vendor identity stays single-source with the keywords — a new
# ALPR vendor keyword added above gets a label here in the same edit. Only the
# vendor/brand keywords appear; the generic capability phrases ("plate reader",
# "alpr", "flock") are evidence terms, not vendor names, and are intentionally
# absent. 'flock' is the one brand that is also its plain agenda spelling, so it
# maps to the Flock Safety label.
ALPR_VENDOR_LABELS = {
    'flock':              'Flock Safety',
    'vigilant solutions': 'Vigilant (Motorola)',
    'genetec':            'Genetec',
    'autovu':             'Genetec AutoVu',
    'sharpv':             'Genetec SharpV',
    'rekor':              'Rekor',
    'openalpr':           'OpenALPR (Rekor)',
    'elsag':              'Elsag (Leonardo)',
    'neology':            'Neology',
    'jenoptik':           'Jenoptik',
    'perceptics':         'Perceptics',
    'verra mobility':     'Verra Mobility',
    'platesmart':         'PlateSmart',
    'fusus':              'Fusus (Axon)',
    'shotspotter':        'ShotSpotter (SoundThinking)',
    'soundthinking':      'ShotSpotter (SoundThinking)',
    'clearview ai':       'Clearview AI',
    'avigilon':           'Avigilon (Motorola)',
    'skydio':             'Skydio',
    # A specific plate-reading product, unlike the bare company name 'axon
    # enterprise' — which is deliberately left unlabelled so it stays medium.
    'axon fleet':         'Axon Fleet',
    # Collapses with 'fusus' to one brand: same product, post-acquisition name.
    'axon enterprise video': 'Fusus (Axon)',
    'verkada':            'Verkada',
    # No 'cellebrite' / 'peregrine technologies' here: both left this page's scope
    # (see the SCOPE note in TOPIC_RULES). A label without its keyword fails the
    # contract test either way.
}

# The spelled-out capability phrases that, on their own, are unambiguous enough to
# mark a mention "high" confidence even without a named vendor (mirrors the
# handoff scanner's high tier). Everything else that trips the alpr rule is
# "medium" — real, badgeable, but keyword-only.
ALPR_HIGH_TERMS = {
    # The test for this set is whether the phrase ALONE names a specific
    # surveillance capability. It was written when this topic was plate readers
    # only, so when the scope widened (drones, gunshot detection, face recognition,
    # crime centres, body cams) the new capabilities were left scoring medium and
    # sorting into the page's "possible mentions" tier — which put Athens-Clarke's
    # real-time crime center next to a bare company-name match. These are not
    # maybes, so they are rated here with the rest.
    'real time crime center', 'real-time crime center', 'rtcc',
    'gunshot detection', 'gunfire detection', 'gunshot sensor', 'acoustic gunshot',
    'facial recognition', 'face recognition',
    'drone as first responder', 'drone as a first responder',
    # Plate-reader acronyms and the Georgia vernacular. 'lpr' is whole-word matched
    # and near-unambiguous in agendas (see TOPIC_WORD_RULES); "tag reader" is simply
    # how Georgia says plate reader.
    'alpr', 'anpr', 'lpr', 'lpr camera', 'lpr system', 'tag reader',
    # Deliberately NOT promoted, and left at medium so they land in the review
    # tier: 'surveillance camera/system/technology/equipment' (self-describing but
    # context-dependent — the Fayette hits are budget account-code lines), bare
    # 'crime center', and 'axon enterprise' (see its note above).
    # Police-worn / in-car cameras: a "body worn camera" item is not a maybe, it is
    # a body camera. Without these here the tier logic would file Atlanta's
    # forty-million-dollar fleet-and-body-camera amendment under "possible
    # mentions", which is exactly backwards.
    'body cam', 'bodycam', 'body-worn', 'body worn',
    'dashcam', 'dash cam', 'in-car camera', 'in car camera', 'fleet camera',
    'automated license plate', 'automatic license plate',
    'license plate recognition', 'license plate reader',
    'license-plate', 'plate recognition', 'number plate recognition',
}


def alpr_vendors(terms):
    """Distinct vendor display names implied by a meeting's matched ALPR terms."""
    return sorted({ALPR_VENDOR_LABELS[t] for t in terms if t in ALPR_VENDOR_LABELS})


# ── Per-mention excerpts (Phase A) ─────────────────────────────────────────────
# The badges/citations only need to know a tag FIRED; an excerpt needs the match
# POSITION, so this re-scans the text for offsets (classify/matched_terms answer
# "which", this answers "where"). Kept here so the one taxonomy owns both. Callers
# gate on the extraction method — excerpts are captured from the poppler text layer
# only, never OCR, because OCR text is non-deterministic (noisy git diffs) and
# often garbled (a misquote in public). See the topic-index rollout notes.

EXCERPT_CHARS = 240  # window of context captured around a matched term


def _snip(text, start, end):
    """A whitespace-collapsed excerpt around [start:end), with … where trimmed.

    Drops U+FFFD replacement chars first: pdftotext decodes with errors='replace',
    so a byte it can't map as UTF-8 becomes U+FFFD, which we must not quote
    verbatim in public. Removing it (rather than leaving a stray box glyph) keeps
    the quote clean; the whitespace collapse tidies the gap it leaves."""
    lo = max(0, start - EXCERPT_CHARS // 2)
    hi = min(len(text), end + EXCERPT_CHARS // 2)
    body = " ".join(text[lo:hi].replace(chr(0xFFFD), " ").split())
    return ("… " if lo > 0 else "") + body + (" …" if hi < len(text) else "")


def _tag_matches(low, tag):
    """All (start, end, keyword) hits for a tag's keywords, over lowercased text.
    Offsets are valid in the original text too (lower() preserves length here)."""
    hits = []
    for kw in TOPIC_RULES.get(tag, []):
        span = _find_kw(low, kw)
        if span:
            hits.append((span[0], span[1], kw))
    for kw in TOPIC_WORD_RULES.get(tag, []):
        m = _WORD_RE[kw].search(low)
        if m:
            hits.append((m.start(), m.end(), kw))
    return hits


def _best_hit(hits, tag):
    """Pick the hit to quote. For ALPR, prefer a vendor / spelled-out capability
    term (the high-confidence evidence) over a bare acronym; else earliest."""
    if tag == "alpr":
        strong = [h for h in hits
                  if h[2] in ALPR_VENDOR_LABELS or h[2] in ALPR_HIGH_TERMS]
        if strong:
            return min(strong, key=lambda h: h[0])
    return min(hits, key=lambda h: h[0])


# ── Public-comment vs agenda-action context ────────────────────────────────────
# A topic can surface two very different ways on an agenda: as GOVERNMENT BUSINESS
# (an item, motion, resolution, or a formal public *hearing* on a specific matter),
# or as PUBLIC COMMENT (a resident sign-up roster / open citizen input). Same words,
# very different meaning — a data center *approved* vs a neighbor complaining about
# one. The signal is WHERE in the document the hit falls, so this keys off the
# nearest preceding section header, with local-cue fallbacks. Used to (a) label the
# topic pages and (b) decide which OCR excerpts are safe to republish (public-comment
# rosters name residents; action items don't).

# Open citizen-input sections. Deliberately excludes "public HEARING" — a hearing is
# a formal action on a specific matter, not open comment (that's ACTION below).
_PC_HEADER_RE = re.compile(
    r"public\s+(?:comment|participation|input|forum)s?"
    r"|(?:audience|citizens?)\s+(?:comment|participation|input)"
    r"|citizens?\s+to\s+be\s+heard"
    r"|comments?\s+from\s+(?:the\s+)?(?:public|citizens|audience|floor)"
    r"|non[-\s]agenda\s+items?"
    r"|items?\s+from\s+(?:the\s+)?(?:public|citizens|audience)"
    r"|public\s+address(?:es)?\s+(?:the\s+)?(?:board|commission|council)",
    re.I)

# Government-business SECTION headers only — structural dividers, NOT content
# words. Words like "ordinance", "resolution", or "rezoning" are deliberately
# excluded here: they appear in citizen comment topics too (a resident speaking
# "re: the Storage Ordinance" is still public comment), so treating them as section
# headers misfiled roster hits as action. They live in _ACTION_CUE_RE below, which
# only applies when no section header precedes the hit at all.
_ACTION_HEADER_RE = re.compile(
    r"public\s+hearings?"
    r"|(?:old|new|unfinished|regular|other|commission|county|general)\s+business"
    r"|consent\s+(?:agenda|calendar)"
    r"|action\s+items?"
    r"|regular\s+agenda"
    r"|first\s+reading|second\s+reading"
    r"|zoning\s+(?:agenda|cases?)"
    r"|planning\s+(?:and|&)\s+zoning|planning\s+commission",
    re.I)

# Strong action verbs — used only as a fallback when no section header precedes the
# hit (e.g. a short structured Legistar item title with no surrounding agenda).
_ACTION_CUE_RE = re.compile(
    r"\bmotion\s+(?:to|by|carried|passed|failed)"
    r"|\bmoved\s+by\b|\bseconded\b"
    r"|\bresolution\b|\bordinance\b|\bpublic\s+hearing\b"
    r"|\brezoning\s+(?:application|petition|request|case)"
    r"|\bapprov(?:e|ed|al)\s+(?:of\s+)?(?:the\s+)?(?:agreement|contract|resolution|ordinance|rezoning|purchase|intergovernmental)"
    # land-use petitions: "requesting a variance", "application ... for rezoning"
    r"|\b(?:request(?:ing|ed)?|petition(?:ing|ed)?|applicant|application)\b[^.]{0,40}"
    r"\b(?:variance|rezon|special\s+use|special\s+exception|conditional\s+use|annex)"
    r"|\bfirst\s+reading|\bsecond\s+reading",
    re.I)

# A public-comment sign-up line: "First Last re:" (a named speaker + their topic).
_ROSTER_RE = re.compile(r"[A-Z][A-Za-z.'\-]+\s+[A-Z][A-Za-z.'\-]+\s+[Rr]e:\s")

# How far back to look for the governing section header. Long enough to clear a
# roster of speakers; short enough not to grab a header from a distant section.
_HEADER_LOOKBACK = 5000


def _nearest_header(pre, rx):
    """The last header match in `pre`, requiring it to be UPPERCASE. Agenda section
    dividers are set in caps ("PUBLIC HEARING", "NON-AGENDA ITEMS"); a resident's
    lowercase comment topic ("re: the public hearing") is not — so the caps rule
    keeps a content word inside a roster from masquerading as a section header, which
    is what would otherwise leak a public-comment excerpt as an action."""
    last = None
    for m in rx.finditer(pre):
        if m.group().isupper():
            last = m
    return last


def classify_context(text, start, end):
    """'public-comment' | 'agenda-action' | 'unknown' for a hit at [start:end).

    Decided by the nearest UPPERCASE section header preceding the hit; if none is
    within the look-back window, by local cues (an action verb, or a "Name re:"
    roster line)."""
    pre = text[max(0, start - _HEADER_LOOKBACK):start]
    pc = _nearest_header(pre, _PC_HEADER_RE)
    ac = _nearest_header(pre, _ACTION_HEADER_RE)
    if pc or ac:
        if pc and ac:
            return "public-comment" if pc.start() > ac.start() else "agenda-action"
        return "public-comment" if pc else "agenda-action"
    sent = _snip(text, start, end)  # local window around the hit
    if _ACTION_CUE_RE.search(sent):
        return "agenda-action"
    if _ROSTER_RE.search(sent):
        return "public-comment"
    return "unknown"


def topic_excerpts(text, tags):
    """{tag: {term, excerpt, context}} for each tag in `tags` that yields a
    locatable hit.

    `text` is the raw extracted page text; `tags` is that meeting's classify()
    result. Returns only tags whose keyword can actually be located (so a tag that
    fired on a keyword the finder can't re-locate is simply omitted, never faked).
    `context` is public-comment / agenda-action / unknown (see classify_context).
    """
    if not text:
        return {}
    low = text.lower()
    out = {}
    for tag in tags:
        hits = _tag_matches(low, tag)
        if not hits:
            continue
        start, end, term = _best_hit(hits, tag)
        out[tag] = {
            "term": term,
            "excerpt": _snip(text, start, end),
            "context": classify_context(text, start, end),
        }
    return out

# Subjects that make a meeting "land use" — drives the land-use card flag.
LAND_USE = {'data-center', 'rezoning', 'special-land-use', 'variance',
            'annexation', 'development', 'comprehensive-plan'}


# ── Combined "agenda packet" trimming ─────────────────────────────────────────
# Some governments (City of Carrollton) publish the meeting AGENDA as a full
# "packet" PDF: the one-page agenda outline followed by every supporting document —
# INCLUDING the complete minutes of the PRIOR meetings being approved under the
# agenda's "MINUTES" item. Classifying the whole packet then stamps the CURRENT
# meeting with topics that were actually discussed at those earlier meetings — a
# Flock/ALPR contract or a data center from last month's embedded minutes surfaces
# as this month's agenda. (Those earlier meetings are enriched correctly and
# independently from their OWN minutes files, so nothing is lost by excluding them
# here.)
#
# The agenda proper always ends at its ADJOURN item; the bundled prior minutes —
# each a meeting in its own right, with its own ADJOURN — follow after it. So for a
# packet source, classify only the head up to and including the first ADJOURN. A
# plain (non-packet) agenda carries its single ADJOURN at the very end, so the trim
# is a harmless no-op there; a document with no ADJOURN at all is returned
# unchanged. Opt in per place via domains.meetings.agenda_packet, applied by the
# enricher to AGENDA text only (minutes files are already single-meeting).
_ADJOURN_RE = re.compile(r'\badjourn(?:ment|ed|ing|s)?\b', re.I)


def agenda_head(text):
    """The agenda proper: text up to and including the first ADJOURN token, with any
    documents bundled after it (notably embedded prior-meeting minutes) dropped.
    Returns `text` unchanged when no ADJOURN token is present."""
    if not text:
        return text
    m = _ADJOURN_RE.search(text)
    return text[:m.end()] if m else text


def classify(text):
    """Return the sorted list of subject tags whose keywords appear in `text`."""
    t = (text or '').lower()
    tags = {tag for tag, kws in TOPIC_RULES.items()
            if any(_find_kw(t, k) for k in kws)}
    tags |= {tag for tag, kws in TOPIC_WORD_RULES.items()
             if any(_WORD_RE[k].search(t) for k in kws)}
    return sorted(tags)


def matched_terms(text):
    """Return the concrete keywords that matched — the *evidence* behind the tags.

    OCR/agenda text has no per-item structure, so the sourced flag points at the
    whole meeting; recording which phrases tripped a tag lets the pipeline (and a
    human auditor) see *why* a place is flagged without re-reading the PDF.
    """
    t = (text or '').lower()
    terms = {k for kws in TOPIC_RULES.values() for k in kws if _find_kw(t, k)}
    terms |= {k for k, rx in _WORD_RE.items() if rx.search(t)}
    return sorted(terms)


def topic_flags(topics):
    """Per-meeting/-place flags from a {tag: count} (or tag-iterable) of topics.

    Identical rule for both enrichers: any land-use subject → 'land-use';
    'data-center', 'millage-budget' and 'alpr' surface as their own flags.
    """
    present = set(topics)
    flags = []
    if present & LAND_USE:
        flags.append('land-use')
    if 'data-center' in present:
        flags.append('data-center')
    if 'millage-budget' in present:
        flags.append('millage-budget')
    if 'alpr' in present:
        flags.append('alpr')
    if 'local-taxes' in present:
        flags.append('local-taxes')
    return flags


# ── Place-level rollup ────────────────────────────────────────────────────────

def _agenda_excerpt(m, tag):
    """The agenda-action excerpt {excerpt, excerptTerm} for `tag` on meeting `m`,
    or None. Mirrors the site/dataset policy: quote only government business
    (agenda-action); never public-comment/unknown, whose text can name private
    residents from sign-up rosters. So an excerpt on a summary item always means
    the topic surfaced as an item/motion/hearing, not during public comment."""
    te = (m.get('topicExcerpts') or {}).get(tag)
    if isinstance(te, dict) and te.get('context') == 'agenda-action' and te.get('excerpt'):
        return {'excerpt': te['excerpt'], 'excerptTerm': te.get('term')}
    return None


def build_summary(enriched):
    """Roll per-meeting enrichment up into the place-level `summary` the UI reads.

    Each `enriched` meeting must carry:
        date            'YYYY-MM-DD'
        flags           list[str]      (from topic_flags)
        topics          {tag: count}
        matchedTerms    list[str]      (from matched_terms; may be empty)
        dataCenterItems list[{title, date, sourceUrl}]  (may be empty)

    The Legistar enricher fills dataCenterItems from the structured land-use
    *items*; the OCR enricher fills it at the *meeting* level (one entry per
    flagged meeting) — either way every entry links a source. `landUseItems` and
    `alprItems` are DERIVED here uniformly from each meeting's `topics` (the
    meeting's title/date/sourceUrl + which subjects/vendor terms it hit), so a
    Legistar and an OCR place get the same sourced lists; data-center meetings are
    excluded from landUseItems because they already surface in dataCenterItems.
    """
    lu_tags = LAND_USE - {'data-center'}
    topic_totals = {}
    dc_items = {}
    lu_items = {}
    alpr_items = {}
    flags = set()
    last = None
    land_use_meetings = 0
    alpr_meetings = 0
    for m in enriched:
        flags.update(m.get('flags') or [])
        if 'land-use' in (m.get('flags') or []):
            land_use_meetings += 1
        d = m.get('date')
        if d and (last is None or d > last):
            last = d
        mtopics = m.get('topics') or {}
        for tag, n in mtopics.items():
            topic_totals[tag] = topic_totals.get(tag, 0) + n
        for it in (m.get('dataCenterItems') or []):
            # Attach this meeting's agenda-action data-center excerpt (if any) so
            # the place page can quote it, matching the topic page / dataset.
            ex = _agenda_excerpt(m, 'data-center')
            if ex:
                it.setdefault('excerpt', ex['excerpt'])
                it.setdefault('excerptTerm', ex['excerptTerm'])
            # De-dupe by title so the same recurring item across meetings lists once.
            dc_items.setdefault(it['title'], it)
        # Land-use citations: a meeting that hit a land-use subject OTHER than
        # data-center (which has its own list). One entry per distinct meeting.
        present_lu = sorted(set(mtopics) & lu_tags)
        if present_lu and 'data-center' not in mtopics:
            title = m.get('title') or m.get('body') or 'Meeting'
            key = (m.get('date'), title)
            entry = {
                'title': title, 'date': m.get('date'),
                'sourceUrl': m.get('sourceUrl'), 'tags': present_lu}
            # First present land-use subtag with an agenda-action excerpt wins.
            for tg in present_lu:
                ex = _agenda_excerpt(m, tg)
                if ex:
                    entry['excerpt'] = ex['excerpt']
                    entry['excerptTerm'] = ex['excerptTerm']
                    break
            lu_items.setdefault(key, entry)
        # ALPR citations: one entry per distinct meeting that hit the alpr subject,
        # carrying the concrete vendor/capability terms that fired (from the
        # meeting's matchedTerms) as the evidence — the same sourced-list shape as
        # land use, derived uniformly so Legistar and OCR places match.
        if 'alpr' in mtopics:
            alpr_meetings += 1
            title = m.get('title') or m.get('body') or 'Meeting'
            terms = sorted(set(m.get('matchedTerms') or []) & ALPR_TERMS)
            key = (m.get('date'), title)
            entry = {
                'title': title, 'date': m.get('date'),
                'sourceUrl': m.get('sourceUrl'), 'terms': terms}
            ex = _agenda_excerpt(m, 'alpr')
            if ex:
                entry['excerpt'] = ex['excerpt']
                entry['excerptTerm'] = ex['excerptTerm']
            alpr_items.setdefault(key, entry)
    # Newest first, capped so the committed sidecar stays small.
    lu_sorted = sorted(lu_items.values(), key=lambda x: x.get('date') or '', reverse=True)
    alpr_sorted = sorted(alpr_items.values(), key=lambda x: x.get('date') or '', reverse=True)
    return {
        'flags': sorted(flags),
        'lastActivity': last,
        'topicTotals': topic_totals,
        'dataCenterItems': list(dc_items.values()),
        'landUseItems': lu_sorted[:20],
        'landUseMeetings': land_use_meetings,
        'alprItems': alpr_sorted[:20],
        'alprMeetings': alpr_meetings,
    }


def flag_entry(summary):
    """The compact per-place record written into the hub file local-flags.json."""
    return {
        'flags': summary['flags'],
        'dataCenterCount': len(summary['dataCenterItems']),
        'landUseCount': len(summary.get('landUseItems') or []),
        'alprCount': len(summary.get('alprItems') or []),
        'lastActivity': summary['lastActivity'],
    }


def write_flags_file(out_dir, updates):
    """Merge per-place flag summaries into the single hub file local-flags.json.

    Merge, never replace: each enricher owns only its own places, so a Legistar
    run and an OCR run each update their slugs and leave the other's alone.
    """
    path = os.path.join(out_dir, 'local-flags.json')
    doc = {'metadata': {}, 'places': {}}
    if os.path.exists(path):
        try:
            with open(path, encoding='utf-8') as f:
                doc = json.load(f)
        except (ValueError, OSError):
            pass
    doc.setdefault('places', {}).update(updates)
    doc['metadata'] = {'generatedAt': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}
    write_json_atomic(path, doc, indent=1)
    return path
