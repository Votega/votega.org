# Old-to-new color map

Companion to `brand-migration-plan.md`. Use when replacing hard-coded colors. New values are **role tokens** (see the plan's token architecture); never paste the hex into components. "Files" = count of source files containing the value on 2026-10-21 (html/css/js/md/yml, excluding `_site`, `docs`, `assets/img/brand`).

**Judgment rule:** a blue or red is only replaced by a *party* token when it marks a party (badge, bar, seat, vote). When it is UI chrome (links, tabs, buttons, focus, headers) it becomes clay. Read the surrounding rule before replacing.

## UI blues and brand navy -> clay / neutrals

| Old | Files | Was | New token | Value |
|---|---|---|---|---|
| `#1a56a8` | 32 | UI blue (links, tabs, buttons) | `--color-accent` (links: `--color-link`) | `#b4521f` (`#9a4214`) |
| `#008aff` | 9 | theme hover/link blue | `--color-link-hover` | `#8a3b12` |
| `#0085a1` | 2 | Beautiful Jekyll default teal | `--color-link` | `#9a4214` |
| `#1a1a2e` | 6 | navy (navbar, og card, headings) | `--color-text` (text) / `--color-accent-strong` (fills) | `#2b2118` / `#8a3b12` |
| `#e8f0fe` | 5 | light blue tint | `--color-surface-tint` | `#fbefe4` |
| `#4f6edb` | 0 | (listed in plan; none found) | - | - |
| `#2471a3`, `#3498db` | 3 / 2 | results-layout blue | party D if it marks Democratic, else clay | see party table |

## Party colors (party data only)

| Old | Files | Meaning | New token | Value |
|---|---|---|---|---|
| `#2563eb`, `#1d4ed8`, `#2471a3`, `#3498db` | 9 / 18 / 3 / 2 | Democratic | `--color-party-d` | `#3333ff` |
| `#dbeafe` | 10 | Democratic badge bg | `--color-party-d-tint` | `#e7e7ff` |
| `#dc2626`, `#c0392b`, `#e74c3c` | 14 / 3 / 2 | Republican | `--color-party-r` (small text: `--color-party-r-text`) | `#e81b23` (`#cf151c`) |
| `#fee2e2` | 14 | Republican badge bg (**also used for error bg: check**) | `--color-party-r-tint` or `--color-danger-tint` | `#fce4e5` |
| `#7c3aed` | 6 | Independent (violet) | `--color-party-i` | `#a21caf` |
| independent/"other" grays | - | Independent shown gray | `--color-party-i` | `#a21caf` |
| vacant/empty seat gray | - | Vacant | `--color-party-vacant` (+ `-tint` `#f3f4f6`, `-text` `#374151`) | `#9ca3af` |

## Status colors

| Old | Files | Meaning | New token | Value |
|---|---|---|---|---|
| `#b91c1c` | 17 | Danger | `--color-danger` (unchanged value; always icon + label) | `#b91c1c` |
| `#854d0e` | 9 | Warning amber | `--color-warning` | `#806000` |
| `#c00` | 11 | ad hoc error/empty-state red | warning/gray message style (guide p.17); `--color-danger` only for real errors | `#806000` / `#b91c1c` |
| green success values | - | success/certified | `--color-success` | `#2f5d50` |

## Neutral grays

| Old | Files | New token | Value |
|---|---|---|---|
| `#777`, `#666` (muted text) | 25 / 26 | `--color-text-muted` | `#6b7280` |
| `#fff` surfaces (cards, inputs) | - | `--color-surface-raised` | `#ffffff` |
| page white / `#f8f8f8` etc. | - | `--color-surface` | `#fffaf4` |
| navbar/footer grays | - | `--color-surface-chrome` | `#f4ebe0` |
| `#ddd`/`#e5e5e5` borders | - | `--color-border` | `#e6c9b0` |

## Leave alone
`assets/css/bootstrap-social.css`, `assets/css/pygment_highlights.css`, and party colors inside `assets/img/brand/`.

## Known special cases
- `ga-executive-orders.html` JS `CATEGORY_DOT` (Appointment `#1a56a8`): category dots are not party data -> clay-family tokens.
- `_includes/entity/ga-legislator.html` ~line 1678: stray non-party accent `#1a56a8` for members who are neither D nor R -> `--color-party-i` / vacant by status.
- `#fee2e2` and `#c00` appear in both party and error contexts; decide per occurrence.
- Place-page land-use green / ALPR red watch colors: open decision (guide p.26).
