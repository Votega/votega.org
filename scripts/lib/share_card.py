"""Per-entity share cards (1200x630 Open Graph images), as pure functions.

`build_entity_pages.py` records one row per entity (see `add_card` there); this module
turns a row into the card's HTML and patches the generated page's front matter. The
rendering itself (headless Chromium) lives in `build_share_cards.py`, so everything here
is testable with no browser.

Design source: assets/img/brand/style-guide-peach.html, "Entity card (person / race)".
Rules that shape this file:
  * Party colour appears only on the party badge, never as the card's background.
  * Every candidate in a race gets the same layout, so a person with no usable photo
    gets the monogram circle (a portrait fills the same circle).
  * Portraits only if they come from a government source: a row's `photo` is set only
    when the URL is in candidate-image-cache.json, which holds government hosts only.
  * 64px margin, nothing under 24px, headline 48px or more.
  * Colours come from tokens.css (inlined by the renderer); none are literal here.
"""
from __future__ import annotations

import base64
import html
import mimetypes
import os
import re

CARD_W, CARD_H = 1200, 630

# Tokens in tokens.css for each party; an unlisted party gets a neutral clay badge.
_PARTY_TOKENS = {
    "democrat": "d",
    "republican": "r",
    "independent": "i",
}

_STAR = ('<svg viewBox="0 0 24 24" width="30" height="30" aria-hidden="true"><path fill="currentColor" '
         'd="M12 2l3.1 6.3 6.9 1-5 4.9 1.2 6.8L12 17.8 5.8 21l1.2-6.8-5-4.9 6.9-1z"/></svg>')

# A ballot box with a check: the race card's counterpart to a person's portrait.
_BALLOT = ('<svg viewBox="0 0 64 64" width="170" height="170" aria-hidden="true" fill="none" '
           'stroke="currentColor" stroke-width="4" stroke-linecap="round" stroke-linejoin="round">'
           '<rect x="8" y="30" width="48" height="26" rx="4"/><path d="M22 30V14h20v16"/>'
           '<path d="M27 22l4 4 7-8"/><path d="M20 43h24"/></svg>')


def esc(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def party_key(party) -> str | None:
    p = (party or "").lower()
    for needle, key in _PARTY_TOKENS.items():
        if needle in p:
            return key
    return None


_SUFFIX = re.compile(r"\s+(jr\.?|sr\.?|ii|iii|iv)$", re.I)


def display_name(name) -> str:
    """The name as printed. Source data sometimes cases a numeral suffix as "Iii"; fix that,
    and bind the suffix to the last word with a no-break space so it never wraps alone."""
    name = (name or "").strip()
    m = _SUFFIX.search(name)
    if not m:
        return name
    suf = m.group(1)
    suf = suf.upper() if suf.lower() in ("ii", "iii", "iv") else suf.capitalize()
    return name[: m.start()] + " " + suf


def monogram(name) -> str:
    """Initials for the placeholder circle: first + last word, ignoring suffixes/titles."""
    skip = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv", "mr", "mr.", "mrs", "mrs.", "ms", "ms.", "dr", "dr."}
    words = [w for w in re.split(r"\s+", (name or "").strip()) if w and w.lower() not in skip]
    letters = [w[0] for w in words if w[0].isalpha()]
    if not letters:
        return "VG"
    pair = letters[0] + (letters[-1] if len(letters) > 1 else "")
    return pair.upper()


def name_font_px(name) -> int:
    """Headline size that keeps the name to about two lines. Never below the guide's 48px."""
    n = len(name or "")
    if n <= 16:
        return 78
    if n <= 24:
        return 66
    if n <= 34:
        return 56
    return 48


def _data_uri(path: str) -> str | None:
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError:
        return None
    mime = mimetypes.guess_type(path)[0] or "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def fmt_stamp(iso) -> str | None:
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(iso or ""))
    if not m:
        return None
    months = ["January", "February", "March", "April", "May", "June", "July", "August",
              "September", "October", "November", "December"]
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not 1 <= mo <= 12:
        return None
    return f"{months[mo - 1]} {d}, {y}"


