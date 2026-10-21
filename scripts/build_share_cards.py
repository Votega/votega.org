#!/usr/bin/env python3
"""Render a 1200x630 share card per entity and point each page's `share-img` at it.

Runs in deploy-pages.yml between build_entity_pages.py (which writes the manifest of
rows and the `_entities/` pages) and the Jekyll build. Output goes to
assets/img/share/<section>/<slug>.png, which is gitignored: the PNGs exist only in the
deployed site, so history never carries ~1,300 binaries. About 100 MB for ~1,300 PNGs: JPEG at q90 was no smaller (86 MB) and softens the text.

Failure policy: this step is non-fatal in the workflow. A page only gets `share-img`
once its PNG is on disk, so any entity whose card did not render falls back to the
site default (og-default.png). If the web font did not load, nothing is rendered at
all and the script exits 1, because a card in a fallback face would ship quietly wrong.

Usage:
  python3 scripts/build_share_cards.py            # all rows in the manifest
  python3 scripts/build_share_cards.py --limit 20 # first N rows (local check)
  python3 scripts/build_share_cards.py --only ga-legislators/akbar-ali-house-106
Needs `pip install playwright` and a Chromium: the bundled one (`playwright install
chromium`) or a system Chrome (set CHROME_CHANNEL=chrome).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.share_card import CARD_H, CARD_W, card_parts, patch_front_matter, shell_html  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, ".share-cards", "manifest.json")
OUT_DIR = os.path.join(ROOT, "assets", "img", "share")
ENTITIES_DIR = os.path.join(ROOT, "_entities")
TOKENS = os.path.join(ROOT, "assets", "css", "tokens.css")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--only", help="section/slug to render, e.g. candidates/jane-doe-ga-house-5")
    args = ap.parse_args()

    if not os.path.exists(MANIFEST):
        print("build_share_cards: no manifest (build_entity_pages.py did not run); skipping", file=sys.stderr)
        return 1
    with open(MANIFEST, encoding="utf-8") as fh:
        rows = json.load(fh).get("cards") or []
    if args.only:
        rows = [r for r in rows if f"{r['section']}/{r['slug']}" == args.only]
    if args.limit:
        rows = rows[: args.limit]
    if not rows:
        print("build_share_cards: nothing to render", file=sys.stderr)
        return 1
    with open(TOKENS, encoding="utf-8") as fh:
        tokens_css = fh.read()

    from playwright.sync_api import sync_playwright  # lazy: the unit tests need no browser

    done = failed = 0
    with sync_playwright() as p:
        launch = {"channel": os.environ["CHROME_CHANNEL"]} if os.environ.get("CHROME_CHANNEL") else {}
        browser = p.chromium.launch(**launch)
        page = browser.new_page(viewport={"width": CARD_W, "height": CARD_H}, device_scale_factor=1)
        # Fonts and tokens load once; each card then only swaps its own CSS and body in.
        # (set_content per card re-fetched the font stylesheet: ~0.55 s a card, ~12 minutes
        # for a full run, against a fraction of that now.)
        page.set_content(shell_html(tokens_css), wait_until="networkidle")
        page.evaluate("document.fonts.load('700 40px \"Public Sans\"')")
        page.evaluate("document.fonts.ready")
        if not page.evaluate("document.fonts.check('700 40px \"Public Sans\"')"):
            print("build_share_cards: Public Sans did not load; refusing to render in a fallback face",
                  file=sys.stderr)
            return 1
        for i, row in enumerate(rows):
            try:
                css, body = card_parts(row, ROOT)
                page.evaluate("([css, body]) => { document.getElementById('card').textContent = css;"
                              " document.body.innerHTML = body; return document.fonts.ready; }", [css, body])
                page.wait_for_function("Array.from(document.images).every(i => i.complete)")
                rel = f"{row['section']}/{row['slug']}.png"
                dest = os.path.join(OUT_DIR, *rel.split("/"))
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                page.screenshot(path=dest, clip={"x": 0, "y": 0, "width": CARD_W, "height": CARD_H})
                entity = os.path.join(ENTITIES_DIR, row["section"], row["slug"] + ".html")
                if os.path.exists(entity) and patch_front_matter(entity, f"/assets/img/share/{rel}"):
                    done += 1
                else:
                    os.remove(dest)  # a card nothing points at is only weight in the deploy
                    failed += 1
            except Exception as exc:  # one bad row must not lose the rest
                failed += 1
                print(f"  {row.get('section')}/{row.get('slug')}: {exc}", file=sys.stderr)
            if (i + 1) % 200 == 0:
                print(f"  {i + 1}/{len(rows)}")
        browser.close()
    print(f"build_share_cards: {done} cards, {failed} skipped")
    return 0 if done else 1


if __name__ == "__main__":
    sys.exit(main())
