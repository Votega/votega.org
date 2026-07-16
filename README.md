# votega.org
Votega.org a site providing elected official information for citizens of the State of Georgia. 

## Refreshing Member data

[![Update Congress.gov current members data](https://github.com/Votega/votega.org/actions/workflows/update-current-members.yml/badge.svg)](https://github.com/Votega/votega.org/actions/workflows/update-current-members.yml)

[![Update Georgia General Assembly member data](https://github.com/Votega/votega.org/actions/workflows/update-ga-members.yml/badge.svg)](https://github.com/Votega/votega.org/actions/workflows/update-ga-members.yml)

[![Sync generated data files on PR](https://github.com/Votega/votega.org/actions/workflows/sync-generated-data-on-pr.yml/badge.svg)](https://github.com/Votega/votega.org/actions/workflows/sync-generated-data-on-pr.yml)

scripts/fetch_ga_executive_orders.py — scrapes gov.georgia.gov/executive-action/executive-orders/2026, handles pagination (?page=0, ?page=1, …), extracts order number/date/title/URL from the download link URLs (no fragile HTML parsing), merges with existing JSON so nothing is lost, and categorizes each order
.github/workflows/update-ga-executive-orders.yml — runs daily at 08:00 UTC, commits only if the current year file changed
publish-ga-executive-orders.yml — now only watches and publishes the current year file; 2023–2025 are left alone permanently

## GA Bills & Resolutions tracker

`ga-bills.html` — a searchable, filterable tracker for all 5,480 bills and resolutions from the Georgia General Assembly's 2025–26 regular session.

**Data pipeline:**

1. `scripts/generate_ga_bills_data.py` — fetches all bills for the 2025–26 session live from the Open States API and writes the compact `assets/data/ga-bills.json` (~5 MB) that the page loads. Requires `OPENSTATES_API_KEY`:
   ```
   python scripts/generate_ga_bills_data.py
   ```
   The script strips the full action history (too large for the browser), keeps passage vote counts with motion text (roll call number), and auto-tags bills as "Local / Municipal" when the title starts with a Georgia county name.
2. `.github/workflows/update-ga-bills.yml` — runs the script weekly (Sundays 07:30 UTC), then re-enriches with party vote tallies before committing.
3. `assets/data/ga-bills.json` — the generated output committed to the repo and served statically.

`scripts/process_ga_bills.py` is retired — it only existed to transform the one-time May 2026 bulk export (`GA_2025_26_bills.json`) that `generate_ga_bills_data.py` now replaces. Output schema is unchanged, so `ga-bills.html` needed no changes.
