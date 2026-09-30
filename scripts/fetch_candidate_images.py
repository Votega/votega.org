#!/usr/bin/env python3
"""Cache government-hosted candidate/member portraits locally, resized.

WHY THIS EXISTS
---------------
Candidate and officeholder photos are referenced in the data by their original
`imageUrl`. Many of those point at government portrait servers, and at least one
of them is expensive: a single `www.legis.ga.gov` portrait is ~3 MB of
full-resolution JPEG being downloaded to fill a ~120px card. Hot-linking them
also means every distinct host costs its own DNS + TLS handshake and none of the
bytes ride our own edge cache.

We fix that ONLY for government sources, where re-hosting the file is clean:
congress.gov is a federal work (public domain) and legis.ga.gov portraits are
the state's official likenesses provided for exactly this civic use. Photos from
campaign sites, Ballotpedia, Wix/Squarespace, and social CDNs are all-rights-
reserved by default and are deliberately left hot-linked (the render layer just
lazy-loads them) — attribution is not a copyright license, and re-hosting them
would create exposure the hot-link does not. See CLAUDE.md discussion.

WHAT IT DOES
------------
1. Walk each source JSON roster for `imageUrl` (and `depiction.imageUrl`) values.
2. Keep only URLs whose host is in ALLOWED_HOSTS.
3. For each, derive a STABLE filename from a hash of the URL and, IF NOT ALREADY
   CACHED, download it and resize to <= MAX_DIM px, re-encoded as optimized JPEG.
   Skip-if-exists is what keeps this idempotent: an unchanged roster produces no
   new bytes, so quiet runs commit nothing and git history does not bloat. (An
   image is binary and does not delta-compress, so re-fetching every run would
   grow .git without bound — never do that.)
4. Emit assets/data/candidate-image-cache.json mapping each cached source URL to
   its local path. The render layer consults this map to swap the src; a URL not
   in the map (any non-gov source) is rendered as-is.

Run:  python scripts/fetch_candidate_images.py
Deps: Pillow (build-time only; not shipped to the client).
"""

import hashlib
import io
import os
import sys
from datetime import datetime, timezone
from urllib.parse import urlparse

# sys.path[0] is scripts/ when run as `python scripts/fetch_candidate_images.py`,
# so the `lib` package resolves. Mirrors the other generators.
from lib.atomic_io import write_json_atomic
from lib.http import fetch_bytes

try:
    from PIL import Image
except ImportError:
    sys.exit("Pillow is required: pip install Pillow")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Rosters scanned for portrait URLs. The cache is URL-keyed, so a photo cached
#: from any one of these serves every page that renders that same URL (a race
#: card, a candidate page, the legislator's own profile).
SOURCE_FILES = [
    "assets/data/races.json",
    "assets/data/ga-members.json",
    "assets/data/current-members.json",
]

#: Only government sources are cached. Keep this tight — adding a non-gov host
#: here would re-host copyrighted images. Compared case-insensitively, with or
#: without a leading "www.".
ALLOWED_HOSTS = {
    "legis.ga.gov",
    "congress.gov",
}

OUTPUT_DIR = "assets/img/candidates"
MANIFEST_FILE = "assets/data/candidate-image-cache.json"

#: Longest edge of the stored image. Cards render at ~120px; 400px covers
#: retina and the largest profile-page render with lots of headroom.
MAX_DIM = 400
JPEG_QUALITY = 82

# A browser-ish UA — the default 'votega.org/1.0' can be refused by some CDNs.
UA = {"User-Agent": "Mozilla/5.0 (compatible; votega.org portrait cache)"}


def load_json(path):
    import json
    with open(os.path.join(REPO_ROOT, path), encoding="utf-8") as f:
        return json.load(f)


def host_allowed(url):
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return False
    if host.startswith("www."):
        host = host[4:]
    return host in ALLOWED_HOSTS


def collect_urls(objs):
    """Return the set of allowlisted portrait URLs found anywhere in the data."""
    urls = set()

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "imageUrl" and isinstance(v, str) and v and host_allowed(v):
                    urls.add(v)
                else:
                    walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)

    for o in objs:
        walk(o)
    return urls


def local_name(url):
    """Stable, collision-resistant filename derived from the URL itself.

    Same URL -> same file forever, which is what makes skip-if-exists safe.
    """
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    return "%s.jpg" % digest


def resize_to_jpeg(raw):
    """Return optimized JPEG bytes at <= MAX_DIM, or None if not a valid image."""
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception as exc:
        print("  not a decodable image: %s" % exc)
        return None

    # Flatten transparency / palette / CMYK onto white so JPEG is always valid.
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    img.thumbnail((MAX_DIM, MAX_DIM), Image.LANCZOS)

    out = io.BytesIO()
    img.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
    return out.getvalue()


def main():
    out_dir_abs = os.path.join(REPO_ROOT, OUTPUT_DIR)
    os.makedirs(out_dir_abs, exist_ok=True)

    rosters = []
    for path in SOURCE_FILES:
        try:
            rosters.append(load_json(path))
        except FileNotFoundError:
            print("skip (missing): %s" % path)
        except Exception as exc:
            sys.exit("Failed to read %s: %s" % (path, exc))

    if not rosters:
        sys.exit("No source rosters found — nothing to scan.")

    urls = sorted(collect_urls(rosters))
    print("Found %d unique government portrait URL(s) across %d roster(s)."
          % (len(urls), len(rosters)))

    manifest = {}
    fetched = skipped = failed = 0

    for url in urls:
        name = local_name(url)
        rel = "%s/%s" % (OUTPUT_DIR, name)
        abs_path = os.path.join(out_dir_abs, name)

        if os.path.exists(abs_path):
            manifest[url] = rel
            skipped += 1
            continue

        print("fetch: %s" % url)
        raw = fetch_bytes(url, headers=UA, timeout=45)
        if raw is None:
            failed += 1
            continue

        jpeg = resize_to_jpeg(raw)
        if jpeg is None:
            failed += 1
            continue

        # Plain write is fine: a torn portrait is self-healing (next run re-fetches
        # a missing/short file); the manifest is the only file that must stay
        # consistent, and that one is written atomically below.
        with open(abs_path, "wb") as f:
            f.write(jpeg)
        manifest[url] = rel
        fetched += 1
        print("  saved %s (%.1f KB, from %.1f KB source)"
              % (rel, len(jpeg) / 1024, len(raw) / 1024))

    payload = {
        "metadata": {
            "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "count": len(manifest),
            "sources": sorted(ALLOWED_HOSTS),
            "note": ("Local cache of government-hosted portraits only. "
                     "Non-government images stay hot-linked at their source."),
        },
        # Sorted for a stable, minimal diff between runs.
        "images": {u: manifest[u] for u in sorted(manifest)},
    }
    write_json_atomic(os.path.join(REPO_ROOT, MANIFEST_FILE), payload, indent=2)

    print("Done. %d fetched, %d already cached, %d failed. Manifest: %d entries."
          % (fetched, skipped, failed, len(manifest)))

    # A run that resolves nothing at all almost certainly means the rosters or
    # the network are broken — fail so CI does not overwrite a good manifest
    # with an empty one.
    if not manifest and urls:
        sys.exit("No portraits could be cached despite %d candidate URL(s) — "
                 "refusing to write an empty manifest." % len(urls))


if __name__ == "__main__":
    main()
