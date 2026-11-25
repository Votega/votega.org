"""Former GA legislators: who counts as one, which bienniums they have, and the wording.

A former member is either a live roster record with a departed status, or a person who
appears only in a frozen biennium (assets/data/ga-bienniums/<tag>/ga-members.json). The
wording is fact and date only: no evaluation, no "lost" or "defeated".
"""
import datetime
import html
import json
import os
import re

from lib.ga_biennium_freeze import FROZEN_ROOT, MEMBERS
from lib.ga_legislator_pages import DEPARTED_STATUSES  # re-exported: the one definition
from lib.ga_sessions import session_slug

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_ROOT = os.path.join(REPO_ROOT, FROZEN_ROOT)

_VERB = {"Resigned": "Resigned", "Removed": "Removed from office", "Deceased": "Died in office"}


def load_frozen(root=DEFAULT_ROOT):
    """{tag: {gid: record}} from every frozen biennium under `root` (empty if none)."""
    out = {}
    if not os.path.isdir(root):
        return out
    for tag in sorted(os.listdir(root)):
        path = os.path.join(root, tag, MEMBERS)
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as f:
            members = json.load(f).get("members") or []
        out[tag] = {str(m["legisGaGovId"]): m for m in members if m.get("legisGaGovId") is not None}
    return out


def is_former(m, in_live):
    """A live member is former when departed; anyone only in a frozen biennium is former."""
    return (m.get("status") in DEPARTED_STATUSES) if in_live else True


def former_records(live_members, frozen):
    """[(record, tag)]: live departed members as (live record, "current"); frozen-only gids
    as (newest frozen record, that tag)."""
    out, live_gids = [], set()
    for m in live_members:
        gid = m.get("legisGaGovId")
        if gid is None:
            continue
        live_gids.add(str(gid))
        if is_former(m, True):
            out.append((m, "current"))
    newest = {}
    for tag in sorted(frozen):  # ascending, so a later tag overwrites
        for gid, rec in frozen[tag].items():
            if gid not in live_gids:
                newest[gid] = (rec, tag)
    out.extend(newest[g] for g in sorted(newest, key=lambda g: (newest[g][0].get("name") or "", g)))
    return out


def bienniums_for(gid, live_session_tag, frozen):
    """Bienniums a member has data for. `live_session_tag` is None for a frozen-only member."""
    gid = str(gid)
    tags = sorted((t for t in frozen if gid in frozen[t]), reverse=True)
    if live_session_tag is None:
        return tags
    return ["current"] + [t for t in tags if t != live_session_tag]


def _date(iso):
    d = datetime.date.fromisoformat(iso[:10])
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def departure_note(m):
    """"Resigned March 1, 2026", or None when the record carries no departure and date."""
    verb = _VERB.get(m.get("status"))
    if verb and m.get("statusDate"):
        return f"{verb} {_date(m['statusDate'])}"
    return None


def departure_sentence(m, tag):
    """`tag` is a real biennium tag (for a live record, pass the roster's metadata.session)."""
    house = "Senate" if "senate" in (m.get("chamber") or "").lower() else "House"
    years = session_slug(tag).replace("-", "–")
    s = f"Served in the Georgia {house}, District {m.get('district')}, in the {years} General Assembly."
    note = departure_note(m)
    if note:
        s += f" {note}."
    return s


_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")


def departure_source_html(m):
    """The editorial status note as safe HTML for the former-member banner, or "".

    Notes are plain text with [label](url) links. Prose that only repeats the date already
    in departure_note() is dropped and its links kept as the source.
    """
    note = (m.get("statusNote") or "").strip()
    if not note or departure_note(m) is None:
        return ""

    def link(match):
        return (f'<a href="{html.escape(match.group(2), quote=True)}" target="_blank" '
                f'rel="noopener">{html.escape(match.group(1))}</a>')

    links = [link(x) for x in _LINK.finditer(note)]
    if _date(m["statusDate"]) in _LINK.sub("", note):
        return f"Source: {', '.join(links)}." if links else ""
    out, at = "", 0
    for x in _LINK.finditer(note):
        out += html.escape(note[at:x.start()]) + link(x)
        at = x.end()
    out += html.escape(note[at:])
    return out if note.endswith(".") else out + "."


def service_years(m, tag):
    """"from 2013 to 2026" for a former member; "" without a start year. Ends with the year
    they left, else the January their last biennium's terms ended."""
    start = m.get("termStartYear")
    if not start:
        return ""
    if m.get("status") in DEPARTED_STATUSES and m.get("statusDate"):
        end = int(m["statusDate"][:4])
    else:
        end = int(session_slug(tag)[-4:]) + 1
    return f"in {start}" if end <= start else f"from {start} to {end}"


def job_title(m, former):
    base = "State Senator" if "senate" in (m.get("chamber") or "").lower() else "State Representative"
    return f"Former {base}" if former else base
