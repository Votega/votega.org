#!/usr/bin/env bash
# Regenerate the default Open Graph share card from og-default.html.
# Renders the HTML with headless Chromium at 1200x630 (the OG/Twitter standard)
# and writes /assets/img/og-default.png.
#
# Requires a Chromium/Chrome binary. Set CHROME to override auto-detection.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
src="$here/og-default.html"
out="$repo/assets/img/og-default.png"

CHROME="${CHROME:-}"
if [[ -z "$CHROME" ]]; then
  for c in /opt/pw-browsers/chromium chromium chromium-browser google-chrome google-chrome-stable; do
    if command -v "$c" >/dev/null 2>&1 || [[ -x "$c" ]]; then CHROME="$c"; break; fi
  done
fi
[[ -n "$CHROME" ]] || { echo "No Chromium/Chrome binary found; set CHROME=/path/to/chrome" >&2; exit 1; }

# Render in a taller window than needed. Headless Chromium's CSS layout viewport
# can come out shorter than the requested height, leaving the bottom of an exactly
# 630px-tall body unpainted; rendering tall guarantees the full card paints, then
# we crop to the exact 1200x630 top-left region.
raw="$(mktemp --suffix=.png)"
trap 'rm -f "$raw"' EXIT

"$CHROME" --headless=new --no-sandbox --hide-scrollbars --force-device-scale-factor=1 \
  --run-all-compositor-stages-before-draw --virtual-time-budget=4000 \
  --window-size=1200,960 --screenshot="$raw" "file://$src"

python3 - "$raw" "$out" <<'PY'
import sys
from PIL import Image
raw, out = sys.argv[1], sys.argv[2]
Image.open(raw).convert("RGB").crop((0, 0, 1200, 630)).save(out, optimize=True)
PY

echo "Wrote $out"
