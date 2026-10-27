#!/usr/bin/env python3
"""Build assets/data/ga-counties.json: Georgia's 159 counties as SVG paths for the county results map.

Source: US Census Bureau cartographic boundary file (public domain), as a county GeoJSON keyed by FIPS
(e.g. plotly/datasets geojson-counties-fips.json). Usage: build_ga_county_shapes.py <counties.geojson>
"""
import json, math, sys

W = 600  # viewBox width; height follows the aspect ratio
TOL = 0.6  # Douglas-Peucker tolerance, in viewBox units


def dp(pts, tol):
    if len(pts) < 3:
        return pts
    (x1, y1), (x2, y2) = pts[0], pts[-1]
    dx, dy = x2 - x1, y2 - y1
    norm = math.hypot(dx, dy) or 1e-9
    idx, dmax = 0, 0
    for i in range(1, len(pts) - 1):
        d = abs(dy * pts[i][0] - dx * pts[i][1] + x2 * y1 - y2 * x1) / norm
        if d > dmax:
            idx, dmax = i, d
    if dmax <= tol:
        return [pts[0], pts[-1]]
    return dp(pts[:idx + 1], tol)[:-1] + dp(pts[idx:], tol)


def main(src):
    feats = [f for f in json.load(open(src))["features"] if f["properties"]["STATE"] == "13"]
    assert len(feats) == 159, len(feats)
    rings = lambda g: [r for p in ([g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]) for r in p]
    lons = [x for f in feats for r in rings(f["geometry"]) for x, _ in r]
    lats = [y for f in feats for r in rings(f["geometry"]) for _, y in r]
    k = math.cos(math.radians((min(lats) + max(lats)) / 2))  # shrink longitude so shapes aren't stretched
    x0, x1, y0, y1 = min(lons), max(lons), min(lats), max(lats)
    scale = W / ((x1 - x0) * k)
    H = round((y1 - y0) * scale)
    out = []
    for f in sorted(feats, key=lambda f: f["properties"]["COUNTY"]):
        parts = []
        for r in rings(f["geometry"]):
            pts = [((x - x0) * k * scale, (y1 - y) * scale) for x, y in r]
            h = len(pts) // 2  # a closed ring has identical ends, so simplify each half separately
            pts = dp(pts[:h + 1], TOL)[:-1] + dp(pts[h:], TOL)
            if len(pts) < 4:
                continue
            parts.append("M" + "L".join("%.1f %.1f" % p for p in pts[:-1]) + "Z")
        out.append({"fips": "13" + f["properties"]["COUNTY"], "name": f["properties"]["NAME"], "d": "".join(parts)})
    json.dump({"viewBox": [0, 0, W, H], "counties": out}, open("assets/data/ga-counties.json", "w"), separators=(",", ":"))
    print(len(out), "counties,", W, "x", H)


main(sys.argv[1])