def card_parts(row: dict, repo_root: str) -> tuple[str, str]:
    """(card-specific CSS, body markup) for one card. `row` is a manifest row (see add_card)."""
    name = display_name(row.get("name"))
    kind = row.get("kind") or "person"

    if kind == "race":
        badge_inner = f'<div class="mono race">{_BALLOT}</div>'
    else:
        photo = _data_uri(os.path.join(repo_root, row["photo"])) if row.get("photo") else None
        if photo:
            badge_inner = f'<div class="mono"><img src="{photo}" alt=""></div>'
        else:
            badge_inner = f'<div class="mono"><span class="mono-text">{esc(monogram(name))}</span></div>'

    pills = []
    pk = party_key(row.get("party"))
    if row.get("party"):
        cls = f"p-{pk}" if pk else "p-n"
        pills.append(f'<span class="pill {cls}">{esc(row["party"])}</span>')
    for b in row.get("badges") or []:
        pills.append(f'<span class="pill p-n">{_STAR if b in ("Incumbent", "Current Officeholder") else ""}{esc(b)}</span>')

    stamp = fmt_stamp(row.get("stamp"))
    foot_bits = []
    if stamp:
        foot_bits.append(f"Data last updated: {stamp}")
    if row.get("source"):
        foot_bits.append(f"Source: {row['source']}")

    fact = row.get("fact")
    css = f"""* {{ margin: 0; padding: 0; box-sizing: border-box; }}
html, body {{ width: {CARD_W}px; height: {CARD_H}px; }}
body {{ font-family: "Public Sans", "Liberation Sans", Arial, sans-serif; background: var(--color-surface);
  color: var(--color-text); position: relative; overflow: hidden; }}
.band {{ position: absolute; left: 0; right: 0; bottom: 0; height: 18px; background: var(--color-accent); }}
.row {{ position: absolute; left: 64px; right: 64px; top: 56px; bottom: 120px; display: flex; gap: 56px; align-items: center; }}
.mono {{ flex: none; width: 300px; height: 300px; border-radius: 50%; overflow: hidden; display: grid; place-items: center;
  background: var(--color-surface-sunken); border: 6px solid var(--color-border); color: var(--color-accent-strong);
  font-size: 120px; font-weight: 700; }}
.mono.race {{ border-radius: 36px; }}
.mono img {{ width: 100%; height: 100%; object-fit: cover; object-position: center top; }}
.txt {{ min-width: 0; }}
.name {{ font-weight: 700; line-height: 1.08; font-size: {name_font_px(name)}px;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }}
.role {{ font-size: 36px; color: var(--color-text-muted); margin: 12px 0 22px; line-height: 1.2;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }}
.pills {{ display: flex; gap: 14px; align-items: center; flex-wrap: wrap; }}
.pill {{ display: inline-flex; align-items: center; gap: 8px; border-radius: 40px; padding: 4px 22px;
  font-weight: 700; font-size: 28px; line-height: 1.3; }}
.p-d {{ background: var(--color-party-d-tint); color: var(--color-party-d-text); }}
.p-r {{ background: var(--color-party-r-tint); color: var(--color-party-r-text); }}
.p-i {{ background: var(--color-party-i-tint); color: var(--color-party-i-text); }}
.p-n {{ background: var(--color-surface-tint); color: var(--color-accent-strong); }}
.fact {{ font-size: 32px; margin-top: 26px; line-height: 1.25; }}
.foot {{ position: absolute; left: 64px; right: 64px; bottom: 44px; display: flex; justify-content: space-between;
  align-items: baseline; gap: 32px; font-size: 24px; color: var(--color-text-muted); }}
.domain {{ color: var(--color-accent-strong); font-weight: 700; letter-spacing: .16em; white-space: nowrap; }}
"""
    body = f"""<div class="row">
  {badge_inner}
  <div class="txt">
    <div class="name">{esc(name)}</div>
    {f'<div class="role">{esc(row.get("role"))}</div>' if row.get("role") else ''}
    {f'<div class="pills">{"".join(pills)}</div>' if pills else ''}
    {f'<div class="fact">{esc(fact)}</div>' if fact else ''}
  </div>
</div>
<div class="foot"><span>{esc(" · ".join(foot_bits))}</span><span class="domain">VOTEGA.ORG</span></div>
<div class="band"></div>
"""
    return css, body


SHELL_HEAD = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Public+Sans:wght@400;600;700&display=swap">"""


def shell_html(tokens_css: str) -> str:
    """The page every card is drawn into: fonts + tokens once, then card_parts swapped in."""
    return f"""{SHELL_HEAD}
<style>
{tokens_css}
</style><style id="card"></style></head><body></body></html>"""


def card_html(row: dict, tokens_css: str, repo_root: str) -> str:
    """One complete standalone document (used by tests and for a single render)."""
    css, body = card_parts(row, repo_root)
    return f"""{SHELL_HEAD}
<style>
{tokens_css}
{css}</style></head>
<body>
{body}</body></html>"""


def patch_front_matter(path: str, img_url: str) -> bool:
    """Insert `share-img:` into a generated entity page's front matter. Idempotent.

    Returns True if the file now carries the line. The pages are build artifacts
    (_entities/ is regenerated on every deploy), so this never touches tracked files.
    """
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    if not text.startswith("---\n"):
        return False
    end = text.find("\n---\n", 4)
    if end == -1:
        return False
    front, rest = text[: end + 1], text[end + 1:]
    front = re.sub(r"^share-img:.*\n", "", front, flags=re.M)  # never keep two keys
    front += f"share-img: {img_url}\n"
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(front + rest)
    return True
