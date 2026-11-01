"""Hand-saved Senate roll-call XML: the sanctioned path while senate.gov refuses bots.

senate.gov has answered every automated request under /legislative/ with an Akamai
403 since 2026-10-25, but the files render in a browser. A person saving one
("Save As" on the vote page's XML link) produces the same bytes `fetch_raw` would
have returned, so both Senate generators read those first. See
docs/superpowers/plans/2026-10-31-senate-xml-manual-drop.md.

Precedence is fixed: committed XML here > senate.gov HTTP > Voteview. A dropped
file is the official record, so it is never provisional.

Only per-roll-call detail files are supported (`vote_<congress>_<session>_<nnnnn>.xml`,
named exactly as senate.gov names them). A saved `vote_menu_*.xml` index is NOT read:
treating a lone local index as "senate.gov is reachable" would send every roll call
we do not hold down the HTTP path to a 403 instead of to Voteview.

Stdlib only - run-script-tests.yml installs no pip packages.
"""
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

#: scripts/data/ is not served by Jekyll, so ~10-30 KB per roll call stays out of the site.
DROP_DIR = Path(__file__).resolve().parent.parent / "data" / "senate-xml"

_NAME = re.compile(r"^vote_(\d+)_(\d)_(\d{5})\.xml$")


def filename(congress, session, number):
    return f"vote_{congress}_{session}_{number:05d}.xml"


def _valid(raw, congress, session, number):
    """True if `raw` is plausibly the roll call its filename claims.

    A mis-saved file (the WAF challenge page, an HTML vote page saved as .xml, the
    browser's rendered tree text) must not be taken as the official record, so
    bytes that do not parse are refused outright rather than half-trusted.
    """
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return False
    if root.tag != "roll_call_vote" or root.find(".//question") is None:
        return False
    claimed = (root.findtext("vote_number") or "").strip()
    if claimed and claimed.isdigit() and int(claimed) != number:
        return False
    for tag, want in (("congress", congress), ("session", session)):
        got = (root.findtext(tag) or "").strip()
        if got and got.isdigit() and int(got) != want:
            return False
    return True


def read_roll(congress, session, number, directory=None):
    """Bytes of a dropped roll-call file, or None if absent or not a valid roll call."""
    path = Path(directory or DROP_DIR) / filename(congress, session, number)
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if not _valid(raw, congress, session, number):
        print(f"  WARNING: {path.name} is not a valid Senate roll-call XML for "
              f"{congress}/{session}/{number} - ignored (re-save it from the vote page's "
              "XML link with Save As)", file=sys.stderr)
        return None
    return raw


def dropped_rolls(congress, directory=None):
    """Sorted [(session, number)] for every valid dropped file of this Congress."""
    base = Path(directory or DROP_DIR)
    found = []
    try:
        names = sorted(p.name for p in base.iterdir())
    except OSError:
        return found  # no drop directory: today's behaviour exactly
    for name in names:
        m = _NAME.match(name)
        if not m or int(m.group(1)) != congress:
            continue
        session, number = int(m.group(2)), int(m.group(3))
        if read_roll(congress, session, number, directory) is not None:
            found.append((session, number))
    return found


def official_url(congress, session, number):
    """The URL a person opens to save the file (the `.xml` the vote page links to)."""
    return ("https://www.senate.gov/legislative/LIS/roll_call_votes/"
            f"vote{congress}{session}/{filename(congress, session, number)}")
