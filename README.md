# votega.org
Votega.org a site providing elected official information for citizens of the State of Georgia. 

## Refreshing Member data

[![Update Congress.gov current members data](https://github.com/Votega/votega.org/actions/workflows/update-current-members.yml/badge.svg)](https://github.com/Votega/votega.org/actions/workflows/update-current-members.yml)

[![Update Georgia General Assembly member data](https://github.com/Votega/votega.org/actions/workflows/update-ga-members.yml/badge.svg)](https://github.com/Votega/votega.org/actions/workflows/update-ga-members.yml)

[![Sync generated data files on PR](https://github.com/Votega/votega.org/actions/workflows/sync-generated-data-on-pr.yml/badge.svg)](https://github.com/Votega/votega.org/actions/workflows/sync-generated-data-on-pr.yml)

scripts/fetch_ga_executive_orders.py — scrapes gov.georgia.gov/executive-action/executive-orders/2026, handles pagination (?page=0, ?page=1, …), extracts order number/date/title/URL from the download link URLs (no fragile HTML parsing), merges with existing JSON so nothing is lost, and categorizes each order
.github/workflows/update-ga-executive-orders.yml — runs daily at 08:00 UTC, commits only if the current year file changed
publish-ga-executive-orders.yml — now only watches and publishes the current year file; 2023–2025 are left alone permanently
